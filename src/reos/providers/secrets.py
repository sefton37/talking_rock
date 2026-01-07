"""Secrets Manager - Secure API key storage via system keyring.

Uses the system keyring (GNOME Keyring, KDE Wallet, etc.) to securely
store API keys for cloud LLM providers.

On Linux, this uses the SecretService D-Bus API via the `secretstorage`
backend. Keys are encrypted by the desktop environment's keyring.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Service name for ReOS credentials in the keyring
SERVICE_NAME = "com.reos.providers"


def store_api_key(provider: str, api_key: str) -> None:
    """Store an API key in the system keyring.

    Args:
        provider: Provider identifier (e.g., "anthropic", "openai").
        api_key: The API key to store.

    Raises:
        RuntimeError: If keyring is not available.
    """
    try:
        import keyring

        keyring.set_password(SERVICE_NAME, provider, api_key)
        logger.info("Stored API key for provider: %s", provider)
    except ImportError as e:
        raise RuntimeError(
            "keyring library not installed. Run: pip install keyring secretstorage"
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to store API key: {e}") from e


def get_api_key(provider: str) -> str | None:
    """Retrieve an API key from the system keyring.

    Args:
        provider: Provider identifier (e.g., "anthropic", "openai").

    Returns:
        The API key if found, None otherwise.
    """
    try:
        import keyring

        return keyring.get_password(SERVICE_NAME, provider)
    except ImportError:
        logger.warning("keyring library not installed")
        return None
    except Exception as e:
        logger.warning("Failed to retrieve API key for %s: %s", provider, e)
        return None


def delete_api_key(provider: str) -> bool:
    """Remove an API key from the system keyring.

    Args:
        provider: Provider identifier.

    Returns:
        True if deleted, False otherwise.
    """
    try:
        import keyring

        keyring.delete_password(SERVICE_NAME, provider)
        logger.info("Deleted API key for provider: %s", provider)
        return True
    except ImportError:
        logger.warning("keyring library not installed")
        return False
    except Exception as e:
        # keyring raises PasswordDeleteError if not found
        logger.debug("Failed to delete API key for %s: %s", provider, e)
        return False


def has_api_key(provider: str) -> bool:
    """Check if an API key exists for a provider.

    Args:
        provider: Provider identifier.

    Returns:
        True if an API key is stored, False otherwise.
    """
    return get_api_key(provider) is not None


def check_keyring_available() -> bool:
    """Check if system keyring is available and functional.

    Returns:
        True if keyring can store secrets securely, False otherwise.
    """
    try:
        import keyring

        # Check what backend is being used
        backend = keyring.get_keyring()
        backend_name = backend.__class__.__name__

        # Plaintext keyring is insecure - treat as unavailable
        if "Plaintext" in backend_name or "Null" in backend_name:
            logger.warning("Keyring using insecure backend: %s", backend_name)
            return False

        # Try a test write/read/delete
        test_key = "__reos_keyring_test__"
        test_value = "test_value"
        try:
            keyring.set_password(SERVICE_NAME, test_key, test_value)
            retrieved = keyring.get_password(SERVICE_NAME, test_key)
            keyring.delete_password(SERVICE_NAME, test_key)
            return retrieved == test_value
        except Exception as e:
            logger.debug("Keyring test failed: %s", e)
            return False

    except ImportError:
        return False
    except Exception as e:
        logger.debug("Keyring availability check failed: %s", e)
        return False


def get_keyring_backend_name() -> str:
    """Get the name of the current keyring backend.

    Returns:
        Backend name (e.g., "SecretService Keyring", "PlaintextKeyring").
    """
    try:
        import keyring

        backend = keyring.get_keyring()
        return backend.__class__.__name__
    except Exception as e:
        logger.debug("Failed to get keyring backend name: %s", e)
        return "Unknown"


def list_stored_providers() -> list[str]:
    """List providers that have stored API keys.

    Note: This is a best-effort function. Some keyring backends
    don't support enumeration.

    Returns:
        List of provider names with stored keys.
    """
    known_providers = ["anthropic", "openai", "google", "cohere"]
    stored = []

    for provider in known_providers:
        if has_api_key(provider):
            stored.append(provider)

    return stored
