#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod kernel;

use kernel::{KernelError, KernelProcess};
use serde_json::Value;
use std::io::Write;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use tauri::State;
use users::{get_current_uid, get_user_by_uid};

struct KernelState(Arc<Mutex<Option<KernelProcess>>>);

#[tauri::command]
fn kernel_start(state: State<'_, KernelState>) -> Result<(), String> {
    let mut guard = state.0.lock().map_err(|_| "lock poisoned".to_string())?;
    if guard.is_some() {
        return Ok(());
    }
    let proc = KernelProcess::start().map_err(|e| e.to_string())?;
    *guard = Some(proc);
    Ok(())
}

#[tauri::command]
async fn kernel_request(state: State<'_, KernelState>, method: String, params: Value) -> Result<Value, String> {
    // IMPORTANT: The Python RPC is blocking I/O (stdin/stdout). If we do it on
    // Tauri's main thread, the WebView can miss paints, which feels like UI lag.
    // Offload to a background thread so the user message + thinking bubble
    // render immediately.
    let state = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut guard = state.lock().map_err(|_| "lock poisoned".to_string())?;
        if guard.is_none() {
            let proc = KernelProcess::start().map_err(|e| e.to_string())?;
            *guard = Some(proc);
        }

        let proc = guard.as_mut().ok_or_else(|| KernelError::NotStarted.to_string())?;
        proc.request(&method, params).map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| format!("kernel_request join error: {e}"))?
}

/// Get the current system username
#[tauri::command]
fn get_current_user() -> Result<String, String> {
    let uid = get_current_uid();
    get_user_by_uid(uid)
        .map(|user| user.name().to_string_lossy().into_owned())
        .ok_or_else(|| "Could not determine current user".to_string())
}

/// Authenticate a user against the system (using unix_chkpwd helper)
#[tauri::command]
async fn pam_authenticate(username: String, password: String) -> Result<bool, String> {
    // Run authentication in a blocking thread since it involves process spawning
    tauri::async_runtime::spawn_blocking(move || {
        // unix_chkpwd is a setuid helper that verifies passwords against PAM/shadow
        // It's standard on most Linux distributions
        let mut child = Command::new("unix_chkpwd")
            .arg(&username)
            .arg("nullok")
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|e| format!("Failed to spawn auth helper: {}", e))?;

        // Send the password to unix_chkpwd via stdin
        if let Some(mut stdin) = child.stdin.take() {
            stdin
                .write_all(password.as_bytes())
                .map_err(|e| format!("Failed to send credentials: {}", e))?;
        }

        let status = child
            .wait()
            .map_err(|e| format!("Auth process failed: {}", e))?;

        if status.success() {
            Ok(true)
        } else {
            Err("Invalid credentials".to_string())
        }
    })
    .await
    .map_err(|e| format!("Auth thread error: {}", e))?
}

fn main() {
    tauri::Builder::default()
        .manage(KernelState(Arc::new(Mutex::new(None))))
        .invoke_handler(tauri::generate_handler![
            kernel_start,
            kernel_request,
            get_current_user,
            pam_authenticate
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
