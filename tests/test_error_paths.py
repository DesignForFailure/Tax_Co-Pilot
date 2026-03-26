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

"""Tests for error handling paths: bad input, missing files, CSRF edge cases."""

import sqlite3
import tempfile

import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db
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


# ─── Import Error Paths ──────────────────────────────────────


def test_import_no_file() -> None:
    """POST /import-returns without a file returns 400."""
    c = _client()
    resp = c.post("/import-returns", data={"csrf_token": CSRF})
    assert resp.status_code == 400
    assert "No file" in resp.text


def test_import_invalid_json() -> None:
    """POST /import-returns with non-JSON returns 400."""
    c = _client()
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("bad.json", b"not json", "application/json")},
    )
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.text


def test_import_non_array() -> None:
    """POST /import-returns with a JSON object (not array) returns 400."""
    c = _client()
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("obj.json", b'{"key": "val"}', "application/json")},
    )
    assert resp.status_code == 400
    assert "array" in resp.text.lower()


# ─── CSRF Edge Cases ─────────────────────────────────────────


def test_csrf_missing_cookie() -> None:
    """POST with form token but no CSRF cookie returns 400."""
    c = TestClient(app, base_url="http://localhost")
    # Deliberately do NOT set the csrf cookie
    resp = c.post(
        "/calculate",
        data=_BASE_FORM,
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "CSRF" in resp.text


# ─── Calculate Validation ────────────────────────────────────


def test_calculate_invalid_filing_status() -> None:
    """POST /calculate with unknown filing status returns 400."""
    c = _client()
    form = {**_BASE_FORM, "filing_status": "invalid"}
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 400


def test_calculate_invalid_tax_year() -> None:
    """POST /calculate with unsupported tax year returns 400."""
    c = _client()
    form = {**_BASE_FORM, "tax_year": "1999"}
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 400
    assert "tax year" in resp.text.lower() or "Unsupported" in resp.text


def test_calculate_mfs_ignores_empty_hidden_spouse_rows() -> None:
    """Blank spouse row keys should not falsely trigger the MFS spouse guard."""
    c = _client()
    form = {
        **_BASE_FORM,
        "filing_status": "mfs",
        "s_w2_0_employer": "",
        "s_w2_0_wages": "",
        "s_w2_0_federal_withheld": "",
    }
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 303


def test_calculate_validation_error_renders_form() -> None:
    """Validation errors re-render the form with an error message (XSS-safe via Jinja2 auto-escape)."""
    c = _client()
    form = {**_BASE_FORM, "p_w2_0_wages": "<script>alert(9)</script>"}
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 400
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Enter tax data" in resp.text  # re-renders the calculate form
    assert "Calculation Error" in resp.text  # error banner shown
    assert "<script>alert(9)</script>" not in resp.text  # XSS-safe: auto-escaped


def test_import_returns_error_summary_is_plain_text() -> None:
    """Import error summaries render as text/plain to avoid HTML/script execution."""
    c = _client()
    payload = b'[{"id":"<script>alert(1)</script>","oops":1}]'
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("bad.json", payload, "application/json")},
    )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/plain")


# ─── Annotate / Delete Nonexistent Runs ──────────────────────


def test_annotate_nonexistent_run() -> None:
    """POST /runs/fake/annotate on a missing run doesn't crash."""
    c = _client()
    resp = c.post(
        "/runs/fake-id/annotate",
        data={"csrf_token": CSRF, "tags": "test", "notes": "test"},
        follow_redirects=False,
    )
    # Should return 404 — run doesn't exist
    assert resp.status_code == 404


def test_delete_nonexistent_run() -> None:
    """POST /runs/fake/delete on a missing run doesn't crash."""
    c = _client()
    resp = c.post(
        "/runs/fake-id/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert resp.status_code == 303


# ─── Restore Success Path ────────────────────────────────────


def test_restore_valid_sqlite() -> None:
    """POST /restore with a valid SQLite file succeeds."""
    # Create a minimal valid SQLite database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp_path = tmp.name
    conn = sqlite3.connect(tmp_path)
    conn.execute("CREATE TABLE test (id INTEGER)")
    conn.commit()
    conn.close()
    with open(tmp_path, "rb") as f:
        db_bytes = f.read()

    c = _client()
    resp = c.post(
        "/restore",
        data={"csrf_token": CSRF},
        files={"file": ("backup.db", db_bytes, "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    import os

    os.unlink(tmp_path)
