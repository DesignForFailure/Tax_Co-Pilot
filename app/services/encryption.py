# SPDX-License-Identifier: AGPL-3.0-or-later
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Encryption provider abstraction for database encryption at rest.

Runtime encryption backend:
- SQLCipher (primary): Native SQLite encryption with AES-256

Legacy compatibility:
- Python-layer encryption state detection is retained to emit explicit
  errors instead of silently misreading encrypted JSON blobs.

Password management:
- Environment variable (TAX_COPILOT_DB_PASSWORD)
- OS keyring (GNOME Keyring, Windows Credential Locker, macOS Keychain)
- Web UI prompt (fallback)
"""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import closing
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.log import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


class HybridRow:
    """Row wrapper supporting both index-based and name-based access."""

    __slots__ = ("_values", "_columns", "_index_by_name")

    def __init__(self, cursor: Any, row: tuple[Any, ...]) -> None:
        self._values = tuple(row)
        self._columns = tuple(description[0] for description in cursor.description)
        self._index_by_name = {name: idx for idx, name in enumerate(self._columns)}

    def __getitem__(self, key: int | str) -> Any:
        if isinstance(key, int):
            return self._values[key]
        if isinstance(key, str):
            return self._values[self._index_by_name[key]]
        raise TypeError(f"Row indices must be integers or strings, not {type(key).__name__}")

    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)

    def __len__(self) -> int:
        return len(self._values)

    def keys(self) -> tuple[str, ...]:
        return self._columns

    def values(self) -> tuple[Any, ...]:
        return self._values


def hybrid_factory(cursor: Any, row: tuple[Any, ...]) -> HybridRow:
    """Convert a database row into a hybrid row with dict+sequence semantics."""
    return HybridRow(cursor, row)


def _hex_encode_key(password: str) -> str:
    """Encode password as hex for SQLCipher PRAGMA key.

    SQLCipher accepts hex-encoded keys via: PRAGMA key = "x'<hex>'"
    This avoids SQL injection from passwords containing quotes.

    KNOWN LIMITATION: SQLCipher interprets an x'...' literal of exactly
    64 hex chars as a RAW 32-byte key (96 chars as raw key + salt),
    skipping PBKDF2 entirely. A password whose UTF-8 encoding is exactly
    32 or 48 bytes therefore gets no key stretching. Changing this
    encoding now would lock existing users out of their databases, so it
    is documented in docs/ENCRYPTION.md instead; a keyed migration would
    be required to fix it. All lengths remain deterministic and
    self-consistent within this app.
    """
    return password.encode("utf-8").hex()


def rotate_key(old_password: str, new_password: str) -> None:
    """Re-encrypt the database with a new password using SQLCipher PRAGMA rekey.

    Requires SQLCipher. The database must already be encrypted.
    """
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except ImportError as e:
        raise ImportError("pysqlcipher3 is required for key rotation") from e

    from app.services.database import DB_PATH

    logger.info("Key rotation started (db=%s)", DB_PATH)
    conn = sqlcipher.connect(str(DB_PATH), timeout=10.0, isolation_level=None)
    try:
        old_hex = _hex_encode_key(old_password)
        conn.execute(f"PRAGMA key = \"x'{old_hex}'\"")
        # Verify old key works
        conn.execute("SELECT count(*) FROM sqlite_master")
        # Rotate to new key
        new_hex = _hex_encode_key(new_password)
        conn.execute(f"PRAGMA rekey = \"x'{new_hex}'\"")
        # Verify new key works
        conn.execute("SELECT count(*) FROM sqlite_master")
    except Exception:
        logger.error("Key rotation failed", exc_info=True)
        raise
    finally:
        conn.close()
    logger.info("Key rotation succeeded")


class DatabaseState(Enum):
    """Database encryption state."""

    NONE = "none"  # Database doesn't exist
    UNENCRYPTED = "unencrypted"  # Existing unencrypted database
    ENCRYPTED_SQLCIPHER = "encrypted_sqlcipher"  # SQLCipher encrypted
    ENCRYPTED_PYTHON = "encrypted_python"  # Python-layer encrypted


class PasswordValidationError(ValueError):
    """Raised when password doesn't meet security requirements."""

    pass


