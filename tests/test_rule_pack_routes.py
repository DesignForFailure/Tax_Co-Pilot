# SPDX-License-Identifier: GPL-3.0-or-later
"""Route integration tests for rule pack editor."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
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
def _cleanup_custom_packs() -> None:
    """Remove any custom_v* directories created during tests."""
    yield  # type: ignore[misc]
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
