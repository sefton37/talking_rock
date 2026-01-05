"""Session context management for per-request session tracking.

Uses contextvars for async-safe, thread-safe session context.
Allows any code in the request path to access the current session
and its crypto storage without passing them through every function.

Usage:
    # At request start (in RPC handler):
    with session_context(session_info, crypto):
        # All code in this context can access:
        session = get_current_session()
        crypto = get_current_crypto_storage()
        username = get_current_username()
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from .crypto_storage import CryptoStorage


@dataclass
class SessionInfo:
    """Session info extracted from RPC request.

    This is the session metadata injected by Rust into params.__session.
    """

    username: str
    session_id: str  # Truncated token for logging (first 16 chars)


# Context variables for async-safe session storage
_current_session: contextvars.ContextVar[SessionInfo | None] = contextvars.ContextVar(
    "current_session", default=None
)
_current_crypto: contextvars.ContextVar["CryptoStorage | None"] = contextvars.ContextVar(
    "current_crypto", default=None
)


def get_current_session() -> SessionInfo | None:
    """Get the current session info.

    Returns:
        SessionInfo if in session context, None otherwise
    """
    return _current_session.get()


def get_current_crypto_storage() -> "CryptoStorage | None":
    """Get the current crypto storage.

    Returns:
        CryptoStorage if in session context with crypto, None otherwise
    """
    return _current_crypto.get()


def get_current_username() -> str | None:
    """Get the current username.

    Returns:
        Username if in session context, None otherwise
    """
    session = _current_session.get()
    return session.username if session else None


def get_current_session_id() -> str | None:
    """Get the current session ID (truncated for logging).

    Returns:
        Session ID if in session context, None otherwise
    """
    session = _current_session.get()
    return session.session_id if session else None


@contextmanager
def session_context(
    session_info: SessionInfo | dict[str, Any] | None,
    crypto: "CryptoStorage | None" = None,
) -> Iterator[SessionInfo | None]:
    """Context manager for setting session context.

    Args:
        session_info: SessionInfo object or dict from __session
        crypto: Optional CryptoStorage instance

    Yields:
        The SessionInfo object (or None if not provided)

    Example:
        with session_context(params.pop("__session", None)):
            # Process request with session context available
            handle_request()
    """
    # Convert dict to SessionInfo if needed
    if isinstance(session_info, dict):
        session_info = SessionInfo(
            username=session_info.get("username", ""),
            session_id=session_info.get("session_id", ""),
        )

    # Set context vars
    session_token = _current_session.set(session_info)
    crypto_token = _current_crypto.set(crypto)

    try:
        yield session_info
    finally:
        # Reset context vars
        _current_session.reset(session_token)
        _current_crypto.reset(crypto_token)


def set_session(
    session_info: SessionInfo | dict[str, Any],
    crypto: "CryptoStorage | None" = None,
) -> tuple[contextvars.Token, contextvars.Token]:
    """Set session context (for non-context-manager usage).

    Args:
        session_info: SessionInfo object or dict from __session
        crypto: Optional CryptoStorage instance

    Returns:
        Tuple of tokens for resetting context

    Note:
        You are responsible for calling reset_session() with the tokens.
        Prefer using session_context() context manager instead.
    """
    if isinstance(session_info, dict):
        session_info = SessionInfo(
            username=session_info.get("username", ""),
            session_id=session_info.get("session_id", ""),
        )

    session_token = _current_session.set(session_info)
    crypto_token = _current_crypto.set(crypto)
    return session_token, crypto_token


def reset_session(session_token: contextvars.Token, crypto_token: contextvars.Token) -> None:
    """Reset session context (for non-context-manager usage).

    Args:
        session_token: Token from set_session()
        crypto_token: Token from set_session()
    """
    _current_session.reset(session_token)
    _current_crypto.reset(crypto_token)


def require_session() -> SessionInfo:
    """Get current session, raising if not in session context.

    Returns:
        Current SessionInfo

    Raises:
        RuntimeError: If not in session context
    """
    session = get_current_session()
    if session is None:
        raise RuntimeError("Operation requires an authenticated session")
    return session


def require_crypto() -> "CryptoStorage":
    """Get current crypto storage, raising if not available.

    Returns:
        Current CryptoStorage

    Raises:
        RuntimeError: If crypto storage not available
    """
    crypto = get_current_crypto_storage()
    if crypto is None:
        raise RuntimeError("Operation requires encrypted storage (crypto context)")
    return crypto