class EncryptionProvider(ABC):
    """Abstract base class for encryption providers."""

    @abstractmethod
    def create_connection(
        self, db_path: Path, password: str, timeout: float = 5.0
    ) -> sqlite3.Connection:
        """Create an encrypted database connection.

        Args:
            db_path: Path to the database file
            password: Encryption password
            timeout: Connection timeout in seconds

        Returns:
            sqlite3.Connection configured for encryption

        Raises:
            ValueError: If password is incorrect or database is corrupted
        """
        pass

    @abstractmethod
    def detect_state(self, db_path: Path) -> DatabaseState:
        """Detect the encryption state of a database.

        Args:
            db_path: Path to the database file

        Returns:
            DatabaseState enum value
        """
        pass


def detect_encryption_state(db_path: Path) -> DatabaseState:
    """Detect the encryption state of a database file.

    Strategy:
    1. If file doesn't exist → NONE
    2. Try opening as plain SQLite → UNENCRYPTED
    3. Check for _encryption_metadata table → ENCRYPTED_PYTHON
    4. Otherwise assume → ENCRYPTED_SQLCIPHER

    Args:
        db_path: Path to database file

    Returns:
        DatabaseState enum value
    """
    state = _detect_encryption_state(db_path)
    logger.debug("Encryption state detection: %s (path=%s)", state.value, db_path)
    return state


def _detect_encryption_state(db_path: Path) -> DatabaseState:
    """Probe the database file; see detect_encryption_state for the strategy."""
    if not db_path.exists():
        return DatabaseState.NONE

    # Try opening as unencrypted SQLite. The failure branch is the EXPECTED
    # path for encrypted databases, so the connection must be closed there
    # too or every state probe leaks a file handle.
    try:
        with closing(sqlite3.connect(str(db_path), timeout=1.0)) as conn:
            # Try to read from sqlite_master (will fail if encrypted)
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
            _ = cursor.fetchall()  # Check if we can read (will fail if encrypted)

            # Check for Python encryption metadata table
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='_encryption_metadata'"
            )
            has_metadata = cursor.fetchone() is not None

        if has_metadata:
            return DatabaseState.ENCRYPTED_PYTHON
        else:
            return DatabaseState.UNENCRYPTED

    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        # Distinguish corrupted plaintext from encrypted:
        # SQLite files start with "SQLite format 3\x00"; encrypted files don't.
        try:
            with open(db_path, "rb") as f:
                header = f.read(16)
            if header.startswith(b"SQLite format 3\x00"):
                raise RuntimeError(
                    f"Database at {db_path} appears corrupted "
                    "(has SQLite header but cannot be read). "
                    "Restore from a backup or delete the file to start fresh."
                )
        except OSError:
            pass
        return DatabaseState.ENCRYPTED_SQLCIPHER


def validate_password(password: str) -> None:
    """Validate password meets minimum security requirements.

    Requirements:
    - Minimum 12 characters
    - Not empty or whitespace-only

    Args:
        password: Password to validate

    Raises:
        PasswordValidationError: If password doesn't meet requirements
    """
    if not password or not password.strip():
        logger.warning("Password validation failed: empty password")
        raise PasswordValidationError("Password cannot be empty")

    if len(password) < 12:
        logger.warning("Password validation failed: below minimum length")
        raise PasswordValidationError("Password must be at least 12 characters long")

    logger.debug("Password validation succeeded")

    # Optional: Add entropy checking here using zxcvbn or similar
    # For now, just enforce minimum length


def get_password_from_env() -> str | None:
    """Get password from environment variable.

    Returns:
        Password if found, None otherwise
    """
    return os.getenv("TAX_COPILOT_DB_PASSWORD")


def get_password_from_keyring(service_name: str = "tax_copilot", username: str = "db") -> str | None:
    """Get password from OS keyring.

    Args:
        service_name: Keyring service name
        username: Keyring username

    Returns:
        Password if found, None otherwise
    """
    try:
        import keyring

        password = keyring.get_password(service_name, username)
        # keyring.get_password returns str | None
        return str(password) if password is not None else None
    except Exception:
        # keyring library not available or error accessing keyring
        logger.warning("Keyring read failed", exc_info=True)
        return None


