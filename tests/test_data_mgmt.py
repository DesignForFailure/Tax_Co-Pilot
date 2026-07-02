# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for data management features: export/import, backup, annotations."""

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


def test_export_all_returns_json() -> None:
    """GET /export-all returns a JSON array."""
    c = _client()
    resp = c.get("/export-all")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert isinstance(data, list)


def test_backup_returns_sqlite_file() -> None:
    """GET /backup returns a downloadable file."""
    c = _client()
    resp = c.get("/backup")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_export_import_round_trip() -> None:
    """Exported runs can be re-imported."""
    c = _client()
    # Create a run first
    _create_run()

    # Export
    export_resp = c.get("/export-all")
    assert export_resp.status_code == 200
    exported = export_resp.json()
    assert len(exported) >= 1

    # Delete the run so re-import doesn't hit a unique constraint
    from app.services.database import delete_return_run
    for entry in exported:
        delete_return_run(entry["id"])

    # Import the exported data back
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("runs.json", json.dumps(exported).encode(), "application/json")},
    )
    assert resp.status_code == 200
    assert "Imported" in resp.text

    # Verify the run is back
    runs_after = list_return_runs()
    assert len(runs_after) >= 1


def test_annotate_run() -> None:
    """POST /runs/{id}/annotate updates tags and notes."""
    run_id = _create_run()
    c = _client()

    resp = c.post(
        f"/runs/{run_id}/annotate",
        data={"csrf_token": CSRF, "tags": "final", "notes": "reviewed"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_restore_rejects_non_sqlite() -> None:
    """POST /restore rejects non-SQLite files."""
    c = _client()
    resp = c.post(
        "/restore",
        data={"csrf_token": CSRF},
        files={"file": ("bad.db", b"not a sqlite file", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "valid SQLite" in resp.text
