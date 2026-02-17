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
        "p_employer": "Acme",
        "p_wages": "1000",
        "p_withheld": "100",
        "cg_desc": "",
        "cg_proceeds": "0",
        "cg_basis": "0",
    }
    form.update(overrides)
    return client.post("/calculate", data=form, follow_redirects=False)


def test_calculate_submit_rejects_blank_primary_first_name() -> None:
    response = _post_calculate(p_first=" \t\n ")

    assert response.status_code == 400
    assert response.text == "first name is required"


def test_calculate_submit_rejects_blank_primary_last_name() -> None:
    response = _post_calculate(p_last="\u00A0")

    assert response.status_code == 400
    assert response.text == "last name is required"
