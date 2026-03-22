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

"""Integration tests for encrypted database operations."""

from __future__ import annotations

import sqlite3
import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest

from app.services.encryption import (
    DatabaseState,
    SQLCipherProvider,
    detect_encryption_state,
    hybrid_factory,
    migrate_to_encrypted,
)


def test_hybrid_factory_supports_index_and_name_access() -> None:
    """Hybrid row factory should support sqlite3.Row-like access patterns."""

    class _Cursor:
        description = (
            ("id", None, None, None, None, None, None),
            ("data", None, None, None, None, None, None),
        )

    row = hybrid_factory(_Cursor(), ("test-1", "hello"))

    assert row[0] == "test-1"
    assert row[1] == "hello"
    assert row["id"] == "test-1"
    assert row["data"] == "hello"
    assert row.keys() == ("id", "data")


def test_hybrid_row_iteration_yields_columns() -> None:
    """HybridRow iteration yields column names (not values) for sqlite3.Row compat."""
    from app.services.encryption import HybridRow

    class FakeCursor:
        description = [("id",), ("name",), ("value",)]

    row = HybridRow(FakeCursor(), ("abc", "test", 42))
    assert list(row) == ["id", "name", "value"]
    assert dict(row) == {"id": "abc", "name": "test", "value": 42}
    assert row.values() == ("abc", "test", 42)


@pytest.fixture
def temp_db() -> Generator[Path, None, None]:
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        yield db_path


@pytest.fixture
def unencrypted_db(temp_db: Path) -> Path:
    """Create an unencrypted test database with sample data."""
    conn = sqlite3.connect(str(temp_db))
    conn.execute(
        """CREATE TABLE return_runs (
            id TEXT PRIMARY KEY,
            tax_year INTEGER NOT NULL,
            filing_status TEXT NOT NULL,
            scenario_name TEXT NOT NULL DEFAULT 'baseline',
            rule_pack_version TEXT NOT NULL,
            rule_pack_checksum TEXT NOT NULL,
            input_snapshot_json TEXT NOT NULL,
            output_json TEXT NOT NULL,
            trace_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        """INSERT INTO return_runs VALUES
        ('test-1', 2024, 'mfj', 'baseline', '1.0', 'abc123',
         '{"taxpayers":[]}', '{"result":100}', '{"trace":[]}', '2024-01-01T00:00:00Z')"""
    )
    conn.commit()
    conn.close()
    return temp_db


def test_sqlcipher_create_and_open(temp_db: Path) -> None:
    """Test creating and opening SQLCipher encrypted database."""
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # noqa: F401
    except ImportError:
        pytest.skip("pysqlcipher3 not available")

    password = "test_password_123"
    provider = SQLCipherProvider(kdf_iterations=100_000)

    # Create encrypted database
    conn = provider.create_connection(temp_db, password, timeout=5.0)
    conn.execute("CREATE TABLE test (id INTEGER, data TEXT)")
    conn.execute("INSERT INTO test VALUES (1, 'hello')")
    conn.commit()
    conn.close()

    # Verify state detection
    assert detect_encryption_state(temp_db) == DatabaseState.ENCRYPTED_SQLCIPHER

    # Reopen and verify data
    conn = provider.create_connection(temp_db, password, timeout=5.0)
    result = conn.execute("SELECT data FROM test WHERE id=1").fetchone()
    assert result[0] == "hello"
    conn.close()


def test_sqlcipher_wrong_password(temp_db: Path) -> None:
    """Test that wrong password fails to open database."""
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # noqa: F401
    except ImportError:
        pytest.skip("pysqlcipher3 not available")

    password = "correct_password"
    provider = SQLCipherProvider(kdf_iterations=100_000)

    # Create encrypted database
    conn = provider.create_connection(temp_db, password, timeout=5.0)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.close()

    # Try to open with wrong password
    with pytest.raises(ValueError, match="Failed to open encrypted database"):
        provider.create_connection(temp_db, "wrong_password", timeout=5.0)


def test_migrate_to_sqlcipher(unencrypted_db: Path) -> None:
    """Test migrating unencrypted database to SQLCipher."""
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # noqa: F401
    except ImportError:
        pytest.skip("pysqlcipher3 not available")

    password = "migration_password_123"

    # Verify initial state
    assert detect_encryption_state(unencrypted_db) == DatabaseState.UNENCRYPTED

    # Perform migration
    migrate_to_encrypted(
        unencrypted_db, password, provider_type="sqlcipher", kdf_iterations=100_000
    )

    # Verify migrated state
    assert detect_encryption_state(unencrypted_db) == DatabaseState.ENCRYPTED_SQLCIPHER

    # Verify backup exists
    backup_path = unencrypted_db.with_suffix(".db.unencrypted.backup")
    assert backup_path.exists()

    # Verify data integrity
    provider = SQLCipherProvider(kdf_iterations=100_000)
    conn = provider.create_connection(unencrypted_db, password, timeout=5.0)
    result = conn.execute("SELECT id, tax_year FROM return_runs").fetchone()
    assert result[0] == "test-1"
    assert result[1] == 2024
    conn.close()


def test_migrate_already_encrypted_fails(temp_db: Path) -> None:
    """Test that migrating already encrypted database fails."""
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher  # noqa: F401
    except ImportError:
        pytest.skip("pysqlcipher3 not available")

    password = "test_password_123"
    provider = SQLCipherProvider(kdf_iterations=100_000)

    # Create encrypted database
    conn = provider.create_connection(temp_db, password, timeout=5.0)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.close()

    # Try to migrate - should fail
    with pytest.raises(ValueError, match="not unencrypted"):
        migrate_to_encrypted(temp_db, "new_password", provider_type="sqlcipher")


def test_detect_encryption_state_comprehensive() -> None:
    """Test encryption state detection for all scenarios."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test 1: Non-existent database
        nonexistent = Path(tmpdir) / "nonexistent.db"
        assert detect_encryption_state(nonexistent) == DatabaseState.NONE

        # Test 2: Unencrypted database
        unencrypted = Path(tmpdir) / "unencrypted.db"
        conn = sqlite3.connect(str(unencrypted))
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()
        assert detect_encryption_state(unencrypted) == DatabaseState.UNENCRYPTED

        # Test 3: Python encrypted database
        python_encrypted = Path(tmpdir) / "python.db"
        conn = sqlite3.connect(str(python_encrypted))
        conn.execute(
            """CREATE TABLE _encryption_metadata (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                encryption_provider TEXT NOT NULL,
                salt BLOB NOT NULL,
                iterations INTEGER NOT NULL,
                encrypted_at TEXT NOT NULL,
                key_version INTEGER NOT NULL
            )"""
        )
        conn.execute(
            """INSERT INTO _encryption_metadata VALUES
            (1, 'python', x'0123456789abcdef', 100000, '2024-01-01', 1)"""
        )
        conn.close()
        assert detect_encryption_state(python_encrypted) == DatabaseState.ENCRYPTED_PYTHON
