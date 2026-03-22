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

"""Unit tests for encryption infrastructure."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from app.services.encryption import (
    DatabaseState,
    PasswordValidationError,
    compute_checksum,
    detect_encryption_state,
    get_password,
    get_password_from_env,
    validate_password,
)


def test_detect_encryption_state_none() -> None:
    """Test detection when database doesn't exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "nonexistent.db"
        assert detect_encryption_state(db_path) == DatabaseState.NONE


def test_detect_encryption_state_unencrypted() -> None:
    """Test detection of unencrypted database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "unencrypted.db"

        # Create unencrypted database
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, data TEXT)")
        conn.execute("INSERT INTO test (data) VALUES ('hello')")
        conn.commit()
        conn.close()

        assert detect_encryption_state(db_path) == DatabaseState.UNENCRYPTED


def test_detect_encryption_state_python_encrypted() -> None:
    """Test detection of Python-layer encrypted database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "python_encrypted.db"

        # Create database with encryption metadata table
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            """CREATE TABLE _encryption_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                encryption_provider TEXT NOT NULL,
                salt BLOB NOT NULL,
                iterations INTEGER NOT NULL,
                encrypted_at TEXT NOT NULL,
                key_version INTEGER NOT NULL DEFAULT 1
            )"""
        )
        conn.execute(
            """INSERT INTO _encryption_metadata
               (id, encryption_provider, salt, iterations, encrypted_at, key_version)
               VALUES (1, 'python', x'0123456789abcdef', 100000, '2024-01-01', 1)"""
        )
        conn.commit()
        conn.close()

        assert detect_encryption_state(db_path) == DatabaseState.ENCRYPTED_PYTHON


def test_validate_password_valid() -> None:
    """Test password validation with valid passwords."""
    # Should not raise
    validate_password("MySecurePassword123")
    validate_password("a" * 12)  # Minimum length
    validate_password("Very Long Password With Spaces!")


def test_validate_password_too_short() -> None:
    """Test password validation rejects short passwords."""
    with pytest.raises(PasswordValidationError, match="at least 12 characters"):
        validate_password("short")

    with pytest.raises(PasswordValidationError, match="at least 12 characters"):
        validate_password("12345678901")  # 11 chars


def test_validate_password_empty() -> None:
    """Test password validation rejects empty passwords."""
    with pytest.raises(PasswordValidationError, match="cannot be empty"):
        validate_password("")

    with pytest.raises(PasswordValidationError, match="cannot be empty"):
        validate_password("   ")  # Whitespace only


def test_get_password_from_env() -> None:
    """Test getting password from environment variable."""
    # Should return None when not set
    os.environ.pop("TAX_COPILOT_DB_PASSWORD", None)
    assert get_password_from_env() is None

    # Should return password when set
    os.environ["TAX_COPILOT_DB_PASSWORD"] = "test_password_123"
    assert get_password_from_env() == "test_password_123"

    # Cleanup
    os.environ.pop("TAX_COPILOT_DB_PASSWORD", None)


def test_get_password_auto() -> None:
    """Test automatic password source selection."""
    # Clear environment
    os.environ.pop("TAX_COPILOT_DB_PASSWORD", None)

    # Should return None when no sources available
    password = get_password(source="auto")
    # Could be None or from keyring depending on system
    assert password is None or isinstance(password, str)


def test_get_password_env_source() -> None:
    """Test explicit env password source."""
    os.environ["TAX_COPILOT_DB_PASSWORD"] = "env_password"
    assert get_password(source="env") == "env_password"
    os.environ.pop("TAX_COPILOT_DB_PASSWORD")


def test_hex_key_encoding() -> None:
    """Password with special chars encodes cleanly for PRAGMA key."""
    from app.services.encryption import _hex_encode_key

    assert _hex_encode_key("simple") == "73696d706c65"
    assert _hex_encode_key("it's a secret") == "69742773206120736563726574"
    result = _hex_encode_key("pass'word\"test")
    assert "'" not in result
    assert '"' not in result


def test_compute_checksum() -> None:
    """Test SHA-256 checksum computation."""
    data = b"Hello, World!"
    checksum = compute_checksum(data)

    # Should be 64 character hex string (SHA-256)
    assert len(checksum) == 64
    assert all(c in "0123456789abcdef" for c in checksum)

    # Should be deterministic
    assert compute_checksum(data) == checksum

    # Different data should produce different checksum
    assert compute_checksum(b"Different data") != checksum
