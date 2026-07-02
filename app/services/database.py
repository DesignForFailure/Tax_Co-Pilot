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

"""SQLite database service for Tax Copilot MVP.

Storage model (MVP):
- Store each ReturnRun as immutable JSON blobs.
- This keeps the DB schema stable while the domain evolves.

Security/QA notes:
- Uses parameterized queries (prevents SQL injection).
- Enables WAL and foreign_keys.
- Sets a busy timeout to reduce "database is locked" errors.

Storage security (with encryption):
- Supports optional encryption-at-rest via SQLCipher (AES-256).
- Password-protected database with PBKDF2 key derivation.
- Transparent encryption (no schema changes required for SQLCipher).

Future improvements:
- Add an index on (tax_year, created_at) if volume grows.
- Add export/import tooling for backups.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path

from app.config import config
from app.log import get_logger
from app.services.encryption import (
    DatabaseState,
    detect_encryption_state,
    get_encryption_provider,
    hybrid_factory,
)

# Overridable so tests (and packagers) can point at an isolated database file.
DB_PATH = Path(os.environ.get("TAX_COPILOT_DB_PATH", "data/tax_copilot.db"))
DB_SCHEMA_VERSION = 1

logger = get_logger(__name__)

# Global password cache (set by main.py startup or unlock route)
_cached_password: str | None = None


def set_cached_password(password: str) -> None:
    """Set the cached database password.

    Called by main.py after user authentication.

    Args:
        password: Database encryption password
    """
    global _cached_password
    _cached_password = password


def get_cached_password() -> str | None:
    """Get the cached database password.

    Returns:
        Cached password if set, None otherwise
    """
    return _cached_password


def clear_cached_password() -> None:
    """Clear the in-memory password cache.

    Called on application shutdown to avoid leaving plaintext
    passwords in process memory longer than necessary.
    """
    global _cached_password
    _cached_password = None


def get_connection(password: str | None = None) -> sqlite3.Connection:
    """Open a SQLite connection with safe defaults.

    Supports both encrypted and unencrypted databases. If database is encrypted,
    password must be provided (either directly or via cached password).

    Notes:
    - `isolation_level=None` puts sqlite3 in autocommit mode.
      For this MVP (append-only inserts), that's fine and avoids partial commits.
    - If you later add multi-step transactions, switch to explicit BEGIN/COMMIT.

    Args:
        password: Optional encryption password. If None, uses cached password or
                 creates unencrypted connection.

    Returns:
        sqlite3.Connection instance

    Raises:
        ValueError: If database is encrypted but no password provided
    """
    # Use provided password or fall back to cached password
    password = password or _cached_password

    # Check if encryption is enabled and database state
    if config.enabled:
        db_state = detect_encryption_state(DB_PATH)

        if db_state == DatabaseState.ENCRYPTED_SQLCIPHER:
            # Database is encrypted, password required
            if not password:
                raise ValueError(
                    "Database is encrypted but no password provided. "
                    "Please unlock the database first."
                )

            # Get encryption provider and create encrypted connection
            provider = get_encryption_provider(
                provider_type=config.provider, kdf_iterations=config.key_derivation_iterations
            )
            return provider.create_connection(DB_PATH, password, timeout=5.0)
        elif db_state == DatabaseState.ENCRYPTED_PYTHON:
            raise ValueError(
                "Python-layer encrypted databases are not supported in runtime reads/writes. "
                "Use SQLCipher encryption."
            )

        elif db_state == DatabaseState.UNENCRYPTED:
            # Database exists but is unencrypted
            # For now, allow unencrypted connections (migration happens in main.py)
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
            conn.row_factory = hybrid_factory
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=5000")
            return conn

        else:  # DatabaseState.NONE
            # New database - create encrypted if password provided
            if password:
                provider = get_encryption_provider(
                    provider_type=config.provider,
                    kdf_iterations=config.key_derivation_iterations,
                )
                return provider.create_connection(DB_PATH, password, timeout=5.0)
            else:
                # Create unencrypted database
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
                conn.row_factory = hybrid_factory
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("PRAGMA busy_timeout=5000")
                return conn

    else:
        # Encryption disabled - use standard SQLite
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
        conn.row_factory = hybrid_factory
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn


# Current hash version for new rows.
_HASH_VERSION = 2


def _compute_integrity_hash_v1(run_data: dict) -> str:
    """Original v1 integrity hash: string concatenation of 6 core fields.

    This algorithm was used before the v2 upgrade that added filing_status,
    scenario_name, rule_pack_version, created_at, and state_outputs.
    Kept for verifying rows written before the upgrade.
    """
    payload = (
        str(run_data.get("id", ""))
        + str(run_data.get("tax_year", ""))
        + json.dumps(run_data.get("input_snapshot", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("output", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("trace", []), sort_keys=True, ensure_ascii=False)
        + str(run_data.get("rule_pack_checksum", ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compute_integrity_hash_v2(run_data: dict) -> str:
    """V2 integrity hash: JSON dict of 11 immutable fields.

    Mutable annotations (`tags`/`notes`) are intentionally excluded so
    run annotations can change without forcing a hash-chain rewrite.
    """
    payload = {
        "id": run_data.get("id", ""),
        "tax_year": run_data.get("tax_year", ""),
        "filing_status": run_data.get("filing_status", ""),
        "scenario_name": run_data.get("scenario_name", "baseline"),
        "rule_pack_version": run_data.get("rule_pack_version", ""),
        "rule_pack_checksum": run_data.get("rule_pack_checksum", ""),
        "created_at": run_data.get("created_at", ""),
        "input_snapshot": run_data.get("input_snapshot", {}),
        "output": run_data.get("output", {}),
        "state_outputs": run_data.get("state_outputs", []),
        "trace": run_data.get("trace", []),
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _compute_integrity_hash(run_data: dict, version: int = _HASH_VERSION) -> str:
    """Dispatch to the correct hash algorithm based on version."""
    if version == 1:
        return _compute_integrity_hash_v1(run_data)
    return _compute_integrity_hash_v2(run_data)


def init_db() -> None:
    """Create tables if they do not exist.

    QA:
    - Safe to call on every startup.
    """
    with closing(get_connection()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS return_runs (
                id TEXT PRIMARY KEY,
                tax_year INTEGER NOT NULL,
                filing_status TEXT NOT NULL,
                scenario_name TEXT NOT NULL DEFAULT 'baseline',
                rule_pack_version TEXT NOT NULL,
                rule_pack_checksum TEXT NOT NULL,
                input_snapshot_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                state_outputs_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(return_runs)").fetchall()}
        if "state_outputs_json" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN state_outputs_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "tags" not in columns:
            conn.execute("ALTER TABLE return_runs ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        if "notes" not in columns:
            conn.execute("ALTER TABLE return_runs ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
        if "integrity_hash" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN integrity_hash TEXT NOT NULL DEFAULT ''"
            )
        if "previous_hash" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''"
            )
        if "hash_version" not in columns:
            # Default 0 means "unknown — needs detection" for pre-existing rows.
            # New rows always write an explicit version.
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN hash_version INTEGER NOT NULL DEFAULT 0"
            )
            # Auto-detect version for existing rows that already have a hash.
            _backfill_hash_versions(conn)
        schema_row = conn.execute("PRAGMA user_version").fetchone()
        current_schema_version = int(schema_row[0]) if schema_row else 0
        if current_schema_version < DB_SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {DB_SCHEMA_VERSION}")
    logger.info("Database initialized (path=%s, schema_version=%s)", DB_PATH, DB_SCHEMA_VERSION)


def _backfill_hash_versions(conn: sqlite3.Connection) -> None:
    """Detect hash algorithm version for rows written before hash_version existed.

    Tries v2 first (current), then v1 (legacy).  Rows matching neither keep
    hash_version=0 so verify_chain can flag them explicitly.
    """
    rows = conn.execute(
        "SELECT id, integrity_hash, tax_year, filing_status, scenario_name, "
        "rule_pack_version, rule_pack_checksum, created_at, "
        "input_snapshot_json, output_json, trace_json, state_outputs_json "
        "FROM return_runs WHERE hash_version = 0 AND integrity_hash != ''"
    ).fetchall()
    for row in rows:
        try:
            run_data = {
                "id": row["id"],
                "tax_year": row["tax_year"],
                "filing_status": row["filing_status"],
                "scenario_name": row["scenario_name"],
                "rule_pack_version": row["rule_pack_version"],
                "rule_pack_checksum": row["rule_pack_checksum"],
                "created_at": row["created_at"],
                "input_snapshot": json.loads(row["input_snapshot_json"]),
                "output": json.loads(row["output_json"]),
                "trace": json.loads(row["trace_json"]),
                "state_outputs": json.loads(row["state_outputs_json"]),
            }
        except (json.JSONDecodeError, TypeError):
            # Corrupted blob — leave hash_version=0 so verify_chain reports it
            # instead of blocking application startup.
            logger.error("Hash version backfill: JSON decode error at run %s", row["id"])
            continue
        stored = row["integrity_hash"]
        if _compute_integrity_hash_v2(run_data) == stored:
            conn.execute(
                "UPDATE return_runs SET hash_version = 2 WHERE id = ?", (row["id"],)
            )
        elif _compute_integrity_hash_v1(run_data) == stored:
            conn.execute(
                "UPDATE return_runs SET hash_version = 1 WHERE id = ?", (row["id"],)
            )
        # else: leave at 0 — genuinely unknown or tampered


def save_return_run(run_data: dict) -> None:
    """Persist a ReturnRun.

    Security:
    - Insert uses placeholders.

    QA:
    - ReturnRuns are treated as immutable; updates are intentionally not supported.
    """
    integrity_hash = _compute_integrity_hash(run_data)
    with closing(get_connection()) as conn:
        # Atomic read-then-insert prevents concurrent saves from
        # duplicating previous_hash in the integrity chain.
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT integrity_hash FROM return_runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
            ).fetchone()
            previous_hash = row["integrity_hash"] if row else ""
            conn.execute(
                """INSERT INTO return_runs
                   (id, tax_year, filing_status, scenario_name,
                    rule_pack_version, rule_pack_checksum,
                    input_snapshot_json, output_json, trace_json, state_outputs_json,
                    created_at, tags, notes, integrity_hash, previous_hash, hash_version)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run_data["id"],
                    run_data["tax_year"],
                    run_data["filing_status"],
                    run_data.get("scenario_name", "baseline"),
                    run_data["rule_pack_version"],
                    run_data["rule_pack_checksum"],
                    json.dumps(run_data["input_snapshot"], ensure_ascii=False),
                    json.dumps(run_data["output"], ensure_ascii=False),
                    json.dumps(run_data["trace"], ensure_ascii=False),
                    json.dumps(run_data.get("state_outputs", []), ensure_ascii=False),
                    run_data["created_at"],
                    run_data.get("tags", ""),
                    run_data.get("notes", ""),
                    integrity_hash,
                    previous_hash,
                    _HASH_VERSION,
                ),
            )
            conn.execute("COMMIT")
        except Exception:
            logger.exception(
                "Return run insert failed; transaction rolled back (id=%s)",
                run_data.get("id"),
            )
            conn.execute("ROLLBACK")
            raise
    logger.info(
        "Return run created (id=%s, tax_year=%s, filing_status=%s)",
        run_data["id"],
        run_data["tax_year"],
        run_data["filing_status"],
    )


