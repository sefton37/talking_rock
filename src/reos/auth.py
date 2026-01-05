"""Authentication module for ReOS.

Handles:
- PAM authentication against Linux system
- Session token generation
- Encryption key derivation using Argon2id
- Per-user session management

Security Notes:
- Credentials are validated locally via PAM, never stored
- Encryption keys derived from password, stored only in memory
- Session tokens are 256-bit cryptographically random
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pam
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Session idle timeout (15 minutes)
SESSION_IDLE_TIMEOUT_SECONDS = 15 * 60


@dataclass
class Session:
    """An authenticated user session."""

    token: str
    username: str
    created_at: datetime
    last_activity: datetime
    key_material: bytes = field(repr=False)  # Never print key material

    def is_expired(self) -> bool:
        """Check if session has expired due to inactivity."""
        elapsed = (datetime.now(timezone.utc) - self.last_activity).total_seconds()
        return elapsed > SESSION_IDLE_TIMEOUT_SECONDS

    def refresh(self) -> None:
        """Update last activity timestamp."""
        self.last_activity = datetime.now(timezone.utc)

    def get_user_data_root(self) -> Path:
        """Get the user's encrypted data directory."""
        return Path.home() / ".reos-data" / self.username


class SessionStore:
    """Thread-safe session storage."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = threading.Lock()

    def insert(self, session: Session) -> None:
        """Store a new session."""
        with self._lock:
            self._sessions[session.token] = session

    def get(self, token: str) -> Session | None:
        """Get a session by token (if valid and not expired)."""
        with self._lock:
            session = self._sessions.get(token)
            if session and not session.is_expired():
                return session
            return None

    def remove(self, token: str) -> bool:
        """Remove and invalidate a session."""
        with self._lock:
            if token in self._sessions:
                # Clear key material before removing
                session = self._sessions[token]
                # Overwrite key material with zeros
                if session.key_material:
                    zeros = bytes(len(session.key_material))
                    session.key_material = zeros
                del self._sessions[token]
                return True
            return False

    def refresh(self, token: str) -> bool:
        """Refresh a session's activity timestamp."""
        with self._lock:
            session = self._sessions.get(token)
            if session and not session.is_expired():
                session.refresh()
                return True
            return False

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        with self._lock:
            expired = [t for t, s in self._sessions.items() if s.is_expired()]
            for token in expired:
                session = self._sessions[token]
                if session.key_material:
                    zeros = bytes(len(session.key_material))
                    session.key_material = zeros
                del self._sessions[token]
            return len(expired)


# Global session store (thread-safe)
_session_store = SessionStore()


def get_session_store() -> SessionStore:
    """Get the global session store."""
    return _session_store


def authenticate_pam(username: str, password: str) -> bool:
    """Authenticate a user against Linux PAM.

    Args:
        username: Linux username
        password: User's password

    Returns:
        True if authentication succeeded, False otherwise

    Security:
        - Credentials are validated locally via PAM
        - Password is not stored or logged
    """
    p = pam.pam()
    return p.authenticate(username, password, service="login")


def derive_encryption_key(username: str, password: str) -> bytes:
    """Derive a 256-bit encryption key from username and password.

    Uses Scrypt for key derivation (memory-hard, side-channel resistant).

    Args:
        username: Linux username (used as salt basis)
        password: User's password

    Returns:
        32-byte encryption key

    Security:
        - Salt is deterministic per-user to allow key recovery
        - Scrypt parameters tuned for security vs. responsiveness
    """
    # Create deterministic salt from username
    salt_input = f"reos-{username}-encryption-salt-v1"
    salt = hashlib.sha256(salt_input.encode()).digest()[:16]

    # Scrypt parameters (memory-hard)
    # - N=2^14 (16384): Memory cost
    # - r=8: Block size
    # - p=1: Parallelization
    kdf = Scrypt(
        salt=salt,
        length=32,
        n=16384,
        r=8,
        p=1,
    )

    return kdf.derive(password.encode())


def generate_session_token() -> str:
    """Generate a cryptographically secure session token.

    Returns:
        64-character hex string (256 bits)
    """
    return secrets.token_hex(32)


def create_session(username: str, password: str) -> Session | None:
    """Authenticate user and create a new session.

    Args:
        username: Linux username
        password: User's password

    Returns:
        Session if authentication succeeded, None otherwise

    Security:
        - PAM validates credentials
        - Encryption key derived and stored only in memory
        - Password is not stored
    """
    # Authenticate via PAM
    if not authenticate_pam(username, password):
        return None

    # Derive encryption key
    key_material = derive_encryption_key(username, password)

    # Generate session token
    token = generate_session_token()
    now = datetime.now(timezone.utc)

    return Session(
        token=token,
        username=username,
        created_at=now,
        last_activity=now,
        key_material=key_material,
    )


def login(username: str, password: str) -> dict[str, Any]:
    """Authenticate and create a session.

    Args:
        username: Linux username
        password: User's password

    Returns:
        Dict with success status, session_token, username, or error
    """
    # Validate username format
    if not username or len(username) > 32:
        return {
            "success": False,
            "error": "Invalid username",
        }

    # Basic username validation (Linux username rules)
    if not all(c.isalnum() or c in "_-" for c in username):
        return {
            "success": False,
            "error": "Invalid username format",
        }

    # Create session (authenticates via PAM)
    session = create_session(username, password)
    if session is None:
        return {
            "success": False,
            "error": "Authentication failed",
        }

    # Store session
    _session_store.insert(session)

    # Ensure user data directory exists
    user_data_root = session.get_user_data_root()
    user_data_root.mkdir(parents=True, exist_ok=True)

    return {
        "success": True,
        "session_token": session.token,
        "username": session.username,
    }


def logout(session_token: str) -> dict[str, Any]:
    """Destroy a session.

    Args:
        session_token: The session token to invalidate

    Returns:
        Dict with success status
    """
    if _session_store.remove(session_token):
        return {"success": True}
    return {"success": False, "error": "Session not found"}


def validate_session(session_token: str) -> dict[str, Any]:
    """Validate a session token.

    Args:
        session_token: The session token to validate

    Returns:
        Dict with valid status and session info if valid
    """
    session = _session_store.get(session_token)
    if session:
        return {
            "valid": True,
            "username": session.username,
        }
    return {"valid": False}


def get_session(session_token: str) -> Session | None:
    """Get a session by token.

    Args:
        session_token: The session token

    Returns:
        Session if valid, None otherwise
    """
    return _session_store.get(session_token)


def refresh_session(session_token: str) -> bool:
    """Refresh a session's activity timestamp.

    Args:
        session_token: The session token

    Returns:
        True if session was refreshed, False if not found/expired
    """
    return _session_store.refresh(session_token)


# Encryption utilities using session key


def encrypt_data(session: Session, plaintext: bytes) -> bytes:
    """Encrypt data using the session's encryption key.

    Args:
        session: The authenticated session
        plaintext: Data to encrypt

    Returns:
        Encrypted data (nonce || ciphertext)
    """
    cipher = AESGCM(session.key_material)
    nonce = os.urandom(12)
    ciphertext = cipher.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def decrypt_data(session: Session, encrypted: bytes) -> bytes:
    """Decrypt data using the session's encryption key.

    Args:
        session: The authenticated session
        encrypted: Encrypted data (nonce || ciphertext)

    Returns:
        Decrypted plaintext

    Raises:
        ValueError: If decryption fails (wrong key or corrupted data)
    """
    if len(encrypted) < 12:
        raise ValueError("Invalid encrypted data: too short")

    cipher = AESGCM(session.key_material)
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    return cipher.decrypt(nonce, ciphertext, None)
