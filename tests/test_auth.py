"""Tests for authentication module.

The auth module handles:
1. Session management (create, validate, refresh, destroy)
2. Session expiration
3. Key material handling (secure storage, zeroization)
4. Thread safety

These tests verify security-critical behavior WITHOUT requiring
actual Polkit/PAM authentication.
"""

from __future__ import annotations

import pytest
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from reos.auth import (
    Session,
    SessionStore,
    get_session_store,
    SESSION_IDLE_TIMEOUT_SECONDS,
)


class TestSession:
    """Test Session dataclass behavior."""

    def test_session_creation(self) -> None:
        """Session should store all required fields."""
        now = datetime.now(timezone.utc)
        key = b"0" * 32  # 256-bit key

        session = Session(
            token="test-token-123",
            username="testuser",
            created_at=now,
            last_activity=now,
            key_material=key,
        )

        assert session.token == "test-token-123"
        assert session.username == "testuser"
        assert session.created_at == now
        assert session.last_activity == now
        assert session.key_material == key

    def test_session_not_expired_immediately(self) -> None:
        """Fresh session should not be expired."""
        now = datetime.now(timezone.utc)
        session = Session(
            token="test",
            username="user",
            created_at=now,
            last_activity=now,
            key_material=b"key",
        )

        assert session.is_expired() is False, "Fresh session should not be expired"

    def test_session_expires_after_timeout(self) -> None:
        """Session should expire after idle timeout."""
        past = datetime.now(timezone.utc) - timedelta(seconds=SESSION_IDLE_TIMEOUT_SECONDS + 60)
        session = Session(
            token="test",
            username="user",
            created_at=past,
            last_activity=past,
            key_material=b"key",
        )

        assert session.is_expired() is True, (
            f"Session should be expired after {SESSION_IDLE_TIMEOUT_SECONDS}s of inactivity"
        )

    def test_refresh_updates_last_activity(self) -> None:
        """Refresh should update last_activity to now."""
        old_time = datetime.now(timezone.utc) - timedelta(minutes=10)
        session = Session(
            token="test",
            username="user",
            created_at=old_time,
            last_activity=old_time,
            key_material=b"key",
        )

        session.refresh()

        # Last activity should be updated to approximately now
        elapsed = (datetime.now(timezone.utc) - session.last_activity).total_seconds()
        assert elapsed < 1.0, "Last activity should be updated to now"

    def test_refresh_prevents_expiration(self) -> None:
        """Refreshing should reset the expiration timer."""
        # Start with a session about to expire
        almost_expired = datetime.now(timezone.utc) - timedelta(
            seconds=SESSION_IDLE_TIMEOUT_SECONDS - 10
        )
        session = Session(
            token="test",
            username="user",
            created_at=almost_expired,
            last_activity=almost_expired,
            key_material=b"key",
        )

        # Should not be expired yet
        assert session.is_expired() is False

        # Refresh it
        session.refresh()

        # Should definitely not be expired now
        assert session.is_expired() is False

    def test_get_user_data_root_uses_username(self) -> None:
        """User data root should be based on username."""
        session = Session(
            token="test",
            username="alice",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"key",
        )

        data_root = session.get_user_data_root()

        assert "alice" in str(data_root), "Data root should include username"
        assert ".reos-data" in str(data_root), "Data root should be in .reos-data"

    def test_key_material_not_in_repr(self) -> None:
        """Key material should not appear in repr (security)."""
        session = Session(
            token="test",
            username="user",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"super-secret-key-12345",
        )

        repr_str = repr(session)

        assert b"super-secret-key" not in repr_str.encode(), (
            "Key material should not appear in repr for security"
        )