def list_return_runs(tax_year: int | None = None) -> list[dict]:
    """List saved runs, newest first."""
    with closing(get_connection()) as conn:
        # rowid tiebreak keeps "newest first" deterministic when two runs
        # share a created_at second (matches the chain-linking queries).
        if tax_year is not None:
            rows = conn.execute(
                "SELECT * FROM return_runs WHERE tax_year = ? "
                "ORDER BY created_at DESC, rowid DESC",
                (tax_year,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM return_runs ORDER BY created_at DESC, rowid DESC"
            ).fetchall()
        return [dict(r) for r in rows]


def get_return_run(run_id: str) -> dict | None:
    """Fetch a single run by id."""
    with closing(get_connection()) as conn:
        row = conn.execute("SELECT * FROM return_runs WHERE id = ?", (run_id,)).fetchone()
        return dict(row) if row else None


def delete_return_run(run_id: str) -> None:
    """Delete a single run by id, relinking the integrity chain around it.

    The successor's previous_hash is re-pointed at the deleted row's
    previous_hash (a linked-list unlink); otherwise verify_chain would
    report an indistinguishable-from-tampering chain_break forever.

    Security:
    - Uses parameterized queries (prevents SQL injection).
    """
    with closing(get_connection()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT integrity_hash, previous_hash, created_at, rowid "
                "FROM return_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if row is None:
                conn.execute("COMMIT")
                logger.debug("Return run deletion skipped; id=%s not found", run_id)
                return

            successor = conn.execute(
                "SELECT id FROM return_runs "
                "WHERE (created_at > ? OR (created_at = ? AND rowid > ?)) "
                "ORDER BY created_at ASC, rowid ASC LIMIT 1",
                (row["created_at"], row["created_at"], row["rowid"]),
            ).fetchone()
            if successor is not None:
                conn.execute(
                    "UPDATE return_runs SET previous_hash = ? WHERE id = ?",
                    (row["previous_hash"], successor["id"]),
                )

            conn.execute("DELETE FROM return_runs WHERE id = ?", (run_id,))
            conn.execute("COMMIT")
        except Exception:
            logger.exception(
                "Return run deletion failed; transaction rolled back (id=%s)", run_id
            )
            conn.execute("ROLLBACK")
            raise
    logger.info("Return run deleted (id=%s)", run_id)


def update_run_annotation(run_id: str, tags: str, notes: str) -> bool:
    """Update tags and notes for an existing run. Returns True if found."""
    with closing(get_connection()) as conn:
        cursor = conn.execute(
            "UPDATE return_runs SET tags = ?, notes = ? WHERE id = ?",
            (tags, notes, run_id),
        )
        return cursor.rowcount > 0


def verify_chain() -> list[dict]:
    """Walk the hash chain and return a list of broken links.

    Returns an empty list if the chain is intact.
    """
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT id, integrity_hash, previous_hash, hash_version, created_at, tax_year, "
            "filing_status, scenario_name, rule_pack_version, rule_pack_checksum, "
            "input_snapshot_json, output_json, trace_json, state_outputs_json "
            "FROM return_runs ORDER BY created_at ASC, rowid ASC"
        ).fetchall()

    errors: list[dict] = []
    prev_hash = ""
    for row in rows:
        run_id = row["id"]
        stored_hash = row["integrity_hash"]
        stored_prev = row["previous_hash"]

        # Verify chain link
        if stored_prev != prev_hash:
            errors.append({
                "id": run_id,
                "error": "chain_break",
                "expected_previous": prev_hash,
                "actual_previous": stored_prev,
            })

        # Recompute integrity hash
        try:
            run_data = {
                "id": run_id,
                "tax_year": row["tax_year"],
                "filing_status": row["filing_status"],
                "scenario_name": row["scenario_name"],
                "rule_pack_version": row["rule_pack_version"],
                "created_at": row["created_at"],
                "input_snapshot": json.loads(row["input_snapshot_json"]),
                "output": json.loads(row["output_json"]),
                "state_outputs": json.loads(row["state_outputs_json"]),
                "trace": json.loads(row["trace_json"]),
                "rule_pack_checksum": row["rule_pack_checksum"],
            }
        except (json.JSONDecodeError, TypeError):
            logger.error("Hash verification: JSON decode error at run %s", run_id)
            errors.append({
                "id": run_id,
                "error": "corrupted",
            })
            prev_hash = stored_hash
            continue
        row_hash_version = row["hash_version"] or _HASH_VERSION
        expected_hash = _compute_integrity_hash(run_data, version=row_hash_version)
        if not stored_hash:
            errors.append({
                "id": run_id,
                "error": "missing_hash",
            })
        elif stored_hash != expected_hash:
            errors.append({
                "id": run_id,
                "error": "tampered",
                "expected_hash": expected_hash,
                "actual_hash": stored_hash,
            })

        # Propagate the STORED hash: insert-time linking records the stored
        # integrity_hash of the previous row, so comparing against the
        # recomputed hash would falsely flag the row after a tampered one.
        prev_hash = stored_hash

    if errors:
        logger.error(
            "Hash chain verification failed: %d error(s), first at run %s (%s)",
            len(errors),
            errors[0].get("id"),
            errors[0].get("error"),
        )
    else:
        logger.info("Hash chain verification passed (%d run(s))", len(rows))
    return errors
