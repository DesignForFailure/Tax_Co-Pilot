# SPDX-License-Identifier: AGPL-3.0-or-later
"""Paste-to-import: split_combined_yaml units and the import route's paste mode."""

from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path

import pytest
import yaml as _yaml
from starlette.testclient import TestClient

from app.services.database import init_db
from app.services.rule_pack_editor import split_combined_yaml
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


_MANIFEST = 'version: "1.0.0"\ntax_year: 2024\njurisdiction: "federal"\n'
_RULES = (
    "constants: {}\n"
    "rules:\n"
    '  - id: "fed.2024.pasted_rule"\n'
    '    description: "Pasted"\n'
    '    type: "formula"\n'
    '    expression: "x"\n'
    "    inputs:\n"
    '      x: { ref: "input.w2.wages" }\n'
)
_COMBINED = f"# === MANIFEST ===\n{_MANIFEST}# === RULES ===\n{_RULES}"


# ─── split_combined_yaml units ──────────────────────────────────


def test_split_plain_combined_document() -> None:
    manifest, rules = split_combined_yaml(_COMBINED)
    assert _yaml.safe_load(manifest)["jurisdiction"] == "federal"
    assert _yaml.safe_load(rules)["rules"][0]["id"] == "fed.2024.pasted_rule"


def test_split_tolerates_chat_prose_and_fences() -> None:
    chat = (
        "Here is the pack you asked for:\n\n"
        "```yaml\n" + _COMBINED + "```\n\n"
        "Let me know if you want the deduction changed."
    )
    manifest, rules = split_combined_yaml(chat)
    assert _yaml.safe_load(manifest)["tax_year"] == 2024
    # Trailing chat prose must not leak into the rules document.
    assert b"Let me know" not in rules
    assert _yaml.safe_load(rules)["rules"][0]["id"] == "fed.2024.pasted_rule"


def test_split_joins_sentinels_across_two_fenced_blocks() -> None:
    chat = (
        "Manifest:\n```yaml\n# === MANIFEST ===\n" + _MANIFEST + "```\n"
        "Rules:\n```yaml\n# === RULES ===\n" + _RULES + "```\n"
    )
    manifest, rules = split_combined_yaml(chat)
    assert _yaml.safe_load(manifest)["jurisdiction"] == "federal"
    assert _yaml.safe_load(rules)["rules"][0]["type"] == "formula"


def test_split_rejects_missing_markers() -> None:
    with pytest.raises(ValueError, match="must contain the marker"):
        split_combined_yaml(_MANIFEST + _RULES)


def test_split_rejects_misordered_markers() -> None:
    swapped = f"# === RULES ===\n{_RULES}# === MANIFEST ===\n{_MANIFEST}"
    with pytest.raises(ValueError, match="must contain the marker"):
        split_combined_yaml(swapped)


def test_split_rejects_empty_sections() -> None:
    with pytest.raises(ValueError, match="empty manifest or rules"):
        split_combined_yaml("# === MANIFEST ===\n# === RULES ===\n" + _RULES)


# ─── Import route paste mode ────────────────────────────────────


def test_paste_import_valid() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "combined_text": _COMBINED, "custom_name": "pasted"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "custom_v" in r.headers.get("location", "")


def test_paste_import_export_round_trip() -> None:
    """A pack exported as one document imports back unchanged."""
    c = _client()
    exported = c.get("/rule-packs/GA/2024/standard/export")
    assert exported.status_code == 200
    r = c.post(
        "/rule-packs/import",
        data={
            "csrf_token": CSRF,
            "combined_text": exported.text,
            "custom_name": "round_trip",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = c.get(r.headers["location"])
    assert detail.status_code == 200
    assert "ga.2024" in detail.text


def test_paste_import_invalid_preserves_paste_and_hints_ai() -> None:
    c = _client()
    bad = _COMBINED.replace("fed.2024.pasted_rule", "wrong.prefix.rule")
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "combined_text": bad, "custom_name": "bad"},
    )
    assert r.status_code == 400
    # The failed paste stays in the textarea for correction, and the page
    # suggests the AI round-trip fix.
    assert "wrong.prefix.rule" in r.text
    assert "Fixing with AI?" in r.text


def test_paste_import_without_markers_reports_format_error() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "combined_text": _MANIFEST, "custom_name": "nomarks"},
    )
    assert r.status_code == 400
    assert "MANIFEST" in r.text


def test_empty_import_form_asks_for_paste_or_files() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "custom_name": "nothing"},
    )
    assert r.status_code == 400
    assert "paste a combined YAML document or upload" in r.text
