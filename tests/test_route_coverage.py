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

"""Route coverage tests for previously untested endpoints."""

import json

import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db, list_return_runs
from main import app

CSRF = "test-csrf-token"

_BASE_FORM = {
    "csrf_token": CSRF,
    "tax_year": "2024",
    "filing_status": "single",
    "p_first": "Test",
    "p_last": "User",
    "p_w2_0_employer": "Acme",
    "p_w2_0_wages": "75000",
    "p_w2_0_federal_withheld": "10000",
}


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def _create_run() -> str:
    c = _client()
    c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    runs = list_return_runs()
    assert runs
    return str(runs[0]["id"])


# ─── Dashboard ────────────────────────────────────────────────


def test_dashboard_empty() -> None:
    """GET / with no runs returns 200."""
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200


def test_dashboard_with_run() -> None:
    """GET / with a saved run returns 200 and shows run data."""
    _create_run()
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "2024" in resp.text


# ─── Runs List ────────────────────────────────────────────────


def test_runs_list() -> None:
    """GET /runs returns 200."""
    c = _client()
    resp = c.get("/runs")
    assert resp.status_code == 200


# ─── Run Detail ───────────────────────────────────────────────


def test_run_detail_valid() -> None:
    """GET /runs/{id} for a valid run returns 200."""
    run_id = _create_run()
    c = _client()
    resp = c.get(f"/runs/{run_id}")
    assert resp.status_code == 200


def test_run_detail_invalid() -> None:
    """GET /runs/{id} for a nonexistent run returns 404."""
    c = _client()
    resp = c.get("/runs/nonexistent-id")
    assert resp.status_code == 404


# ─── Legal ────────────────────────────────────────────────────


def test_legal_page() -> None:
    """GET /legal returns 200."""
    c = _client()
    resp = c.get("/legal")
    assert resp.status_code == 200


# ─── Unlock ───────────────────────────────────────────────────


def test_unlock_get() -> None:
    """GET /unlock returns 200."""
    c = _client()
    resp = c.get("/unlock")
    assert resp.status_code == 200


def test_unlock_post_empty_password() -> None:
    """POST /unlock with empty password redirects with error."""
    c = _client()
    resp = c.post(
        "/unlock",
        data={"csrf_token": CSRF, "password": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers.get("location", "")


# ─── Rotate Key ──────────────────────────────────────────────


def test_rotate_key_get() -> None:
    """GET /rotate-key returns 200."""
    c = _client()
    resp = c.get("/rotate-key")
    assert resp.status_code == 200
    assert "Rotate" in resp.text


def test_rotate_key_post_mismatch() -> None:
    """POST /rotate-key with mismatched passwords redirects with error."""
    c = _client()
    resp = c.post(
        "/rotate-key",
        data={
            "csrf_token": CSRF,
            "current_password": "oldpassword123",
            "new_password": "newpassword1234",
            "confirm_new_password": "differentpassword",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers.get("location", "")


def test_rotate_key_post_same_password() -> None:
    """POST /rotate-key where new == current redirects with error."""
    c = _client()
    resp = c.post(
        "/rotate-key",
        data={
            "csrf_token": CSRF,
            "current_password": "samepassword123",
            "new_password": "samepassword123",
            "confirm_new_password": "samepassword123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers.get("location", "")


# ─── Security Headers ────────────────────────────────────────


def test_security_headers_present() -> None:
    """All security headers are set on responses."""
    c = _client()
    resp = c.get("/legal")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "Permissions-Policy" in resp.headers
    assert "Content-Security-Policy" in resp.headers
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "script-src 'self' 'unsafe-inline'" in csp
    assert "unpkg.com" not in csp
    assert resp.headers.get("Cache-Control") == "no-store"


# ─── Audit Verification ──────────────────────────────────────


def test_audit_verify_returns_json() -> None:
    """GET /audit/verify returns valid JSON with status and errors fields."""
    c = _client()
    resp = c.get("/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "errors" in data
    assert isinstance(data["errors"], list)


def test_audit_verify_runs_have_hashes() -> None:
    """Newly created runs have integrity_hash and previous_hash populated."""
    from app.services.database import get_return_run

    run_id = _create_run()
    r = get_return_run(run_id)
    assert r is not None
    assert r["integrity_hash"] != ""
    assert len(r["integrity_hash"]) == 64  # SHA-256 hex digest


def test_calculate_preserves_withholding_only_1099_rows() -> None:
    """Withholding-only 1099 rows must contribute to saved inputs and totals."""
    from app.services.database import get_return_run
    from main import _load_run_from_row

    c = _client()
    before_ids = {str(run["id"]) for run in list_return_runs()}
    resp = c.post(
        "/calculate",
        data={
            "csrf_token": CSRF,
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Test",
            "p_last": "User",
            "p_1099int_0_payer": "",
            "p_1099int_0_interest": "",
            "p_1099int_0_federal_withheld": "150",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    after_ids = {str(run["id"]) for run in list_return_runs()}
    new_ids = after_ids - before_ids
    assert len(new_ids) == 1
    run_id = new_ids.pop()
    row = get_return_run(run_id)
    assert row is not None
    run = _load_run_from_row(row)
    assert len(run.input_snapshot.taxpayers[0].form_1099_ints) == 1
    assert run.output.total_withholding == 150


def test_audit_verify_detects_state_output_tampering() -> None:
    """Integrity verification should fail if persisted state outputs are modified."""
    from app.services.database import get_connection

    c = _client()
    before_ids = {str(run["id"]) for run in list_return_runs()}
    resp = c.post(
        "/calculate",
        data={
            **_BASE_FORM,
            "p_w2_0_state": "GA",
            "p_w2_0_state_wages": "75000",
            "p_w2_0_state_withheld": "2500",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303

    after_ids = {str(run["id"]) for run in list_return_runs()}
    new_ids = after_ids - before_ids
    assert len(new_ids) == 1
    run_id = new_ids.pop()
    with get_connection() as conn:
        tampered_state_outputs = json.dumps(
            [
                {
                    "state": "GA",
                    "state_agi": "1",
                    "state_standard_deduction": "0",
                    "state_personal_exemption": "0",
                    "state_taxable_income": "1",
                    "state_tax": "999",
                    "state_withholding": "0",
                    "state_refund_or_owed": "-999",
                }
            ]
        )
        conn.execute(
            "UPDATE return_runs SET state_outputs_json = ? WHERE id = ?",
            (tampered_state_outputs, run_id),
        )

    verify_resp = c.get("/audit/verify")
    assert verify_resp.status_code == 200
    data = verify_resp.json()
    assert data["status"] == "integrity_errors"
    assert any(err["id"] == run_id and err["error"] == "tampered" for err in data["errors"])
