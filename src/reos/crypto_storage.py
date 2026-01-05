"""Transparent encryption layer for per-user data storage.

Provides AES-256-GCM authenticated encryption for user data files.
All data is stored encrypted at rest and decrypted transparently on read.

Security Notes:
- Uses AES-256-GCM (authenticated encryption with associated data)
- 12-byte random nonce per encryption (never reused)
- Key material stored only in memory (from session)
- Files stored as: nonce (12 bytes) || ciphertext || auth tag (16 bytes)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

if TYPE_CHECKING:
    from .auth import Session


class CryptoStorageError(Exception):
    """Raised when encryption/decryption fails."""

    pass


class CryptoStorage:
    """Transparent encryption layer for user data.

    Encrypts all file operations with the user's session key.
    Data is stored at ~/.reos-data/{username}/.
    """

    # Nonce size for AES-GCM (96 bits = 12 bytes)
    NONCE_SIZE = 12

    def __init__(self, session: Session):
        """Initialize with an authenticated session.

        Args:
            session: Authenticated session with key material
        """
        self._session = session
        self._cipher = AESGCM(session.key_material)
        self._user_root = session.get_user_data_root()

        # Ensure user data directory exists with proper permissions
        self._user_root.mkdir(parents=True, exist_ok=True)
        # Set restrictive permissions (owner only)
        self._user_root.chmod(0o700)

    @property
    def user_data_root(self) -> Path:
        """Get the root directory for user data."""
        return self._user_root

    @property
    def username(self) -> str:
        """Get the username for this storage instance."""
        return self._session.username

    def _resolve_path(self, rel_path: str) -> Path:
        """Resolve a relative path to absolute within user data root.

        Args:
            rel_path: Relative path within user data directory

        Returns:
            Absolute path to the file

        Raises:
            CryptoStorageError: If path escapes user data root
        """
        # Normalize and resolve the path
        target = (self._user_root / rel_path).resolve()

        # Security: Ensure path stays within user root
        try:
            target.relative_to(self._user_root)
        except ValueError:
            raise CryptoStorageError(
                f"Path escape attempt: {rel_path} resolves outside user data"
            )

        return target

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt data with session key.

        Args:
            plaintext: Data to encrypt

        Returns:
            Encrypted data: nonce || ciphertext (includes auth tag)
        """
        nonce = os.urandom(self.NONCE_SIZE)
        ciphertext = self._cipher.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, encrypted: bytes) -> bytes:
        """Decrypt data with session key.

        Args:
            encrypted: Encrypted data (nonce || ciphertext)

        Returns:
            Decrypted plaintext

        Raises:
            CryptoStorageError: If decryption fails (wrong key or corrupted)
        """
        if len(encrypted) < self.NONCE_SIZE:
            raise CryptoStorageError("Encrypted data too short")

        nonce = encrypted[: self.NONCE_SIZE]
        ciphertext = encrypted[self.NONCE_SIZE :]

        try:
            return self._cipher.decrypt(nonce, ciphertext, None)
        except Exception as e:
            raise CryptoStorageError(f"Decryption failed: {e}") from e

    def read(self, rel_path: str) -> bytes:
        """Read and decrypt a file.

        Args:
            rel_path: Relative path within user data directory

        Returns:
            Decrypted file contents

        Raises:
            FileNotFoundError: If file doesn't exist
            CryptoStorageError: If decryption fails
        """
        target = self._resolve_path(rel_path)

        if not target.exists():
            raise FileNotFoundError(f"File not found: {rel_path}")

        encrypted = target.read_bytes()
        return self.decrypt(encrypted)

    def read_text(self, rel_path: str, encoding: str = "utf-8") -> str:
        """Read and decrypt a text file.

        Args:
            rel_path: Relative path within user data directory
            encoding: Text encoding (default: utf-8)

        Returns:
            Decrypted file contents as string

        Raises:
            FileNotFoundError: If file doesn't exist
            CryptoStorageError: If decryption fails
        """
        return self.read(rel_path).decode(encoding)

    def write(self, rel_path: str, data: bytes) -> None:
        """Encrypt and write data to a file.

        Args:
            rel_path: Relative path within user data directory
            data: Data to encrypt and write
        """
        target = self._resolve_path(rel_path)

        # Ensure parent directories exist
        target.parent.mkdir(parents=True, exist_ok=True)

        encrypted = self.encrypt(data)
        target.write_bytes(encrypted)

        # Set restrictive permissions
        target.chmod(0o600)

    def write_text(self, rel_path: str, text: str, encoding: str = "utf-8") -> None:
        """Encrypt and write text to a file.

        Args:
            rel_path: Relative path within user data directory
            text: Text to encrypt and write
            encoding: Text encoding (default: utf-8)
        """
        self.write(rel_path, text.encode(encoding))

    def exists(self, rel_path: str) -> bool:
        """Check if an encrypted file exists.

        Args:
            rel_path: Relative path within user data directory

        Returns:
            True if file exists
        """
        target = self._resolve_path(rel_path)
        return target.exists()

    def delete(self, rel_path: str) -> bool:
        """Delete an encrypted file.

        Args:
            rel_path: Relative path within user data directory

        Returns:
            True if file was deleted, False if it didn't exist
        """
        target = self._resolve_path(rel_path)

        if not target.exists():
            return False

        # Overwrite with random data before deletion (defense in depth)
        file_size = target.stat().st_size
        if file_size > 0:
            target.write_bytes(os.urandom(file_size))

        target.unlink()
        return True

    def list_files(self, rel_dir: str = "") -> list[str]:
        """List files in an encrypted directory.

        Args:
            rel_dir: Relative directory path (empty = root)

        Returns:
            List of relative file paths
        """
        target = self._resolve_path(rel_dir) if rel_dir else self._user_root

        if not target.is_dir():
            return []

        files = []
        for path in target.rglob("*"):
            if path.is_file():
                rel = path.relative_to(self._user_root)
                files.append(str(rel))

        return sorted(files)

    def ensure_dir(self, rel_dir: str) -> Path:
        """Ensure a directory exists within user data.

        Args:
            rel_dir: Relative directory path

        Returns:
            Absolute path to the directory
        """
        target = self._resolve_path(rel_dir)
        target.mkdir(parents=True, exist_ok=True)
        target.chmod(0o700)
        return target
