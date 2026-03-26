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

"""Tests for integrity hash versioning and migration.

The hash algorithm changed from v1 (string concatenation, 6 fields) to v2
(JSON dict, 11 fields).  Rows written by v1 must not be flagged as tampered
when verify_chain runs.
"""

import hashlib
import json
from contextlib import closing

import pytest

from app.services.database import (
    DB_SCHEMA_VERSION,
    get_connection,
    init_db,
    save_return_run,
    verify_chain,
)


@pytest.fixture(autouse=True)
def _ensure_db():  # type: ignore[no-untyped-def]
    init_db()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")
    yield
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")


def _v1_hash(run_data: dict) -> str:
    """Reproduce the original v1 integrity hash algorithm."""
    payload = (
        str(run_data.get("id", ""))
        + str(run_data.get("tax_year", ""))
        + json.dumps(run_data.get("input_snapshot", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("output", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("trace", []), sort_keys=True, ensure_ascii=False)
        + str(run_data.get("rule_pack_checksum", ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _insert_v1_row(run_data: dict, previous_hash: str = "") -> None:
    """Insert a row using the v1 hash algorithm, simulating a pre-upgrade DB."""
    integrity_hash = _v1_hash(run_data)
    with closing(get_connection()) as conn:
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
                "",
                "",
                integrity_hash,
                previous_hash,
                1,
            ),
        )


_SAMPLE_RUN: dict = {
    "id": "v1-test-run-001",
    "tax_year": 2024,
    "filing_status": "single",
    "scenario_name": "baseline",
    "rule_pack_version": "federal-2024-v1.0",
    "rule_pack_checksum": "abc123def456",
    "created_at": "2024-06-15T12:00:00Z",
    "input_snapshot": {
        "tax_year": 2024,
        "filing_status": "single",
        "taxpayers": [{"first_name": "Test", "last_name": "User", "w2s": []}],
    },
    "output": {
        "gross_income": "75000",
        "agi": "75000",
        "federal_tax": "8000",
        "refund_or_owed": "2000",
    },
    "trace": [{"rule_id": "fed.2024.gross_income.total", "result": {"value": "75000"}}],
    "state_outputs": [],
}


def test_v1_row_not_flagged_as_tampered() -> None:
    """A row hashed with v1 must verify clean when hash_version=1."""
    _insert_v1_row(_SAMPLE_RUN)
    errors = verify_chain()
    tampered = [e for e in errors if e["error"] == "tampered"]
    assert tampered == [], f"v1 row falsely flagged as tampered: {tampered}"


def test_v2_row_still_verifies() -> None:
    """A row written by save_return_run (v2) must still verify clean."""
    save_return_run(_SAMPLE_RUN | {"id": "v2-test-run-001"})
    errors = verify_chain()
    tampered = [e for e in errors if e["error"] == "tampered"]
    assert tampered == [], f"v2 row falsely flagged as tampered: {tampered}"


def test_mixed_v1_v2_chain_verifies() -> None:
    """A chain with v1 rows followed by v2 rows verifies intact."""
    _insert_v1_row(_SAMPLE_RUN)

    # Get the v1 row's hash to chain the v2 row
    run2 = _SAMPLE_RUN | {
        "id": "v2-after-v1-run",
        "created_at": "2024-06-16T12:00:00Z",
    }
    save_return_run(run2)

    errors = verify_chain()
    tampered = [e for e in errors if e["error"] == "tampered"]
    assert tampered == [], f"mixed chain falsely flagged: {tampered}"


def test_tampered_v1_row_detected() -> None:
    """If a v1 row's data is modified post-write, it must be caught."""
    _insert_v1_row(_SAMPLE_RUN)

    # Tamper with the stored output
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE return_runs SET output_json = ? WHERE id = ?",
            ('{"gross_income": "999999"}', _SAMPLE_RUN["id"]),
        )

    errors = verify_chain()
    tampered = [e for e in errors if e["error"] == "tampered"]
    assert len(tampered) == 1
    assert tampered[0]["id"] == _SAMPLE_RUN["id"]


def test_tampered_v2_row_detected() -> None:
    """If a v2 row's data is modified post-write, it must be caught."""
    save_return_run(_SAMPLE_RUN | {"id": "v2-tamper-test"})

    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE return_runs SET output_json = ? WHERE id = ?",
            ('{"gross_income": "999999"}', "v2-tamper-test"),
        )

    errors = verify_chain()
    tampered = [e for e in errors if e["error"] == "tampered"]
    assert len(tampered) == 1
    assert tampered[0]["id"] == "v2-tamper-test"


def test_save_return_run_writes_hash_version_2() -> None:
    """New runs must be saved with hash_version=2."""
    save_return_run(_SAMPLE_RUN | {"id": "version-check"})
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT hash_version FROM return_runs WHERE id = ?",
            ("version-check",),
        ).fetchone()
    assert row is not None
    assert row["hash_version"] == 2


def test_backfill_tolerates_corrupted_json_blobs() -> None:
    """A row with corrupted JSON must not crash init_db / backfill."""
    from app.services.database import _backfill_hash_versions

    # Insert a row with hash_version=0 and corrupted JSON
    with closing(get_connection()) as conn:
        conn.execute(
            """INSERT INTO return_runs
               (id, tax_year, filing_status, scenario_name,
                rule_pack_version, rule_pack_checksum,
                input_snapshot_json, output_json, trace_json, state_outputs_json,
                created_at, tags, notes, integrity_hash, previous_hash, hash_version)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "corrupted-row",
                2024,
                "single",
                "baseline",
                "federal-2024-v1.0",
                "abc123",
                "NOT VALID JSON {{{",
                '{"ok": true}',
                "[]",
                "[]",
                "2024-06-15T12:00:00Z",
                "",
                "",
                "somehash",
                "",
                0,
            ),
        )

        # Must not raise — corrupted row stays at hash_version=0
        _backfill_hash_versions(conn)

        row = conn.execute(
            "SELECT hash_version FROM return_runs WHERE id = ?",
            ("corrupted-row",),
        ).fetchone()
    assert row is not None
    assert row["hash_version"] == 0


def test_init_db_sets_independent_schema_generation() -> None:
    """The SQLite schema generation should be tracked independently via user_version."""
    with closing(get_connection()) as conn:
        row = conn.execute("PRAGMA user_version").fetchone()
    assert row is not None
    assert row[0] == DB_SCHEMA_VERSION
