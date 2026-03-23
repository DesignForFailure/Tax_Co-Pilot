# SPDX-License-Identifier: GPL-3.0-or-later
"""Route integration tests for rule pack editor."""

from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml as _yaml
from starlette.testclient import TestClient

from app.services.database import init_db
from main import app

CSRF = "test-csrf-token"


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


@pytest.fixture(autouse=True)
def _cleanup_custom_packs() -> Generator[None, None, None]:
    """Remove any custom_v* directories created during tests."""
    yield
    base = Path(__file__).resolve().parent.parent / "rule_packs"
    for custom_dir in base.rglob("custom_v*"):
        if custom_dir.is_dir():
            shutil.rmtree(custom_dir, ignore_errors=True)


def test_rule_packs_list_page() -> None:
    c = _client()
    r = c.get("/rule-packs")
    assert r.status_code == 200
    assert "Rule Pack" in r.text
    assert "federal" in r.text.lower()


def test_pack_detail_page() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard")
    assert r.status_code == 200
    assert "fed.2024" in r.text


def test_clone_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "test_clone"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers.get("location", "")
    assert "custom_v" in loc


def test_validate_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/federal/2024/standard/validate",
        data={"csrf_token": CSRF},
    )
    assert r.status_code == 200
    assert "valid" in r.text.lower() or "error" in r.text.lower()


def test_export_download() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard/export")
    assert r.status_code == 200
    assert "yaml" in r.headers.get("content-type", "").lower() or r.status_code == 200
    assert b"tax_year" in r.content


def test_create_custom_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/create",
        data={"csrf_token": CSRF, "jurisdiction": "federal", "year": "2024", "custom_name": "new_pack"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_delete_custom_pack_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "to_delete"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_rule_editor_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard/rules/fed.2024.gross_income.wages")
    assert r.status_code == 200
    assert "fed.2024.gross_income.wages" in r.text
    assert "sum" in r.text.lower()


def test_add_rule_form_renders() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_add"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.get(f"/rule-packs/federal/2024/{variant}/rules/add")
    assert r.status_code == 200
    assert "Add Rule" in r.text or "New Rule" in r.text


def test_save_rule_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_save"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.my_new_rule",
            "rule_type": "formula",
            "description": "Test formula",
            "expression": "x",
            "input_name_0": "x",
            "input_type_0": "ref",
            "input_value_0": "input.w2.wages",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 or r.status_code == 200


def test_save_existing_rule_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_edit"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.gross_income.wages",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.gross_income.wages",
            "rule_type": "sum",
            "description": "Updated wages",
            "sum_items_ref": "input.w2.wages",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_delete_rule_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_rule_del"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.gross_income.wages/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_import_page_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/import")
    assert r.status_code == 200
    assert "Import" in r.text


def test_import_upload_valid() -> None:
    c = _client()
    manifest = _yaml.dump(
        {"version": "1", "tax_year": 2024, "jurisdiction": "federal"}
    ).encode()
    rules = _yaml.dump(
        {
            "constants": {},
            "rules": [
                {
                    "id": "fed.2024.imported_rule",
                    "description": "Imported",
                    "type": "formula",
                    "expression": "x",
                    "inputs": {"x": {"ref": "input.w2.wages"}},
                }
            ],
        }
    ).encode()
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "custom_name": "uploaded"},
        files={
            "manifest_file": ("manifest.yaml", manifest, "application/x-yaml"),
            "rules_file": ("rules.yaml", rules, "application/x-yaml"),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "custom_v" in r.headers.get("location", "")



def test_calculate_with_custom_variant_param() -> None:
    """The calculate form should accept a pack_variant parameter."""
    c = _client()
    r = c.get("/calculate")
    assert r.status_code == 200
    assert "pack_variant" in r.text or "Rule Pack" in r.text