def set_password_in_keyring(
    password: str, service_name: str = "tax_copilot", username: str = "db"
) -> bool:
    """Store password in OS keyring.

    Args:
        password: Password to store
        service_name: Keyring service name
        username: Keyring username

    Returns:
        True if successful, False otherwise
    """
    try:
        import keyring

        keyring.set_password(service_name, username, password)
        return True
    except Exception:
        logger.warning("Keyring write failed", exc_info=True)
        return False


def get_password(source: str = "auto") -> str | None:
    """Get database password from configured source.

    Args:
        source: Password source ("env" | "keyring" | "prompt" | "auto")
               "auto" tries env → keyring → None (caller handles prompt)

    Returns:
        Password if found, None if prompt needed
    """
    if source == "env":
        return get_password_from_env()
    elif source == "keyring":
        return get_password_from_keyring()
    elif source == "auto":
        # Try environment first
        password = get_password_from_env()
        if password:
            return password
        # Then try keyring
        password = get_password_from_keyring()
        if password:
            return password
        # Return None - caller should prompt
        return None
    else:
        # source == "prompt" or unknown
        return None


def compute_checksum(data: bytes) -> str:
    """Compute SHA-256 checksum of data.

    Args:
        data: Data to checksum

    Returns:
        Hex-encoded SHA-256 hash
    """
    return hashlib.sha256(data).hexdigest()


class SQLCipherProvider(EncryptionProvider):
    """SQLCipher encryption provider using native SQLite encryption.

    Uses AES-256 encryption at the SQLite page level via SQLCipher.
    Requires pysqlcipher3 library.
    """

    def __init__(self, kdf_iterations: int = 100_000) -> None:
        """Initialize SQLCipher provider.

        Args:
            kdf_iterations: PBKDF2 iterations for key derivation (minimum 100k)
        """
        self.kdf_iterations = max(kdf_iterations, 100_000)

    def create_connection(
        self, db_path: Path, password: str, timeout: float = 5.0
    ) -> sqlite3.Connection:
        """Create an encrypted database connection using SQLCipher.

        Args:
            db_path: Path to the database file
            password: Encryption password
            timeout: Connection timeout in seconds

        Returns:
            sqlite3.Connection configured for SQLCipher encryption

        Raises:
            ValueError: If password is incorrect or database is corrupted
            ImportError: If pysqlcipher3 is not available
        """
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher
        except ImportError as e:
            raise ImportError(
                "pysqlcipher3 is required for SQLCipher encryption. "
                "Install with: pip install pysqlcipher3"
            ) from e

        # Create parent directory if needed
        db_path.parent.mkdir(parents=True, exist_ok=True)

        conn = None
        try:
            # Connect to database
            conn = sqlcipher.connect(str(db_path), timeout=timeout, isolation_level=None)

            # Set encryption key (hex-encoded to prevent SQL injection from quotes)
            hex_key = _hex_encode_key(password)
            conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")

            # Configure key derivation (PBKDF2)
            conn.execute(f"PRAGMA kdf_iter = {self.kdf_iterations}")

            # Pin cipher parameters for cross-version compatibility.
            # NOTE: cipher_compatibility = 4 resets all cipher settings to the
            # SQLCipher v4 defaults, INCLUDING kdf_iter (256,000). Every
            # existing database was created under these defaults, so the
            # kdf_iter PRAGMA above is effectively inert; reordering it after
            # this line would change the KDF and lock users out of their
            # databases. See docs/ENCRYPTION.md.
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute("PRAGMA cipher_compatibility = 4")

            # Configure SQLite pragmas (matching unencrypted behavior)
            conn.row_factory = hybrid_factory
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")

            # Verify encryption works by trying to read
            conn.execute("SELECT count(*) FROM sqlite_master")

            # pysqlcipher3 connection is compatible with sqlite3.Connection interface
            return conn  # type: ignore

        except Exception as e:
            logger.warning("Failed to open encrypted database (path=%s): %s", db_path, e)
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    logger.debug("Closing failed encrypted connection raised", exc_info=True)
            raise ValueError(
                f"Failed to open encrypted database. "
                f"Password may be incorrect or database corrupted: {e}"
            ) from e

    def detect_state(self, db_path: Path) -> DatabaseState:
        """Detect if database is encrypted with SQLCipher.

        Args:
            db_path: Path to database file

        Returns:
            DatabaseState enum value
        """
        # Use the global detect_encryption_state function
        return detect_encryption_state(db_path)


