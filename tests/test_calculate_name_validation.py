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

"""Tests for name field validation in the /calculate form submission."""

from typing import Any

from fastapi.testclient import TestClient
from httpx import Response

from main import app


def _post_calculate(**overrides: Any) -> Response:
    client = TestClient(app, base_url="http://localhost")
    csrf = "test-csrf-token"
    client.cookies.set("csrf", csrf)

    form = {
        "csrf_token": csrf,
        "tax_year": "2024",
        "filing_status": "mfj",
        "p_first": "Jane",
        "p_last": "Doe",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "1000",
        "p_w2_0_federal_withheld": "100",
    }
    form.update(overrides)
    return client.post("/calculate", data=form, follow_redirects=False)


def test_calculate_submit_rejects_blank_primary_first_name() -> None:
    response = _post_calculate(p_first=" \t\n ")

    assert response.status_code == 400
    assert "text/html" in response.headers.get("content-type", "")
    assert "first name is required" in response.text


def test_calculate_submit_rejects_blank_primary_last_name() -> None:
    response = _post_calculate(p_last="\u00A0")

    assert response.status_code == 400
    assert "text/html" in response.headers.get("content-type", "")
    assert "last name is required" in response.text


def test_calculate_submit_rejects_mfs_spouse_aggregation() -> None:
    response = _post_calculate(
        filing_status="mfs",
        s_first="Sam",
        s_last="Doe",
    )

    assert response.status_code == 400
    assert "text/html" in response.headers.get("content-type", "")
    assert "MFS is per-person; submit each spouse as a separate run" in response.text


def test_validation_error_preserves_posted_year_and_filing_status() -> None:
    response = _post_calculate(tax_year="2024", filing_status="single", p_first=" ")

    assert response.status_code == 400
    assert 'value="2024" selected' in response.text
    assert 'value="single" selected' in response.text
