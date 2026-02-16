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
