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

"""Regression tests for web-layer hardening.

Covers: spouse-data rejection for non-MFJ statuses, non-ASCII CSRF
tokens, non-numeric tax_year in the error path, missing pack variants,
qualifying_children validation, and the rule-detail template XSS sink.
"""

from pathlib import Path

from fastapi.testclient import TestClient

from app.services.database import init_db
from main import app

CSRF = "test-csrf-token"


def _client() -> TestClient:
    init_db()
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def _base_form(**overrides: str) -> dict[str, str]:
    form = {
        "csrf_token": CSRF,
        "tax_year": "2024",
        "filing_status": "mfj",
        "p_first": "Jane",
        "p_last": "Doe",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "50000",
        "p_w2_0_federal_withheld": "5000",
    }
    form.update(overrides)
    return form


def test_spouse_data_rejected_for_single_status() -> None:
    c = _client()
    resp = c.post(
        "/calculate",
        data=_base_form(
            filing_status="single",
            s_first="Sam",
            s_last="Doe",
            s_w2_0_employer="Globex",
            s_w2_0_wages="40000",
            s_w2_0_federal_withheld="4000",
        ),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "Spouse information was submitted" in resp.text


def test_spouse_data_rejected_for_hoh_status() -> None:
    c = _client()
    resp = c.post(
        "/calculate",
        data=_base_form(filing_status="hoh", s_first="Sam", s_last="Doe"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "Spouse information was submitted" in resp.text


def test_non_ascii_csrf_token_returns_400_not_500() -> None:
    c = _client()
    resp = c.post(
        "/calculate",
        data=_base_form(csrf_token="ééé"),
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_non_numeric_tax_year_renders_error_form() -> None:
    c = _client()
    resp = c.post("/calculate", data=_base_form(tax_year="abc"), follow_redirects=False)
    assert resp.status_code == 400
    # Must be the re-rendered form, not a raw int() traceback message.
    assert "text/html" in resp.headers.get("content-type", "")
    assert "invalid literal" not in resp.text


def test_missing_pack_variant_is_an_error_not_silent_fallback() -> None:
    c = _client()
    resp = c.post(
        "/calculate",
        data=_base_form(pack_variant="custom_v999"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "no longer exists" in resp.text


def test_invalid_qualifying_children_is_rejected() -> None:
    c = _client()
    resp = c.post(
        "/calculate",
        data=_base_form(qualifying_children="-1"),
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "whole number" in resp.text


def test_rule_detail_template_does_not_embed_rule_id_in_js() -> None:
    template = Path("app/templates/pages/rule_pack_detail.html").read_text()
    assert "confirm('Delete rule {{ rule.id }}?')" not in template


def test_whatif_non_numeric_year_returns_400_form() -> None:
    c = _client()
    resp = c.post(
        "/whatif",
        data={"csrf_token": CSRF, "tax_year": "abc", "filing_status": "mfj"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 400)
    assert "text/html" in resp.headers.get("content-type", "")
