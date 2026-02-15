"""SQLite database service for Tax Copilot MVP.

Storage model (MVP):
- Store each ReturnRun as immutable JSON blobs.
- This keeps the DB schema stable while the domain evolves.

Security/QA notes:
- Uses parameterized queries (prevents SQL injection).
- Enables WAL and foreign_keys.
- Sets a busy timeout to reduce "database is locked" errors.

Future improvements:
- Add an index on (tax_year, created_at) if volume grows.
- Add optional encryption-at-rest (SQLCipher) if device threat model requires it.
- Add export/import tooling for backups.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/tax_copilot.db")


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with safe defaults.

    Notes:
    - `isolation_level=None` puts sqlite3 in autocommit mode.
      For this MVP (append-only inserts), that's fine and avoids partial commits.
    - If you later add multi-step transactions, switch to explicit BEGIN/COMMIT.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=5.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def init_db() -> None:
    """Create tables if they do not exist.

    QA:
    - Safe to call on every startup.
    """
    conn = get_connection()
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
            created_at TEXT NOT NULL
        );
        """
    )
    conn.close()


def save_return_run(run_data: dict) -> None:
    """Persist a ReturnRun.

    Security:
    - Insert uses placeholders.

    QA:
    - ReturnRuns are treated as immutable; updates are intentionally not supported.
    """
    conn = get_connection()
    conn.execute(
        """INSERT INTO return_runs
           (id, tax_year, filing_status, scenario_name,
            rule_pack_version, rule_pack_checksum,
            input_snapshot_json, output_json, trace_json, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
            run_data["created_at"],
        ),
    )
    conn.close()


def list_return_runs(tax_year: int | None = None) -> list[dict]:
    """List saved runs, newest first."""
    conn = get_connection()
    if tax_year is not None:
        rows = conn.execute(
            "SELECT * FROM return_runs WHERE tax_year = ? ORDER BY created_at DESC",
            (tax_year,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM return_runs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_return_run(run_id: str) -> dict | None:
    """Fetch a single run by id."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM return_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()
    return dict(row) if row else None