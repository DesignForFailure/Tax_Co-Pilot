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

"""Run-listing pagination tests (Milestone 15).

Covers the paginated ``list_return_runs`` query (subset correctness,
total counts, clamped out-of-range pages, tax-year filtering), the
``count_return_runs``/``list_all_return_runs`` helpers, and the ``/runs``
page controls.
"""

import json
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.services.database import (
    count_return_runs,
    get_connection,
    init_db,
    list_all_return_runs,
    list_return_runs,
    save_return_run,
)
from main import app

CSRF = "test-csrf-token"

_BASE_FORM = {
    "csrf_token": CSRF,
    "tax_year": "2024",
    "filing_status": "single",
    "p_first": "Page",
    "p_last": "Tester",
    "p_w2_0_employer": "Acme",
    "p_w2_0_wages": "75000",
    "p_w2_0_federal_withheld": "10000",
}


def _run(index: int, tax_year: int = 2024) -> dict:
    return {
        "id": f"page-run-{index:03d}",
        "tax_year": tax_year,
        "filing_status": "single",
        "scenario_name": "baseline",
        "rule_pack_version": "1.0.0",
        "rule_pack_checksum": "abc",
        # Zero-padded minutes keep created_at ordering aligned with index.
        "created_at": f"2024-06-01T00:{index:02d}:00Z",
        "input_snapshot": {"tax_year": tax_year},
        "output": {"agi": "1000"},
        "trace": [],
        "state_outputs": [],
    }


@pytest.fixture(autouse=True)
def _clean_db():  # type: ignore[no-untyped-def]
    init_db()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")
    yield
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")


def _seed(count: int, tax_year: int = 2024) -> None:
    for i in range(count):
        save_return_run(_run(i, tax_year))


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


# ─── Database layer ────────────────────────────────────────────


def test_first_page_returns_page_size_and_total() -> None:
    _seed(30)
    runs, total = list_return_runs(page=1, page_size=25)
    assert len(runs) == 25
    assert total == 30
    # Newest first: highest index leads.
    assert runs[0]["id"] == "page-run-029"


def test_second_page_returns_remainder() -> None:
    _seed(30)
    runs, total = list_return_runs(page=2, page_size=25)
    assert len(runs) == 5
    assert total == 30
    assert runs[-1]["id"] == "page-run-000"


def test_pages_do_not_overlap_and_cover_everything() -> None:
    _seed(30)
    page1, _ = list_return_runs(page=1, page_size=25)
    page2, _ = list_return_runs(page=2, page_size=25)
    ids = [r["id"] for r in page1] + [r["id"] for r in page2]
    assert len(ids) == 30
    assert len(set(ids)) == 30


def test_page_zero_and_negative_clamp_to_first_page() -> None:
    _seed(5)
    for bad_page in (0, -1):
        runs, total = list_return_runs(page=bad_page, page_size=25)
        assert total == 5
        assert [r["id"] for r in runs] == [r["id"] for r in list_return_runs(page=1)[0]]


def test_page_past_the_end_is_empty_with_accurate_total() -> None:
    _seed(5)
    runs, total = list_return_runs(page=99, page_size=25)
    assert runs == []
    assert total == 5


def test_tax_year_filter_paginates_and_counts_independently() -> None:
    _seed(3, tax_year=2023)
    for i in range(3, 7):
        save_return_run(_run(i, tax_year=2024))
    runs, total = list_return_runs(2023, page=1, page_size=2)
    assert total == 3
    assert len(runs) == 2
    assert all(r["tax_year"] == 2023 for r in runs)
    assert count_return_runs(2023) == 3
    assert count_return_runs(2024) == 4
    assert count_return_runs() == 7


def test_list_all_return_runs_ignores_pagination() -> None:
    _seed(30)
    assert len(list_all_return_runs()) == 30


# ─── /runs route ───────────────────────────────────────────────


def test_runs_page_shows_25_and_controls() -> None:
    _seed(30)
    resp = _client().get("/runs")
    assert resp.status_code == 200
    assert resp.text.count("page-run-") >= 25
    assert "page-run-029" in resp.text
    assert "page-run-000" not in resp.text  # oldest run is on page 2
    assert "Showing 1–25 of 30 runs" in resp.text
    # Page 1: Previous disabled, Next enabled.
    assert 'aria-disabled="true">Previous</span>' in resp.text
    assert '<a href="/runs?page=2" class="btn btn-sm btn-outline">Next</a>' in resp.text


def test_runs_page_two_shows_remainder() -> None:
    _seed(30)
    resp = _client().get("/runs?page=2")
    assert resp.status_code == 200
    assert "page-run-000" in resp.text
    assert "page-run-029" not in resp.text
    assert "Showing 26–30 of 30 runs" in resp.text
    # Last page: Next disabled, Previous enabled.
    assert 'aria-disabled="true">Next</span>' in resp.text
    assert '<a href="/runs?page=1" class="btn btn-sm btn-outline">Previous</a>' in resp.text


def test_runs_page_zero_and_negative_render_first_page() -> None:
    _seed(3)
    for bad in ("0", "-1"):
        resp = _client().get(f"/runs?page={bad}")
        assert resp.status_code == 200
        assert "Showing 1–3 of 3 runs" in resp.text


def test_runs_page_past_end_redirects_to_last_page() -> None:
    _seed(30)
    resp = _client().get("/runs?page=99", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/runs?page=2"


def test_runs_single_run_summary_is_singular() -> None:
    _seed(1)
    resp = _client().get("/runs")
    assert "Showing 1–1 of 1 run" in resp.text


def test_export_all_exports_beyond_one_page() -> None:
    _seed(30)
    resp = _client().get("/export-all")
    assert resp.status_code == 200
    assert len(resp.json()) == 30


def test_home_run_count_reflects_all_pages() -> None:
    # The home page hydrates the latest run into a full ReturnRun model, so
    # seed one real run via /calculate and clone it past the page size.
    c = _client()
    c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    row = list_all_return_runs()[0]
    base = {
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
    for i in range(29):
        clone = dict(base)
        clone["id"] = f"home-clone-{i:02d}"
        clone["created_at"] = f"2024-07-01T00:{i:02d}:00Z"
        save_return_run(clone)

    resp = c.get("/")
    assert resp.status_code == 200
    assert ">30</div>" in resp.text
