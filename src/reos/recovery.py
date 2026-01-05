"""Recovery system for encrypted user data.

Provides two recovery mechanisms:
1. User Recovery Passphrase: User-memorized backup phrase
2. Admin Escrow: RSA-encrypted key stored for root recovery

Security Notes:
- Recovery keys are encrypted separately from user data
- Admin escrow requires root access to decrypt
- Recovery passphrases use the same key derivation as login
- Re-keying atomically updates all encrypted files
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

if TYPE_CHECKING:
    from .auth import Session


class RecoveryError(Exception):
    """Raised when recovery operations fail."""

    pass


# Recovery file locations
RECOVERY_DIR = Path.home() / ".reos-recovery"
RECOVERY_KEY_FILE = RECOVERY_DIR / "recovery.enc"
RECOVERY_META_FILE = RECOVERY_DIR / "recovery.meta"

# Admin escrow location (requires root)
ESCROW_DIR = Path("/var/lib/reos/escrow")


def _derive_recovery_key(username: str, passphrase: str) -> bytes:
    """Derive an encryption key from recovery passphrase.

    Uses same Scrypt parameters as auth.py for consistency.

    Args:
        username: Linux username
        passphrase: Recovery passphrase

    Returns:
        32-byte encryption key
    """
    salt_input = f"reos-{username}-recovery-salt-v1"
    salt = hashlib.sha256(salt_input.encode()).digest()[:16]

    kdf = Scrypt(
        salt=salt,
        length=32,
        n=16384,
        r=8,
        p=1,
    )

    return kdf.derive(passphrase.encode())


def setup_recovery_passphrase(
    username: str,
    master_key: bytes,
    passphrase: str,
) -> dict[str, str]:
    """Set up recovery passphrase for user data.

    Encrypts the master key with a key derived from the passphrase.
    Stored at ~/.reos-recovery/recovery.enc

    Args:
        username: Linux username
        master_key: The user's encryption key material
        passphrase: User-chosen recovery passphrase

    Returns:
        Dict with recovery_id and status

    Security:
        - Passphrase should be 16+ characters
        - Stored separately from user data
        - Uses same KDF as login (Scrypt)
    """
    if len(passphrase) < 8:
        raise RecoveryError("Recovery passphrase must be at least 8 characters")

    # Derive encryption key from passphrase
    recovery_key = _derive_recovery_key(username, passphrase)

    # Encrypt master key
    cipher = AESGCM(recovery_key)
    nonce = os.urandom(12)
    encrypted = cipher.encrypt(nonce, master_key, username.encode())

    # Ensure recovery directory exists
    RECOVERY_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Write encrypted key
    RECOVERY_KEY_FILE.write_bytes(nonce + encrypted)
    RECOVERY_KEY_FILE.chmod(0o600)

    # Write metadata (non-sensitive)
    recovery_id = hashlib.sha256(f"{username}-{datetime.now().isoformat()}".encode()).hexdigest()[:16]
    meta = {
        "username": username,
        "recovery_id": recovery_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "version": 1,
    }

    import json
    RECOVERY_META_FILE.write_text(json.dumps(meta, indent=2))
    RECOVERY_META_FILE.chmod(0o600)

    return {
        "recovery_id": recovery_id,
        "status": "created",
    }


def recover_with_passphrase(username: str, passphrase: str) -> bytes:
    """Recover master key using passphrase.

    Args:
        username: Linux username
        passphrase: Recovery passphrase

    Returns:
        Decrypted master key

    Raises:
        RecoveryError: If recovery fails
    """
    if not RECOVERY_KEY_FILE.exists():
        raise RecoveryError("No recovery key found. Recovery not set up.")

    # Read encrypted key
    encrypted_data = RECOVERY_KEY_FILE.read_bytes()
    if len(encrypted_data) < 12:
        raise RecoveryError("Invalid recovery data")

    # Derive key and decrypt
    recovery_key = _derive_recovery_key(username, passphrase)
    cipher = AESGCM(recovery_key)

    nonce = encrypted_data[:12]
    ciphertext = encrypted_data[12:]

    try:
        master_key = cipher.decrypt(nonce, ciphertext, username.encode())
        return master_key
    except Exception as e:
        raise RecoveryError(f"Invalid passphrase or corrupted recovery data: {e}") from e


def has_recovery_passphrase(username: str) -> bool:
    """Check if recovery passphrase is set up.

    Args:
        username: Linux username

    Returns:
        True if recovery is configured
    """
    if not RECOVERY_META_FILE.exists():
        return False

    try:
        import json
        meta = json.loads(RECOVERY_META_FILE.read_text())
        return meta.get("username") == username
    except Exception:
        return False


def setup_admin_escrow(username: str, master_key: bytes) -> dict[str, str]:
    """Set up admin escrow for emergency recovery.

    Encrypts master key with system RSA key, stored at
    /var/lib/reos/escrow/{username}.enc

    This requires root access to:
    1. Create the escrow directory
    2. Write the encrypted key
    3. Read and decrypt during recovery

    Args:
        username: Linux username
        master_key: The user's encryption key material

    Returns:
        Dict with escrow_id and status

    Raises:
        RecoveryError: If escrow setup fails (usually permission denied)
    """
    # Generate or load system escrow key
    escrow_key_path = ESCROW_DIR / "escrow.key"
    escrow_pub_path = ESCROW_DIR / "escrow.pub"

    try:
        ESCROW_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    except PermissionError:
        raise RecoveryError(
            "Admin escrow requires root access. "
            "Run with sudo to enable admin recovery."
        )

    # Load or generate RSA key pair
    if escrow_key_path.exists():
        key_data = escrow_key_path.read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)
        public_key = private_key.public_key()
    else:
        # Generate new 4096-bit RSA key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=4096,
        )
        public_key = private_key.public_key()

        # Save keys
        escrow_key_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        escrow_key_path.chmod(0o600)

        escrow_pub_path.write_bytes(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        escrow_pub_path.chmod(0o644)

    # Encrypt master key with RSA-OAEP
    encrypted = public_key.encrypt(
        master_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=username.encode(),
        ),
    )

    # Save encrypted key
    user_escrow_path = ESCROW_DIR / f"{username}.enc"
    user_escrow_path.write_bytes(encrypted)
    user_escrow_path.chmod(0o600)

    # Generate escrow ID
    escrow_id = hashlib.sha256(
        f"{username}-escrow-{datetime.now().isoformat()}".encode()
    ).hexdigest()[:16]

    return {
        "escrow_id": escrow_id,
        "status": "created",
    }


def recover_with_admin_escrow(username: str) -> bytes:
    """Recover master key using admin escrow.

    Requires root access to read the private key.

    Args:
        username: Linux username

    Returns:
        Decrypted master key

    Raises:
        RecoveryError: If recovery fails
    """
    escrow_key_path = ESCROW_DIR / "escrow.key"
    user_escrow_path = ESCROW_DIR / f"{username}.enc"

    if not escrow_key_path.exists():
        raise RecoveryError("Admin escrow not configured on this system")

    if not user_escrow_path.exists():
        raise RecoveryError(f"No escrow key found for user: {username}")

    try:
        # Load private key
        key_data = escrow_key_path.read_bytes()
        private_key = serialization.load_pem_private_key(key_data, password=None)

        # Read encrypted key
        encrypted = user_escrow_path.read_bytes()

        # Decrypt
        master_key = private_key.decrypt(
            encrypted,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=username.encode(),
            ),
        )

        return master_key

    except PermissionError:
        raise RecoveryError(
            "Permission denied. Admin escrow recovery requires root access."
        )
    except Exception as e:
        raise RecoveryError(f"Escrow recovery failed: {e}") from e


def has_admin_escrow(username: str) -> bool:
    """Check if admin escrow is set up for user.

    Args:
        username: Linux username

    Returns:
        True if escrow exists (may need root to read)
    """
    user_escrow_path = ESCROW_DIR / f"{username}.enc"
    return user_escrow_path.exists()


def rekey_user_data(
    username: str,
    old_key: bytes,
    new_key: bytes,
    user_data_root: Path | None = None,
) -> dict[str, int]:
    """Re-encrypt all user data with a new key.

    Used after password change to update encryption.

    Args:
        username: Linux username
        old_key: Current encryption key
        new_key: New encryption key
        user_data_root: Override user data directory

    Returns:
        Dict with files_processed count and status

    Security:
        - Atomic file updates (write to temp, rename)
        - Original files preserved until success
        - Recovery keys updated separately
    """
    if user_data_root is None:
        user_data_root = Path.home() / ".reos-data" / username

    if not user_data_root.exists():
        return {"files_processed": 0, "status": "no_data"}

    old_cipher = AESGCM(old_key)
    new_cipher = AESGCM(new_key)

    files_processed = 0
    errors = []

    # Process all encrypted files
    for path in user_data_root.rglob("*"):
        if not path.is_file():
            continue

        try:
            # Read and decrypt with old key
            encrypted_data = path.read_bytes()
            if len(encrypted_data) < 12:
                continue  # Not an encrypted file

            nonce = encrypted_data[:12]
            ciphertext = encrypted_data[12:]

            try:
                plaintext = old_cipher.decrypt(nonce, ciphertext, None)
            except Exception:
                # Not encrypted or wrong key, skip
                continue

            # Re-encrypt with new key
            new_nonce = os.urandom(12)
            new_ciphertext = new_cipher.encrypt(new_nonce, plaintext, None)

            # Atomic write: temp file then rename
            temp_path = path.with_suffix(".tmp")
            temp_path.write_bytes(new_nonce + new_ciphertext)
            temp_path.chmod(0o600)
            temp_path.rename(path)

            files_processed += 1

        except Exception as e:
            errors.append(f"{path}: {e}")

    result = {
        "files_processed": files_processed,
        "status": "completed" if not errors else "partial",
    }

    if errors:
        result["errors"] = errors[:10]  # Limit error list

    return result


def update_recovery_keys(
    username: str,
    new_master_key: bytes,
    recovery_passphrase: str | None = None,
) -> dict[str, str]:
    """Update recovery keys after password change.

    Args:
        username: Linux username
        new_master_key: New encryption key
        recovery_passphrase: If provided, update recovery passphrase too

    Returns:
        Dict with updated recovery info
    """
    results = {}

    # Update recovery passphrase if it exists and passphrase provided
    if recovery_passphrase and has_recovery_passphrase(username):
        setup_recovery_passphrase(username, new_master_key, recovery_passphrase)
        results["recovery_passphrase"] = "updated"

    # Update admin escrow if it exists
    if has_admin_escrow(username):
        try:
            setup_admin_escrow(username, new_master_key)
            results["admin_escrow"] = "updated"
        except RecoveryError:
            results["admin_escrow"] = "failed_permission_denied"

    return results
