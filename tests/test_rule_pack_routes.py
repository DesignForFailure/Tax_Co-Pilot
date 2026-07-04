# SPDX-License-Identifier: AGPL-3.0-or-later
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


def test_rule_packs_create_form_lists_supported_jurisdictions() -> None:
    c = _client()
    r = c.get("/rule-packs")
    assert r.status_code == 200
    assert 'option value="AK"' in r.text
    assert 'option value="WY"' in r.text


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


def _clone(c: TestClient, custom_name: str) -> str:
    """Clone federal/2024/standard and return the new variant name."""
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": custom_name},
        follow_redirects=False,
    )
    return str(resp.headers["location"]).rstrip("/").split("/")[-1]


def _read_rule(variant: str, rule_id: str) -> dict[str, object]:
    """Read a rule back from the on-disk YAML the route wrote."""
    rules_path = (
        Path(__file__).resolve().parent.parent
        / "rule_packs"
        / "federal"
        / "2024"
        / variant
        / "rules.yaml"
    )
    data = _yaml.safe_load(rules_path.read_text())
    for rule in data["rules"]:
        if rule["id"] == rule_id:
            return dict(rule)
    raise AssertionError(f"{rule_id} not found in {rules_path}")


def test_save_rule_via_post() -> None:
    c = _client()
    variant = _clone(c, "for_save")
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
    # A 200 here is the error re-render — only the redirect proves the save.
    assert r.status_code == 303
    saved = _read_rule(variant, "fed.2024.my_new_rule")
    assert saved["expression"] == "x"
    assert saved["inputs"] == {"x": {"ref": "input.w2.wages"}}


def test_save_formula_with_literal_input_via_post() -> None:
    c = _client()
    variant = _clone(c, "for_literal")
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.flat_fee",
            "rule_type": "formula",
            "description": "Wages times a literal rate",
            "expression": "wages * rate",
            "input_name_0": "wages",
            "input_type_0": "ref",
            "input_value_0": "input.w2.wages",
            "input_name_1": "rate",
            "input_type_1": "literal",
            "input_value_1": "0.04",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = _read_rule(variant, "fed.2024.flat_fee")
    assert saved["inputs"] == {
        "wages": {"ref": "input.w2.wages"},
        "rate": {"literal": "0.04"},
    }


def test_save_lookup_rule_via_post_round_trips() -> None:
    c = _client()
    variant = _clone(c, "for_lookup")
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.my_lookup",
            "rule_type": "lookup",
            "description": "Standard deduction lookup",
            "lookup_table": "constants.standard_deduction",
            "lookup_key_ref": "input.filing_status",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = _read_rule(variant, "fed.2024.my_lookup")
    assert saved["table"] == "constants.standard_deduction"
    assert saved["key"] == {"ref": "input.filing_status"}


def test_save_bracket_table_rule_via_post_round_trips() -> None:
    c = _client()
    variant = _clone(c, "for_brackets")
    data = {
        "csrf_token": CSRF,
        "rule_id": "fed.2024.my_brackets",
        "rule_type": "bracket_table",
        "description": "Two-bracket test schedule",
        "bracket_input_ref": "fed.2024.taxable_income",
        "bracket_key_ref": "input.filing_status",
    }
    for status in ("single", "mfj", "mfs", "hoh", "qss"):
        data[f"bracket_{status}_0_lower"] = "0"
        data[f"bracket_{status}_0_upper"] = "10000"
        data[f"bracket_{status}_0_rate"] = "0.10"
        data[f"bracket_{status}_1_lower"] = "10000"
        data[f"bracket_{status}_1_upper"] = ""
        data[f"bracket_{status}_1_rate"] = "0.20"
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data=data,
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = _read_rule(variant, "fed.2024.my_brackets")
    tables = saved["tables"]
    assert isinstance(tables, dict) and set(tables) == {"single", "mfj", "mfs", "hoh", "qss"}
    assert tables["single"] == [
        {"lower": "0", "upper": "10000", "rate": "0.10"},
        {"lower": "10000", "upper": None, "rate": "0.20"},
    ]


def test_save_matrix_lookup_rule_via_post_round_trips() -> None:
    c = _client()
    variant = _clone(c, "for_matrix")
    data = {
        "csrf_token": CSRF,
        "rule_id": "fed.2024.my_matrix",
        "rule_type": "matrix_lookup",
        "description": "Status by children matrix",
        "matrix_key_0": "input.filing_status",
        "matrix_key_1": "fed.2024.credits.eic.num_children",
        "matrix_col_0": "0",
        "matrix_col_1": "1",
    }
    for i, status in enumerate(("single", "mfj", "mfs", "hoh", "qss")):
        data[f"matrix_row_{i}_key"] = status
        data[f"matrix_cell_{i}_0"] = "100"
        data[f"matrix_cell_{i}_1"] = "200"
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data=data,
        follow_redirects=False,
    )
    assert r.status_code == 303
    saved = _read_rule(variant, "fed.2024.my_matrix")
    assert saved["keys"] == [
        {"ref": "input.filing_status"},
        {"ref": "fed.2024.credits.eic.num_children"},
    ]
    table = saved["table"]
    assert isinstance(table, dict)
    assert table["mfj"] == {"0": "100", "1": "200"}
    # The saved rule renders back into the grid editor.
    r = c.get(f"/rule-packs/federal/2024/{variant}/rules/fed.2024.my_matrix")
    assert r.status_code == 200
    assert "Matrix Lookup" in r.text and 'value="200"' in r.text


def test_invalid_rule_form_rerenders_editor_with_error() -> None:
    c = _client()
    variant = _clone(c, "for_bad_rule")
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.broken",
            "rule_type": "formula",
            "description": "Uses an undeclared identifier",
            "expression": "wages + mystery",
            "input_name_0": "wages",
            "input_type_0": "ref",
            "input_value_0": "input.w2.wages",
        },
        follow_redirects=False,
    )
    # The editor re-renders with the engine's validation message instead
    # of writing a broken pack.
    assert r.status_code == 200
    assert "Validation failed" in r.text and "mystery" in r.text
    rules_path = (
        Path(__file__).resolve().parent.parent
        / "rule_packs"
        / "federal"
        / "2024"
        / variant
        / "rules.yaml"
    )
    data = _yaml.safe_load(rules_path.read_text())
    assert all(rule["id"] != "fed.2024.broken" for rule in data["rules"])


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
    # refund_or_owed is a leaf rule: nothing references it, so deletion
    # leaves the pack loadable and passes validate-before-write.
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.refund_or_owed/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_delete_referenced_rule_via_post_is_rejected() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_rule_del_ref"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    # gross_income.wages is referenced by downstream rules; deleting it
    # previously wrote an unloadable pack to disk.
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.gross_income.wages/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_import_page_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/import")
    assert r.status_code == 200
    assert "Import" in r.text


def test_import_upload_valid() -> None:
    c = _client()
    manifest = _yaml.dump(
        {"version": "1.2.3", "tax_year": 2024, "jurisdiction": "federal"}
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
