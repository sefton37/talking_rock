#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod auth;
mod kernel;

use auth::{AuthResult, AuthState, SessionInfo};
use kernel::{KernelError, KernelProcess};
use serde_json::{json, Value};
use std::sync::{Arc, Mutex};

use tauri::State;

struct KernelState(Arc<Mutex<Option<KernelProcess>>>);

// =============================================================================
// Authentication Commands
// =============================================================================

/// Authenticate a user via Python kernel (PAM happens there)
///
/// Flow:
/// 1. Frontend calls this with username/password
/// 2. We forward to Python kernel's auth/login endpoint
/// 3. Python validates via PAM and derives encryption key
/// 4. Python returns success + session token
/// 5. We store the session token for future request validation
#[tauri::command]
async fn auth_login(
    state: State<'_, KernelState>,
    auth_state: State<'_, AuthState>,
    username: String,
    password: String,
) -> Result<AuthResult, String> {
    // Validate username format (prevent injection)
    if username.is_empty() || username.len() > 32 {
        return Ok(AuthResult {
            success: false,
            session_token: None,
            username: None,
            error: Some("Invalid username".to_string()),
        });
    }

    // Forward to Python kernel for PAM authentication
    let state_clone = state.0.clone();
    let result = tauri::async_runtime::spawn_blocking(move || {
        let mut guard = state_clone.lock().map_err(|_| "lock poisoned".to_string())?;
        if guard.is_none() {
            let proc = KernelProcess::start().map_err(|e| e.to_string())?;
            *guard = Some(proc);
        }

        let proc = guard
            .as_mut()
            .ok_or_else(|| KernelError::NotStarted.to_string())?;

        // Call Python's auth/login endpoint
        proc.request(
            "auth/login",
            json!({
                "username": username,
                "password": password,
            }),
        )
        .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| format!("auth_login join error: {e}"))??;

    // Parse response from Python
    let auth_result: AuthResult = serde_json::from_value(result)
        .map_err(|e| format!("Failed to parse auth response: {e}"))?;

    // If successful, store the session in Rust
    if auth_result.success {
        if let (Some(token), Some(uname)) = (&auth_result.session_token, &auth_result.username) {
            let session = auth::create_session(token.clone(), uname.clone());
            let mut store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
            store.insert(session);
        }
    }

    Ok(auth_result)
}

/// Log out and destroy a session (zeroizes key material)
#[tauri::command]
fn auth_logout(auth_state: State<'_, AuthState>, session_token: String) -> Result<(), String> {
    let mut store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
    if store.remove(&session_token) {
        Ok(())
    } else {
        Err("Session not found".to_string())
    }
}

/// Validate a session token
#[tauri::command]
fn auth_validate(auth_state: State<'_, AuthState>, session_token: String) -> Result<bool, String> {
    let store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
    Ok(store.get(&session_token).is_some())
}

/// Refresh session activity timestamp
#[tauri::command]
fn auth_refresh(auth_state: State<'_, AuthState>, session_token: String) -> Result<(), String> {
    let mut store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
    match store.get_mut(&session_token) {
        Some(session) => {
            session.refresh();
            Ok(())
        }
        None => Err("Session not found or expired".to_string()),
    }
}

/// Get current session info (for UI display)
#[tauri::command]
fn auth_get_session(
    auth_state: State<'_, AuthState>,
    session_token: String,
) -> Result<SessionInfo, String> {
    let store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
    auth::validate_session(&store, &session_token).ok_or_else(|| "Session not found".to_string())
}

// =============================================================================
// Kernel Commands (now session-aware)
// =============================================================================

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

/// Send a request to the Python kernel
///
/// # Security
/// - Requires valid session token
/// - Session info is injected into params for audit logging
/// - Credentials never reach the kernel
#[tauri::command]
async fn kernel_request(
    state: State<'_, KernelState>,
    auth_state: State<'_, AuthState>,
    session_token: String,
    method: String,
    params: Value,
) -> Result<Value, String> {
    // Validate session first (zero trust)
    let session_info = {
        let store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
        auth::validate_session(&store, &session_token)
            .ok_or_else(|| "Invalid or expired session".to_string())?
    };

    // Refresh session activity
    {
        let mut store = auth_state.0.lock().map_err(|_| "lock poisoned")?;
        if let Some(session) = store.get_mut(&session_token) {
            session.refresh();
        }
    }

    // Inject session info into params for kernel-side audit logging
    let mut enriched_params = match params {
        Value::Object(map) => Value::Object(map),
        Value::Null => json!({}),
        other => json!({ "value": other }),
    };

    if let Value::Object(ref mut map) = enriched_params {
        map.insert(
            "__session".to_string(),
            json!({
                "username": session_info.username,
                "session_id": session_info.session_id,
            }),
        );
    }

    // Forward to kernel on background thread
    let state = state.0.clone();
    tauri::async_runtime::spawn_blocking(move || {
        let mut guard = state.lock().map_err(|_| "lock poisoned".to_string())?;
        if guard.is_none() {
            let proc = KernelProcess::start().map_err(|e| e.to_string())?;
            *guard = Some(proc);
        }

        let proc = guard
            .as_mut()
            .ok_or_else(|| KernelError::NotStarted.to_string())?;
        proc.request(&method, enriched_params)
            .map_err(|e| e.to_string())
    })
    .await
    .map_err(|e| format!("kernel_request join error: {e}"))?
}

// =============================================================================
// Application Entry Point
// =============================================================================

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(KernelState(Arc::new(Mutex::new(None))))
        .manage(AuthState::new())
        .invoke_handler(tauri::generate_handler![
            // Auth commands
            auth_login,
            auth_logout,
            auth_validate,
            auth_refresh,
            auth_get_session,
            // Kernel commands
            kernel_start,
            kernel_request,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