class PythonEncryptionProvider(EncryptionProvider):
    """Python-layer encryption provider (legacy, runtime-disabled).

    Historical note:
    - This mode stored encrypted JSON blobs in plain SQLite tables.
    - Runtime read/write support is intentionally disabled because transparent
      decode/encode hooks were never implemented end-to-end.
    """

    def __init__(self, kdf_iterations: int = 100_000) -> None:
        """Initialize Python encryption provider.

        Args:
            kdf_iterations: PBKDF2 iterations for key derivation (minimum 100k)
        """
        self.kdf_iterations = max(kdf_iterations, 100_000)

    def _derive_key(self, password: str, salt: bytes) -> bytes:
        """Derive encryption key from password using PBKDF2.

        Args:
            password: User password
            salt: Random salt (16 bytes)

        Returns:
            32-byte encryption key
        """
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=self.kdf_iterations,
        )
        # kdf.derive returns bytes
        derived_key: bytes = kdf.derive(password.encode("utf-8"))
        return derived_key

    def create_connection(
        self, db_path: Path, password: str, timeout: float = 5.0
    ) -> sqlite3.Connection:
        """Create a connection with Python-layer encryption.

        Runtime access is disabled because decode/encode hooks are not available
        in the persistence layer.
        """
        raise ValueError(
            "Python-layer encryption runtime support is disabled. "
            "Use SQLCipher encryption."
        )

    def detect_state(self, db_path: Path) -> DatabaseState:
        """Detect if database uses Python-layer encryption.

        Args:
            db_path: Path to database file

        Returns:
            DatabaseState enum value
        """
        return detect_encryption_state(db_path)


def get_encryption_provider(provider_type: str = "auto", kdf_iterations: int = 100_000) -> EncryptionProvider:
    """Get an encryption provider instance.

    Args:
        provider_type: "sqlcipher", "python", or "auto"
        kdf_iterations: PBKDF2 iterations for key derivation

    Returns:
        EncryptionProvider instance

    Raises:
        ImportError: If requested provider is unavailable
    """
    if provider_type == "sqlcipher":
        return SQLCipherProvider(kdf_iterations)
    elif provider_type == "python":
        raise ValueError(
            "Python-layer encryption is disabled. Use provider_type='sqlcipher'."
        )
    elif provider_type == "auto":
        # Runtime encryption requires SQLCipher.
        try:
            from pysqlcipher3 import dbapi2 as sqlcipher  # noqa: F401

            return SQLCipherProvider(kdf_iterations)
        except ImportError:
            raise ImportError(
                "SQLCipher runtime support is required but pysqlcipher3 is not installed."
            ) from None
    else:
        raise ValueError(f"Unknown provider type: {provider_type}")


def migrate_to_encrypted(
    db_path: Path,
    password: str,
    provider_type: str = "auto",
    kdf_iterations: int = 100_000,
    backup_suffix: str = ".unencrypted.backup",
) -> None:
    """Migrate an unencrypted database to encrypted format.

    Creates encrypted copy, verifies integrity, then atomically swaps files.
    Original database is backed up with specified suffix.

    Args:
        db_path: Path to unencrypted database
        password: Encryption password for new database
        provider_type: Encryption provider to use ("sqlcipher" | "auto")
        kdf_iterations: PBKDF2 iterations
        backup_suffix: Suffix for backup file

    Raises:
        ValueError: If database doesn't exist or is already encrypted
        RuntimeError: If migration fails or integrity check fails
    """
    # Validate input
    if not db_path.exists():
        raise ValueError(f"Database file not found: {db_path}")

    db_state = detect_encryption_state(db_path)
    if db_state != DatabaseState.UNENCRYPTED:
        raise ValueError(f"Database is not unencrypted (state: {db_state})")

    validate_password(password)

    if provider_type == "python":
        raise ValueError(
            "Python-layer encryption migration is disabled. Use provider_type='sqlcipher'."
        )

    # Get provider
    provider = get_encryption_provider(provider_type, kdf_iterations)

    # Determine migration strategy based on provider
    if isinstance(provider, SQLCipherProvider):
        logger.info("Encryption migration started (path=%s)", db_path)
        _migrate_to_sqlcipher(db_path, password, kdf_iterations, backup_suffix)
        logger.info("Encryption migration succeeded (path=%s)", db_path)
    else:
        raise RuntimeError(f"Unsupported provider type: {type(provider)}")


