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

"""Route integration tests for Milestone 6 features.

Covers: what-if page, CSV import, audit export, run deletion, run comparison.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.services.csv_import import import_csv
from app.services.database import init_db
from main import app

CSRF = "test-csrf-token"

_BASE_FORM = {
    "csrf_token": CSRF,
    "tax_year": "2024",
    "filing_status": "mfj",
    "p_first": "Jane",
    "p_last": "Doe",
    "p_w2_0_employer": "Acme",
    "p_w2_0_wages": "85000",
    "p_w2_0_federal_withheld": "12000",
}


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    """Ensure the database table exists before each test."""
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def _create_run(client: TestClient) -> str:
    """POST to /calculate and return the saved run ID."""
    r = client.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    assert r.status_code == 303
    from app.services.database import list_all_return_runs

    runs = list_all_return_runs()
    assert runs, "Expected at least one saved run after posting to /calculate"
    return str(runs[0]["id"])


# ─── What-If ──────────────────────────────────────────────────


def test_whatif_get_renders_form() -> None:
    client = _client()
    r = client.get("/whatif")
    assert r.status_code == 200
    assert "MFJ vs MFS" in r.text


def test_whatif_post_returns_comparison() -> None:
    client = _client()
    form = dict(_BASE_FORM)
    form["csrf_token"] = CSRF
    r = client.post("/whatif", data=form)
    assert r.status_code == 200
    # Recommendation card and savings must appear in the page
    assert "MFJ" in r.text
    assert "MFS" in r.text
    assert "savings" in r.text.lower() or "Recommendation" in r.text


def test_whatif_post_csrf_rejected() -> None:
    client = _client()
    form = dict(_BASE_FORM)
    form["csrf_token"] = "bad-token"
    r = client.post("/whatif", data=form)
    assert r.status_code == 400


def test_whatif_post_shows_inline_error_for_unallocated_household_fields() -> None:
    client = _client()
    form = dict(_BASE_FORM)
    form["other_income"] = "1000"
    form["s_first"] = "Jane"
    form["s_last"] = "Doe"
    form["s_w2_0_employer"] = "SpouseCo"
    form["s_w2_0_wages"] = "45000"
    form["s_w2_0_federal_withheld"] = "5000"
    r = client.post("/whatif", data=form)
    assert r.status_code == 400
    assert "Cannot Compare This Scenario Yet" in r.text
    assert "cannot safely allocate household-level" in r.text


# ─── CSV Import ───────────────────────────────────────────────


def test_import_csv_get_renders_form() -> None:
    client = _client()
    r = client.get("/import-csv")
    assert r.status_code == 200
    assert "Import CSV" in r.text


def test_import_csv_post_w2_success() -> None:
    client = _client()
    csv_text = "employer_name,wages,federal_withheld,state,state_wages,state_withheld\nAcme,85000,12000,GA,85000,4000\n"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "W2", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "Acme" in r.text
    assert "85000" in r.text


def test_import_csv_post_1099b_success() -> None:
    client = _client()
    csv_text = "description,proceeds,cost_basis,is_long_term\nAAPL sale,900,200,true\n"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "1099-B", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "AAPL sale" in r.text


def test_import_csv_post_1099int_success() -> None:
    client = _client()
    csv_text = "payer_name,interest_income,federal_withheld\nFirst Bank,500,0\n"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "1099-INT", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "First Bank" in r.text


def test_import_csv_post_1099div_success() -> None:
    client = _client()
    csv_text = "payer_name,ordinary_dividends,qualified_dividends,federal_withheld\nVanguard,1000,800,0\n"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "1099-DIV", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "Vanguard" in r.text


def test_import_csv_post_shows_parse_errors() -> None:
    client = _client()
    # Row has invalid wages value
    csv_text = "employer_name,wages,federal_withheld\nBadCorp,not_a_number,0\n"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "W2", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "Line 2" in r.text  # error references CSV line 2


def test_import_csv_preserves_input_text() -> None:
    client = _client()
    csv_text = "employer_name,wages,federal_withheld\nAcme,50000,8000"
    r = client.post(
        "/import-csv",
        data={"csrf_token": CSRF, "record_type": "W2", "csv_text": csv_text},
    )
    assert r.status_code == 200
    assert "Acme,50000,8000" in r.text


def test_import_csv_post_csrf_rejected() -> None:
    client = _client()
    r = client.post(
        "/import-csv",
        data={"csrf_token": "bad", "record_type": "W2", "csv_text": ""},
    )
    assert r.status_code == 400


# ─── csv_import unit tests (1099-INT and 1099-DIV) ────────────


def test_unit_import_csv_1099_int() -> None:
    csv_text = "payer_name,interest_income,federal_withheld\nMy Bank,250,0\n"
    records, errors = import_csv(csv_text, "1099-INT")
    assert not errors
    assert len(records) == 1
    rec = records[0]
    assert rec.model_dump()["payer_name"] == "My Bank"  # type: ignore[attr-defined]
    assert rec.model_dump()["interest_income"] == 250  # type: ignore[attr-defined]


def test_unit_import_csv_1099_div() -> None:
    csv_text = "payer_name,ordinary_dividends,qualified_dividends,federal_withheld\nFidelity,1500,1200,100\n"
    records, errors = import_csv(csv_text, "1099-DIV")
    assert not errors
    assert len(records) == 1
    d = records[0].model_dump()  # type: ignore[attr-defined]
    assert d["ordinary_dividends"] == 1500
    assert d["qualified_dividends"] == 1200


# ─── Audit Export ─────────────────────────────────────────────


def test_export_json_returns_download() -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/export/json")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.headers["content-type"].startswith("application/json")
    data = json.loads(r.content)
    assert "id" in data
    assert data["id"] == run_id


def test_export_html_returns_download() -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/export/html")
    assert r.status_code == 200
    assert "attachment" in r.headers.get("content-disposition", "")
    assert "html" in r.headers["content-type"]
    assert "Audit Report" in r.text


def test_export_json_not_found() -> None:
    client = _client()
    r = client.get("/runs/nonexistent-id/export/json")
    assert r.status_code == 404


def test_export_html_not_found() -> None:
    client = _client()
    r = client.get("/runs/nonexistent-id/export/html")
    assert r.status_code == 404


# ─── Run Deletion ─────────────────────────────────────────────


def test_delete_run_removes_from_list() -> None:
    client = _client()
    run_id = _create_run(client)

    r = client.post(
        f"/runs/{run_id}/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/runs"

    from app.services.database import get_return_run

    assert get_return_run(run_id) is None


def test_delete_run_csrf_rejected() -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.post(
        f"/runs/{run_id}/delete",
        data={"csrf_token": "bad"},
        follow_redirects=False,
    )
    assert r.status_code == 400


# ─── Run Comparison ───────────────────────────────────────────


def test_compare_runs_renders_diff_table() -> None:
    client = _client()
    # Create two runs
    run_id_a = _create_run(client)
    # Create a second run with different income
    form2 = dict(_BASE_FORM)
    form2["p_w2_0_wages"] = "100000"
    form2["p_w2_0_federal_withheld"] = "20000"
    r2 = client.post("/calculate", data=form2, follow_redirects=False)
    assert r2.status_code == 303
    from app.services.database import list_all_return_runs

    runs = list_all_return_runs()
    run_id_b = str(runs[0]["id"])

    r = client.get(f"/runs/compare?a={run_id_a}&b={run_id_b}")
    assert r.status_code == 200
    assert "Run A" in r.text
    assert "Run B" in r.text
    assert "gross_income" in r.text
    assert "federal_tax" in r.text


def test_compare_runs_missing_ids_returns_400() -> None:
    client = _client()
    r = client.get("/runs/compare")
    assert r.status_code == 400


def test_compare_runs_bad_ids_returns_404() -> None:
    client = _client()
    r = client.get("/runs/compare?a=bad-id-1&b=bad-id-2")
    assert r.status_code == 404


def test_compare_route_not_matched_as_run_id() -> None:
    """Ensure /runs/compare is not swallowed by /runs/{run_id}."""
    client = _client()
    # A GET to /runs/compare with no query params should return 400,
    # not 404 (which would happen if "compare" were treated as a run_id).
    r = client.get("/runs/compare")
    assert r.status_code == 400
