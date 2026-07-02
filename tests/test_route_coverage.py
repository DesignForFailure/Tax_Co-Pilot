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
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

import app.route_helpers.db_state as db_state_module
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


@pytest.fixture
def _locked_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    import app.services.database as db_module
    from app.services.encryption import DatabaseState

    monkeypatch.setattr(db_state_module.encryption_config, "enabled", True)
    monkeypatch.setattr(db_module.config, "enabled", True)
    monkeypatch.setattr(
        db_state_module,
        "detect_encryption_state",
        lambda _path: DatabaseState.ENCRYPTED_SQLCIPHER,
    )
    monkeypatch.setattr(
        db_module,
        "detect_encryption_state",
        lambda _path: DatabaseState.ENCRYPTED_SQLCIPHER,
    )
    db_module.clear_cached_password()
    yield
    db_module.clear_cached_password()


def _create_run() -> str:
    c = _client()
    c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    runs = list_return_runs()
    assert runs
    return str(runs[0]["id"])


# ─── Home / Dashboard ─────────────────────────────────────────


def test_home_page() -> None:
    """GET / returns the landing page."""
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "Workspace Home" in resp.text


def test_home_page_locked_state_prompts_unlock(_locked_database: None) -> None:
    """GET / while locked should prompt unlock instead of claiming there are no runs."""
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "Unlock the database to inspect saved runs and recent activity." in resp.text
    assert "No saved runs are available yet." not in resp.text
    assert "No returns have been saved yet." not in resp.text


def test_dashboard_empty() -> None:
    """GET /dashboard with no runs returns 200."""
    c = _client()
    resp = c.get("/dashboard")
    assert resp.status_code == 200
    assert "Dashboard" in resp.text


def test_dashboard_with_run() -> None:
    """GET /dashboard with a saved run returns 200 and shows run data."""
    _create_run()
    c = _client()
    resp = c.get("/dashboard")
    assert resp.status_code == 200
    assert "2024" in resp.text


@pytest.mark.parametrize(
    "path",
    [
        "/dashboard",
        "/runs",
        "/runs/compare?a=a&b=b",
        "/runs/fake-id",
        "/runs/fake-id/audit",
        "/runs/fake-id/export/json",
        "/runs/fake-id/export/html",
        "/runs/fake-id/forms",
        "/runs/fake-id/export/forms",
        "/export-all",
        "/audit/verify",
    ],
)
def test_locked_db_get_routes_redirect_to_unlock(_locked_database: None, path: str) -> None:
    """Locked DB-backed GET routes should redirect to the unlock page."""
    c = _client()
    resp = c.get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/unlock"


@pytest.mark.parametrize("path", ["/runs/fake-id/delete", "/runs/fake-id/annotate"])
def test_locked_db_post_routes_redirect_to_unlock(_locked_database: None, path: str) -> None:
    """Locked DB-backed POST routes should redirect to the unlock page."""
    c = _client()
    resp = c.post(
        path,
        data={"csrf_token": CSRF, "tags": "review", "notes": "locked"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/unlock"


def test_locked_import_returns_redirects_to_unlock(_locked_database: None) -> None:
    """Import returns should redirect to unlock before attempting DB writes."""
    c = _client()
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("runs.json", b"[]", "application/json")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/unlock"


def test_locked_calculate_submit_redirects_to_unlock(_locked_database: None) -> None:
    """Submitting a calculation while locked should redirect to unlock."""
    c = _client()
    resp = c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers.get("location") == "/unlock"


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


def test_run_audit_valid() -> None:
    """GET /runs/{id}/audit for a valid run returns 200."""
    run_id = _create_run()
    c = _client()
    resp = c.get(f"/runs/{run_id}/audit")
    assert resp.status_code == 200
    assert "Audit Trail" in resp.text


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
    assert "script-src 'self'" in csp
    assert "style-src 'self'" in csp
    assert "unsafe-inline" not in csp
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
    from app.route_helpers.db_state import load_run_from_row
    from app.services.database import get_return_run

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
    run = load_run_from_row(row)
    assert len(run.input_snapshot.taxpayers[0].form_1099_ints) == 1
    assert run.output.total_withholding == 150


def test_calculate_spouse_jump_link_matches_section() -> None:
    """The spouse jump link should target the rendered spouse section anchor."""
    c = _client()
    resp = c.get("/calculate")
    assert resp.status_code == 200
    assert 'href="#spouse_section"' in resp.text
    assert 'id="spouse_section"' in resp.text
    assert 'href="#spouse-section"' not in resp.text


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