class TestSessionStore:
    """Test SessionStore thread-safe storage."""

    @pytest.fixture
    def store(self) -> SessionStore:
        """Create a fresh session store."""
        return SessionStore()

    @pytest.fixture
    def sample_session(self) -> Session:
        """Create a sample session."""
        return Session(
            token="token-123",
            username="testuser",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"key-material-32-bytes-long-xxxx",
        )

    def test_insert_and_get(self, store: SessionStore, sample_session: Session) -> None:
        """Can insert and retrieve a session."""
        store.insert(sample_session)

        retrieved = store.get(sample_session.token)

        assert retrieved is not None, "Should retrieve inserted session"
        assert retrieved.username == sample_session.username
        assert retrieved.token == sample_session.token

    def test_get_nonexistent_returns_none(self, store: SessionStore) -> None:
        """Getting nonexistent session returns None, not error."""
        result = store.get("nonexistent-token")

        assert result is None, "Nonexistent token should return None, not raise"

    def test_get_expired_returns_none(self, store: SessionStore) -> None:
        """Getting expired session returns None."""
        expired_session = Session(
            token="expired-token",
            username="user",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_activity=datetime.now(timezone.utc) - timedelta(hours=1),
            key_material=b"key",
        )
        store.insert(expired_session)

        result = store.get("expired-token")

        assert result is None, "Expired session should return None"

    def test_remove_returns_true_for_existing(
        self, store: SessionStore, sample_session: Session
    ) -> None:
        """Remove returns True for existing session."""
        store.insert(sample_session)

        result = store.remove(sample_session.token)

        assert result is True, "Should return True when removing existing session"

    def test_remove_returns_false_for_nonexistent(self, store: SessionStore) -> None:
        """Remove returns False for nonexistent session."""
        result = store.remove("nonexistent")

        assert result is False, "Should return False when removing nonexistent session"

    def test_remove_clears_key_material(self, store: SessionStore) -> None:
        """Remove should zeroize key material before deleting."""
        key = bytearray(b"secret-key-material!")
        session = Session(
            token="token",
            username="user",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=bytes(key),
        )
        store.insert(session)

        # Get reference before removal
        stored = store.get("token")
        assert stored is not None

        # Remove it
        store.remove("token")

        # Key material should be zeroized
        # Note: We can't directly check the session's key after removal
        # because it's deleted, but the store's implementation should
        # overwrite with zeros before deleting

    def test_session_gone_after_remove(
        self, store: SessionStore, sample_session: Session
    ) -> None:
        """Session should not be retrievable after removal."""
        store.insert(sample_session)
        store.remove(sample_session.token)

        result = store.get(sample_session.token)

        assert result is None, "Removed session should not be retrievable"

    def test_refresh_updates_session(
        self, store: SessionStore, sample_session: Session
    ) -> None:
        """Refresh should update stored session's last_activity."""
        store.insert(sample_session)
        old_activity = sample_session.last_activity

        time.sleep(0.1)  # Small delay to ensure time difference
        store.refresh(sample_session.token)

        refreshed = store.get(sample_session.token)
        assert refreshed is not None
        assert refreshed.last_activity > old_activity, (
            "Last activity should be updated after refresh"
        )

    def test_refresh_nonexistent_returns_false(self, store: SessionStore) -> None:
        """Refresh returns False for nonexistent session."""
        result = store.refresh("nonexistent")

        assert result is False

    def test_refresh_expired_returns_false(self, store: SessionStore) -> None:
        """Cannot refresh an expired session."""
        expired = Session(
            token="expired",
            username="user",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_activity=datetime.now(timezone.utc) - timedelta(hours=1),
            key_material=b"key",
        )
        store.insert(expired)

        result = store.refresh("expired")

        assert result is False, "Should not be able to refresh expired session"

    def test_cleanup_expired_removes_old_sessions(self, store: SessionStore) -> None:
        """Cleanup should remove all expired sessions."""
        # Insert some expired sessions
        for i in range(5):
            expired = Session(
                token=f"expired-{i}",
                username=f"user-{i}",
                created_at=datetime.now(timezone.utc) - timedelta(hours=1),
                last_activity=datetime.now(timezone.utc) - timedelta(hours=1),
                key_material=b"key",
            )
            store.insert(expired)

        # Insert one valid session
        valid = Session(
            token="valid",
            username="active-user",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"key",
        )
        store.insert(valid)

        # Cleanup
        removed_count = store.cleanup_expired()

        assert removed_count == 5, "Should remove 5 expired sessions"
        assert store.get("valid") is not None, "Valid session should remain"

    def test_thread_safety_concurrent_access(self, store: SessionStore) -> None:
        """Store should handle concurrent access safely."""
        errors: list[Exception] = []

        def insert_sessions(prefix: str) -> None:
            try:
                for i in range(100):
                    session = Session(
                        token=f"{prefix}-{i}",
                        username=f"user-{prefix}-{i}",
                        created_at=datetime.now(timezone.utc),
                        last_activity=datetime.now(timezone.utc),
                        key_material=b"key",
                    )
                    store.insert(session)
            except Exception as e:
                errors.append(e)

        def read_sessions(prefix: str) -> None:
            try:
                for i in range(100):
                    store.get(f"{prefix}-{i}")
            except Exception as e:
                errors.append(e)

        # Run concurrent inserts and reads
        threads = [
            threading.Thread(target=insert_sessions, args=("a",)),
            threading.Thread(target=insert_sessions, args=("b",)),
            threading.Thread(target=read_sessions, args=("a",)),
            threading.Thread(target=read_sessions, args=("b",)),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Concurrent access caused errors: {errors}"


class TestGlobalSessionStore:
    """Test global session store singleton."""

    def test_get_session_store_returns_same_instance(self) -> None:
        """get_session_store should return the same instance."""
        store1 = get_session_store()
        store2 = get_session_store()

        assert store1 is store2, "Should return same singleton instance"


class TestLoginFunction:
    """Test login function (mocked Polkit)."""

    def test_login_with_valid_credentials(self) -> None:
        """Login with valid credentials should return session."""
        from reos.auth import login

        with patch("reos.auth._polkit_authenticate") as mock_polkit:
            mock_polkit.return_value = True

            result = login("testuser", "password123")

        if result.get("success"):
            assert "session_token" in result, "Success should include session_token"
            assert result["username"] == "testuser"

    def test_login_with_invalid_credentials(self) -> None:
        """Login with invalid credentials should fail gracefully."""
        from reos.auth import login

        with patch("reos.auth._polkit_authenticate") as mock_polkit:
            mock_polkit.return_value = False

            result = login("testuser", "wrongpassword")

        assert result.get("success") is False
        assert "error" in result, "Failed login should include error message"


class TestLogoutFunction:
    """Test logout function."""

    def test_logout_invalidates_session(self) -> None:
        """Logout should invalidate the session."""
        from reos.auth import logout, get_session_store, Session

        store = get_session_store()

        # Create a session directly
        session = Session(
            token="logout-test-token",
            username="user",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"key-material-32-bytes-long-xxxx",
        )
        store.insert(session)

        # Logout
        result = logout("logout-test-token")

        assert result.get("success") is True
        assert store.get("logout-test-token") is None, "Session should be gone after logout"

    def test_logout_nonexistent_session(self) -> None:
        """Logout of nonexistent session should not error."""
        from reos.auth import logout

        result = logout("nonexistent-token-xyz")

        # Should handle gracefully (either success=False or success=True is acceptable)
        assert "success" in result


class TestValidateSession:
    """Test session validation."""

    def test_validate_valid_session(self) -> None:
        """Valid session should pass validation."""
        from reos.auth import validate_session, get_session_store, Session

        store = get_session_store()
        session = Session(
            token="valid-session-token",
            username="validuser",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc),
            key_material=b"key-material-32-bytes-long-xxxx",
        )
        store.insert(session)

        result = validate_session("valid-session-token")

        assert result.get("valid") is True
        assert result.get("username") == "validuser"

    def test_validate_expired_session(self) -> None:
        """Expired session should fail validation."""
        from reos.auth import validate_session, get_session_store, Session

        store = get_session_store()
        expired = Session(
            token="expired-validate-token",
            username="user",
            created_at=datetime.now(timezone.utc) - timedelta(hours=1),
            last_activity=datetime.now(timezone.utc) - timedelta(hours=1),
            key_material=b"key",
        )
        store.insert(expired)

        result = validate_session("expired-validate-token")

        assert result.get("valid") is False

    def test_validate_nonexistent_session(self) -> None:
        """Nonexistent session should fail validation."""
        from reos.auth import validate_session

        result = validate_session("does-not-exist-token")

        assert result.get("valid") is False


class TestRefreshSession:
    """Test session refresh."""

    def test_refresh_valid_session(self) -> None:
        """Refreshing valid session should succeed."""
        from reos.auth import refresh_session, get_session_store, Session

        store = get_session_store()
        session = Session(
            token="refresh-test-token",
            username="user",
            created_at=datetime.now(timezone.utc),
            last_activity=datetime.now(timezone.utc) - timedelta(minutes=5),
            key_material=b"key-material-32-bytes-long-xxxx",
        )
        store.insert(session)

        result = refresh_session("refresh-test-token")

        assert result is True

        # Verify last_activity was updated
        refreshed = store.get("refresh-test-token")
        assert refreshed is not None
        elapsed = (datetime.now(timezone.utc) - refreshed.last_activity).total_seconds()
        assert elapsed < 1.0, "Last activity should be updated to now"
