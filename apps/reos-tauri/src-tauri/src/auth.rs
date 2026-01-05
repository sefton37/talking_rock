//! Session Management for ReOS
//!
//! This module handles session token management. PAM authentication
//! and encryption happen in the Python kernel for better library support.
//!
//! Architecture:
//! - Frontend sends credentials to Python kernel via auth/login RPC
//! - Python validates via PAM, derives encryption key
//! - Python returns session token to Rust
//! - Rust stores session token and validates on each request
//! - Python handles encrypted storage with the derived key

use rand::RngCore;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

/// Session idle timeout (15 minutes)
const SESSION_IDLE_TIMEOUT: Duration = Duration::from_secs(15 * 60);

/// A user session with authentication state
pub struct Session {
    pub token: String,
    pub username: String,
    pub created_at: Instant,
    pub last_activity: Instant,
}

impl Session {
    /// Check if session has expired due to inactivity
    pub fn is_expired(&self) -> bool {
        self.last_activity.elapsed() > SESSION_IDLE_TIMEOUT
    }

    /// Update last activity timestamp
    pub fn refresh(&mut self) {
        self.last_activity = Instant::now();
    }
}

/// Thread-safe session store
pub struct SessionStore {
    sessions: HashMap<String, Session>,
}

impl SessionStore {
    pub fn new() -> Self {
        Self {
            sessions: HashMap::new(),
        }
    }

    /// Insert a new session
    pub fn insert(&mut self, session: Session) {
        self.sessions.insert(session.token.clone(), session);
    }

    /// Get a session by token (if valid and not expired)
    pub fn get(&self, token: &str) -> Option<&Session> {
        self.sessions.get(token).filter(|s| !s.is_expired())
    }

    /// Get a mutable session by token (if valid and not expired)
    pub fn get_mut(&mut self, token: &str) -> Option<&mut Session> {
        self.sessions.get_mut(token).filter(|s| !s.is_expired())
    }

    /// Remove a session
    pub fn remove(&mut self, token: &str) -> bool {
        self.sessions.remove(token).is_some()
    }

    /// Remove all expired sessions
    pub fn cleanup_expired(&mut self) {
        self.sessions.retain(|_, s| !s.is_expired());
    }
}

/// Thread-safe authentication state
pub struct AuthState(pub Arc<Mutex<SessionStore>>);

impl AuthState {
    pub fn new() -> Self {
        Self(Arc::new(Mutex::new(SessionStore::new())))
    }
}

/// Result of a login attempt (from Python kernel)
#[derive(Serialize, Deserialize, Clone)]
pub struct AuthResult {
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_token: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub username: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

/// Session info for injection into RPC params
#[derive(Serialize, Deserialize, Clone)]
pub struct SessionInfo {
    pub username: String,
    pub session_id: String, // Truncated token for logging (first 16 chars)
}

/// Generate a cryptographically secure session token
pub fn generate_session_token() -> String {
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    hex::encode(bytes)
}

/// Create a new session after Python kernel validates credentials
pub fn create_session(token: String, username: String) -> Session {
    let now = Instant::now();
    Session {
        token,
        username,
        created_at: now,
        last_activity: now,
    }
}

/// Validate a session token and return session info if valid
pub fn validate_session(store: &SessionStore, token: &str) -> Option<SessionInfo> {
    store.get(token).map(|session| SessionInfo {
        username: session.username.clone(),
        session_id: token.chars().take(16).collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_session_token_uniqueness() {
        let token1 = generate_session_token();
        let token2 = generate_session_token();
        assert_ne!(token1, token2);
        assert_eq!(token1.len(), 64); // 32 bytes hex-encoded
    }

    #[test]
    fn test_session_expiry() {
        let mut session = Session {
            token: "test".to_string(),
            username: "testuser".to_string(),
            created_at: Instant::now(),
            last_activity: Instant::now() - Duration::from_secs(20 * 60), // 20 mins ago
        };

        assert!(session.is_expired());
        session.refresh();
        assert!(!session.is_expired());
    }

    #[test]
    fn test_session_store() {
        let mut store = SessionStore::new();
        let token = generate_session_token();
        let session = create_session(token.clone(), "testuser".to_string());

        store.insert(session);
        assert!(store.get(&token).is_some());

        store.remove(&token);
        assert!(store.get(&token).is_none());
    }
}
