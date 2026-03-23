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

# SPDX-License-Identifier: GPL-3.0-or-later
"""Route coverage tests for previously untested endpoints."""

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