_SAFE_TABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_table_name(name: str) -> str:
    """Reject table names that could enable SQL injection."""
    if not _SAFE_TABLE_NAME_RE.fullmatch(name):
        raise RuntimeError(f"Unsafe table name rejected: {name!r}")
    return name


def _migrate_to_sqlcipher(
    db_path: Path, password: str, kdf_iterations: int, backup_suffix: str
) -> None:
    """Migrate to SQLCipher encryption using ATTACH DATABASE method.

    Args:
        db_path: Path to unencrypted database
        password: Encryption password
        kdf_iterations: PBKDF2 iterations
        backup_suffix: Suffix for backup file
    """
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except ImportError as e:
        raise ImportError("pysqlcipher3 required for SQLCipher migration") from e

    encrypted_path = db_path.with_suffix(".db.encrypted.tmp")
    backup_path = Path(f"{db_path}{backup_suffix}")

    try:
        # Open source database (unencrypted)
        source_conn = sqlite3.connect(str(db_path), timeout=10.0)

        # Get row counts for verification
        tables_query = "SELECT name FROM sqlite_master WHERE type='table'"
        tables = [
            _validate_table_name(row[0])
            for row in source_conn.execute(tables_query).fetchall()
        ]
        source_counts = {}
        for table in tables:
            count = source_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            source_counts[table] = count

        source_conn.close()

        # Perform migration using SQLCipher's ATTACH DATABASE + export
        conn = sqlcipher.connect(str(db_path), timeout=10.0)
        hex_key = _hex_encode_key(password)
        conn.execute(f"ATTACH DATABASE '{encrypted_path}' AS encrypted KEY \"x'{hex_key}'\"")
        conn.execute(f"PRAGMA encrypted.kdf_iter = {kdf_iterations}")
        conn.execute("PRAGMA encrypted.cipher_page_size = 4096")
        conn.execute("PRAGMA encrypted.cipher_compatibility = 4")

        # Export all data
        conn.execute("SELECT sqlcipher_export('encrypted')")
        conn.execute("DETACH DATABASE encrypted")
        conn.close()

        # Verify encrypted database
        provider = SQLCipherProvider(kdf_iterations)
        verify_conn = provider.create_connection(encrypted_path, password, timeout=10.0)

        # Check row counts match
        for table, expected_count in source_counts.items():
            actual_count = verify_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if actual_count != expected_count:
                verify_conn.close()
                encrypted_path.unlink()
                raise RuntimeError(
                    f"Integrity check failed: {table} has {actual_count} rows, expected {expected_count}"
                )

        verify_conn.close()

        # Atomic swap: backup original → move encrypted to production
        if backup_path.exists():
            backup_path.unlink()
        db_path.rename(backup_path)
        encrypted_path.rename(db_path)

        # The app runs SQLite in WAL mode; sidecars belonging to the old
        # PLAINTEXT database must not survive next to the encrypted file
        # (they contain plaintext pages and confuse SQLCipher on open).
        for suffix in ("-wal", "-shm"):
            sidecar = Path(str(db_path) + suffix)
            sidecar.unlink(missing_ok=True)

    except Exception as e:
        # Cleanup on failure
        logger.error("Encryption migration failed", exc_info=True)
        if encrypted_path.exists():
            encrypted_path.unlink()
        raise RuntimeError(f"SQLCipher migration failed: {e}") from e


