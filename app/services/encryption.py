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
import secrets
import sqlite3
from abc import ABC, abstractmethod
from collections.abc import Iterator
from datetime import UTC
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


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

    conn = sqlcipher.connect(str(DB_PATH), timeout=10.0, isolation_level=None)
    old_hex = _hex_encode_key(old_password)
    conn.execute(f"PRAGMA key = \"x'{old_hex}'\"")
    # Verify old key works
    conn.execute("SELECT count(*) FROM sqlite_master")
    # Rotate to new key
    new_hex = _hex_encode_key(new_password)
    conn.execute(f"PRAGMA rekey = \"x'{new_hex}'\"")
    # Verify new key works
    conn.execute("SELECT count(*) FROM sqlite_master")
    conn.close()


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
    if not db_path.exists():
        return DatabaseState.NONE

    # Try opening as unencrypted SQLite
    try:
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        # Try to read from sqlite_master (will fail if encrypted)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' LIMIT 1")
        _ = cursor.fetchall()  # Check if we can read (will fail if encrypted)
        conn.close()

        # Check for Python encryption metadata table
        conn = sqlite3.connect(str(db_path), timeout=1.0)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='_encryption_metadata'"
        )
        has_metadata = cursor.fetchone() is not None
        conn.close()

        if has_metadata:
            return DatabaseState.ENCRYPTED_PYTHON
        else:
            return DatabaseState.UNENCRYPTED

    except (sqlite3.DatabaseError, sqlite3.OperationalError):
        # Can't read sqlite_master → likely encrypted with SQLCipher
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
        raise PasswordValidationError("Password cannot be empty")

    if len(password) < 12:
        raise PasswordValidationError("Password must be at least 12 characters long")

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

        try:
            # Connect to database
            conn = sqlcipher.connect(str(db_path), timeout=timeout, isolation_level=None)

            # Set encryption key (hex-encoded to prevent SQL injection from quotes)
            hex_key = _hex_encode_key(password)
            conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")

            # Configure key derivation (PBKDF2)
            conn.execute(f"PRAGMA kdf_iter = {self.kdf_iterations}")

            # Pin cipher parameters for cross-version compatibility.
            # Order matters: key → kdf_iter → cipher params → first read.
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
        _migrate_to_sqlcipher(db_path, password, kdf_iterations, backup_suffix)
    else:
        raise RuntimeError(f"Unsupported provider type: {type(provider)}")


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
        tables = [row[0] for row in source_conn.execute(tables_query).fetchall()]
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

    except Exception as e:
        # Cleanup on failure
        if encrypted_path.exists():
            encrypted_path.unlink()
        raise RuntimeError(f"SQLCipher migration failed: {e}") from e


def _migrate_to_python_encryption(
    db_path: Path, password: str, kdf_iterations: int, backup_suffix: str
) -> None:
    """Migrate to Python-layer encryption.

    Creates new database with encryption metadata, copies all data with
    field-level encryption for JSON columns.

    Args:
        db_path: Path to unencrypted database
        password: Encryption password
        kdf_iterations: PBKDF2 iterations
        backup_suffix: Suffix for backup file
    """
    import base64
    from datetime import datetime

    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    encrypted_path = db_path.with_suffix(".db.encrypted.tmp")
    backup_path = db_path.with_suffix(backup_suffix)

    try:
        # Generate salt for key derivation
        salt = secrets.token_bytes(16)

        # Derive encryption key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=kdf_iterations
        )
        key = kdf.derive(password.encode("utf-8"))
        fernet = Fernet(base64.urlsafe_b64encode(key))

        # Open source database
        source_conn = sqlite3.connect(str(db_path), timeout=10.0)
        source_conn.row_factory = sqlite3.Row

        # Create encrypted database
        dest_conn = sqlite3.connect(str(encrypted_path), timeout=10.0, isolation_level=None)

        # Create encryption metadata table
        dest_conn.execute(
            """CREATE TABLE _encryption_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                encryption_provider TEXT NOT NULL,
                salt BLOB NOT NULL,
                iterations INTEGER NOT NULL,
                encrypted_at TEXT NOT NULL,
                key_version INTEGER NOT NULL DEFAULT 1
            )"""
        )
        dest_conn.execute(
            """INSERT INTO _encryption_metadata (id, encryption_provider, salt, iterations, encrypted_at, key_version)
               VALUES (1, 'python', ?, ?, ?, 1)""",
            (salt, kdf_iterations, datetime.now(UTC).isoformat()),
        )

        # Copy schema (all tables except _encryption_metadata)
        for row in source_conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name != '_encryption_metadata'"
        ):
            if row[0]:
                dest_conn.execute(row[0])

        # Copy data with encryption for JSON columns
        tables = [
            row[0]
            for row in source_conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]

        for table in tables:
            # Get column names
            columns_info = source_conn.execute(f"PRAGMA table_info({table})").fetchall()
            columns = [col[1] for col in columns_info]

            # Identify JSON columns (assume columns ending in _json)
            json_columns = {col for col in columns if col.endswith("_json")}

            # Copy rows
            source_rows = source_conn.execute(f"SELECT * FROM {table}").fetchall()
            for row in source_rows:
                row_dict = dict(row)
                # Encrypt JSON columns
                for col in json_columns:
                    if row_dict[col] is not None:
                        plaintext = row_dict[col].encode("utf-8")
                        encrypted = fernet.encrypt(plaintext)
                        row_dict[col] = encrypted.decode("utf-8")

                # Insert into dest
                placeholders = ", ".join(["?"] * len(columns))
                col_names = ", ".join(columns)
                values = [row_dict[col] for col in columns]
                dest_conn.execute(
                    f"INSERT INTO {table} ({col_names}) VALUES ({placeholders})", values
                )

        source_conn.close()
        dest_conn.close()

        # Verify encrypted database can be opened
        provider = PythonEncryptionProvider(kdf_iterations)
        verify_conn = provider.create_connection(encrypted_path, password, timeout=10.0)
        verify_conn.close()

        # Atomic swap
        if backup_path.exists():
            backup_path.unlink()
        db_path.rename(backup_path)
        encrypted_path.rename(db_path)

    except Exception as e:
        # Cleanup on failure
        if encrypted_path.exists():
            encrypted_path.unlink()
        raise RuntimeError(f"Python encryption migration failed: {e}") from e
