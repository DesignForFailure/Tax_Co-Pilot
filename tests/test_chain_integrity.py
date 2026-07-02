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

"""Integrity-chain regression tests.

Covers: a content-tampered row must not falsely implicate its successor,
and deleting a run must relink the chain instead of breaking it forever.
"""

import json
from contextlib import closing

import pytest

from app.services.database import (
    delete_return_run,
    get_connection,
    init_db,
    save_return_run,
    verify_chain,
)


@pytest.fixture(autouse=True)
def _clean_db():  # type: ignore[no-untyped-def]
    init_db()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")
    yield
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")


def _run(run_id: str, created_at: str) -> dict:
    return {
        "id": run_id,
        "tax_year": 2024,
        "filing_status": "single",
        "scenario_name": "baseline",
        "rule_pack_version": "1.0.0",
        "rule_pack_checksum": "abc",
        "created_at": created_at,
        "input_snapshot": {"tax_year": 2024},
        "output": {"agi": "1000"},
        "trace": [],
        "state_outputs": [],
    }


def _save_three() -> None:
    save_return_run(_run("run-a", "2024-06-01T00:00:00Z"))
    save_return_run(_run("run-b", "2024-06-02T00:00:00Z"))
    save_return_run(_run("run-c", "2024-06-03T00:00:00Z"))


def test_clean_chain_verifies() -> None:
    _save_three()
    assert verify_chain() == []


def test_tampered_row_does_not_implicate_successor() -> None:
    _save_three()
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE return_runs SET output_json = ? WHERE id = ?",
            (json.dumps({"agi": "999999"}), "run-b"),
        )

    errors = verify_chain()
    assert [e["error"] for e in errors] == ["tampered"]
    assert errors[0]["id"] == "run-b"


def test_delete_middle_run_relinks_chain() -> None:
    _save_three()
    delete_return_run("run-b")
    assert verify_chain() == []


def test_delete_first_and_last_run_relinks_chain() -> None:
    _save_three()
    delete_return_run("run-a")
    assert verify_chain() == []
    delete_return_run("run-c")
    assert verify_chain() == []


def test_delete_missing_run_is_noop() -> None:
    _save_three()
    delete_return_run("no-such-run")
    assert verify_chain() == []
