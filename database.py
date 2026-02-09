"""SQLite database service for Tax Copilot MVP.

Uses standard sqlite3 (no SQLCipher in MVP — that's Milestone 6).
Stores ReturnRuns as immutable JSON blobs for now.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB_PATH = Path("data/tax_copilot.db")


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


def save_return_run(run_data: dict):
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
            run_data["scenario_name"],
            run_data["rule_pack_version"],
            run_data["rule_pack_checksum"],
            json.dumps(run_data["input_snapshot"]),
            json.dumps(run_data["output"]),
            json.dumps(run_data["trace"]),
            run_data["created_at"],
        ),
    )
    conn.commit()
    conn.close()


def list_return_runs(tax_year: int | None = None) -> list[dict]:
    conn = get_connection()
    if tax_year:
        rows = conn.execute(
            "SELECT * FROM return_runs WHERE tax_year = ? ORDER BY created_at DESC",
            (tax_year,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM return_runs ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_return_run(run_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM return_runs WHERE id = ?", (run_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
