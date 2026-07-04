# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI authoring prompt builder, reference catalogs, and the ai-assist routes."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.engine.calculator import known_input_refs
from app.services.ai_prompt import MAX_DESCRIPTION_CHARS, build_authoring_prompt
from app.services.database import init_db
from app.services.ref_catalog import constants_table_paths, input_ref_options
from main import app

CSRF = "test-csrf-token"


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


# ─── Engine input catalog ───────────────────────────────────────


def test_known_input_refs_derived_from_engine() -> None:
    refs = known_input_refs()
    assert refs, "catalog must not be empty"
    assert all(ref.startswith("input.") for ref in refs)
    assert "input.w2.wages" in refs
    assert "input.withholding.federal" in refs
    # Key-only pseudo-ref is deliberately excluded from the numeric catalog.
    assert "input.filing_status" not in refs


def test_input_ref_options_adds_state_refs_for_states_only() -> None:
    federal = input_ref_options("federal")
    georgia = input_ref_options("GA")
    assert "input.withholding.state.GA" not in federal
    assert "input.withholding.state.GA" in georgia
    assert "input.state.is_resident.GA" in georgia
    assert "input.state.other_state_tax" in georgia


def test_constants_table_paths_flat_and_grouped() -> None:
    constants = {
        "standard_deduction": {"single": "14600", "mfj": "29200"},
        "education_phaseout": {
            "lower": {"single": "80000"},
            "upper": {"single": "90000"},
        },
    }
    paths = constants_table_paths(constants)
    assert "constants.standard_deduction" in paths
    assert "constants.education_phaseout.lower" in paths
    assert "constants.education_phaseout.upper" in paths
    assert "constants.education_phaseout" not in paths


# ─── Prompt builder ─────────────────────────────────────────────


def test_federal_prompt_contains_the_full_contract() -> None:
    prompt = build_authoring_prompt("federal", 2024, "Simple flat tax test.")
    # The user's ask is embedded.
    assert "Simple flat tax test." in prompt
    # All five rule types and the expression allowlist are described.
    for rule_type in ("formula", "lookup", "sum", "bracket_table", "matrix_lookup"):
        assert rule_type in prompt
    assert "max(" in prompt and "min(" in prompt
    # Required federal headline rules.
    assert "fed.2024.agi.total" in prompt
    assert "fed.2024.refund_or_owed" in prompt
    # Live input catalog and shipped-pack rule ids.
    assert "input.w2.wages" in prompt
    assert "fed.2024.taxable_income" in prompt
    # Output contract matches what paste-import accepts.
    assert "# === MANIFEST ===" in prompt
    assert "# === RULES ===" in prompt


def test_state_prompt_includes_cross_pack_targets_and_state_inputs() -> None:
    prompt = build_authoring_prompt("GA", 2024, "Flat 5.39% on federal AGI.")
    assert "prefix `ga.`" in prompt
    assert "fed.2024.agi.total" in prompt  # cross-pack reference targets
    assert "input.withholding.state.GA" in prompt
    assert "ga.2024.tax" in prompt  # required state rule ids
    assert "apportionment" in prompt


def test_prompt_for_state_without_a_shipped_pack_still_builds() -> None:
    prompt = build_authoring_prompt("ZY", 2024, "New state, flat 3% tax.")
    assert "prefix `zy.`" in prompt
    # No shipped ZY pack — but the federal targets are still listed.
    assert "fed.2024.agi.total" in prompt


def test_prompt_rejects_bad_inputs() -> None:
    with pytest.raises(ValueError, match="two-letter"):
        build_authoring_prompt("notastate", 2024, "x")
    with pytest.raises(ValueError, match="Invalid year"):
        build_authoring_prompt("federal", 1980, "x")
    with pytest.raises(ValueError, match="Describe the rules"):
        build_authoring_prompt("federal", 2024, "   ")
    with pytest.raises(ValueError, match="exceeds"):
        build_authoring_prompt("federal", 2024, "x" * (MAX_DESCRIPTION_CHARS + 1))


# ─── Routes ─────────────────────────────────────────────────────


def test_ai_assist_page_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/ai-assist")
    assert r.status_code == 200
    assert "Generate Prompt" in r.text
    assert "never contacts an AI service" in r.text


def test_ai_assist_post_generates_prompt() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/ai-assist",
        data={
            "csrf_token": CSRF,
            "jurisdiction": "GA",
            "year": "2024",
            "description": "Flat 5.39% income tax on federal AGI.",
        },
    )
    assert r.status_code == 200
    assert "# === MANIFEST ===" in r.text
    assert "Copy prompt" in r.text


def test_ai_assist_post_rejects_bad_jurisdiction() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/ai-assist",
        data={
            "csrf_token": CSRF,
            "jurisdiction": "ZZZ",
            "year": "2024",
            "description": "x",
        },
    )
    assert r.status_code == 400
    assert "two-letter" in r.text


def test_ai_assist_post_rejects_non_numeric_year() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/ai-assist",
        data={
            "csrf_token": CSRF,
            "jurisdiction": "federal",
            "year": "twenty24",
            "description": "x",
        },
    )
    assert r.status_code == 400
    assert "whole number" in r.text
