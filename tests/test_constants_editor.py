# SPDX-License-Identifier: AGPL-3.0-or-later
"""Constants editor: service CRUD, form parsing, and routes."""

from __future__ import annotations

import shutil
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.datastructures import FormData
from starlette.testclient import TestClient

from app.route_helpers.form_parsing import (
    constant_groups_from_form,
    constant_view_groups,
    parse_constant_form,
)
from app.services.database import init_db
from app.services.rule_pack_editor import (
    clone_pack,
    delete_constant,
    load_pack_detail,
    save_constant,
)
from main import app

CSRF = "test-csrf-token"

_STATUS_VALUES = {"single": "100", "mfj": "200", "mfs": "100", "hoh": "150", "qss": "200"}


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


@pytest.fixture
def tmp_packs(tmp_path: Path) -> Path:
    """Minimal valid federal 2024 pack with one lookup + its constant."""
    pack_dir = tmp_path / "federal" / "2024"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tax_year": 2024, "jurisdiction": "federal"})
    )
    (pack_dir / "rules.yaml").write_text(
        yaml.safe_dump(
            {
                "constants": {"standard_deduction": {"single": "14600", "mfj": "29200"}},
                "rules": [
                    {
                        "id": "fed.2024.standard_deduction",
                        "description": "Standard deduction",
                        "type": "lookup",
                        "table": "constants.standard_deduction",
                        "key": {"ref": "input.filing_status"},
                    }
                ],
            }
        )
    )
    return tmp_path


def _variant(base: Path) -> str:
    info = clone_pack("federal", 2024, "standard", "const_test", base_dir=base)
    return info.variant


def _read_constants(base: Path, variant: str) -> dict[str, Any]:
    rules_path = base / "federal" / "2024" / variant / "rules.yaml"
    data = yaml.safe_load(rules_path.read_text())
    constants = data.get("constants", {})
    assert isinstance(constants, dict)
    return constants


# ─── Service layer ──────────────────────────────────────────────


def test_save_flat_constant(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    save_constant(
        "federal", 2024, variant, "test_credit", dict(_STATUS_VALUES), base_dir=tmp_packs
    )
    constants = _read_constants(tmp_packs, variant)
    assert constants["test_credit"] == _STATUS_VALUES


def test_save_grouped_constant(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    value = {"lower": dict(_STATUS_VALUES), "upper": dict(_STATUS_VALUES)}
    save_constant("federal", 2024, variant, "phaseout", value, base_dir=tmp_packs)
    constants = _read_constants(tmp_packs, variant)
    assert set(constants["phaseout"]) == {"lower", "upper"}


def test_save_constant_updates_in_place(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    updated = dict(_STATUS_VALUES, single="999")
    save_constant(
        "federal", 2024, variant, "standard_deduction", updated, base_dir=tmp_packs
    )
    constants = _read_constants(tmp_packs, variant)
    assert constants["standard_deduction"]["single"] == "999"
    # The pack still loads (the lookup rule still resolves).
    detail = load_pack_detail("federal", 2024, variant, base_dir=tmp_packs)
    assert detail["constants"]["standard_deduction"]["single"] == "999"


def test_save_constant_refuses_standard_pack(tmp_packs: Path) -> None:
    with pytest.raises(ValueError, match="standard pack"):
        save_constant(
            "federal", 2024, "standard", "x", dict(_STATUS_VALUES), base_dir=tmp_packs
        )


def test_save_constant_rejects_bad_name(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    for bad in ("Nope", "1starts_with_digit", "has.dot", "has space", ""):
        with pytest.raises(ValueError, match="Constant name"):
            save_constant(
                "federal", 2024, variant, bad, dict(_STATUS_VALUES), base_dir=tmp_packs
            )


def test_save_constant_rejects_non_decimal_value(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    with pytest.raises(ValueError, match="decimal"):
        save_constant(
            "federal",
            2024,
            variant,
            "bad_value",
            {"single": "not-a-number"},
            base_dir=tmp_packs,
        )


def test_save_constant_rejects_three_level_nesting(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    too_deep = {"a": {"b": {"c": "1"}}}
    with pytest.raises(ValueError, match="two levels"):
        save_constant("federal", 2024, variant, "deep", too_deep, base_dir=tmp_packs)


def test_delete_constant(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    save_constant(
        "federal", 2024, variant, "unused", dict(_STATUS_VALUES), base_dir=tmp_packs
    )
    delete_constant("federal", 2024, variant, "unused", base_dir=tmp_packs)
    assert "unused" not in _read_constants(tmp_packs, variant)


def test_delete_referenced_constant_is_refused(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    # standard_deduction is the lookup rule's table — deleting it would
    # only fail at calculation time, so the service must refuse now.
    with pytest.raises(ValueError, match="referenced by rule"):
        delete_constant("federal", 2024, variant, "standard_deduction", base_dir=tmp_packs)


def test_delete_missing_constant_is_an_error(tmp_packs: Path) -> None:
    variant = _variant(tmp_packs)
    with pytest.raises(ValueError, match="not found"):
        delete_constant("federal", 2024, variant, "ghost", base_dir=tmp_packs)


def test_save_constant_rejects_non_finite_values(tmp_packs: Path) -> None:
    # Decimal("NaN")/"Infinity" construct fine but would silently corrupt
    # calculations (NaN comparisons are False, Infinity uncaps min()).
    variant = _variant(tmp_packs)
    for bad in ("NaN", "Infinity", "-Infinity", "sNaN"):
        with pytest.raises(ValueError, match="finite"):
            save_constant(
                "federal", 2024, variant, "bad", {"single": bad}, base_dir=tmp_packs
            )


def test_save_constant_rejects_reserved_name_add(tmp_packs: Path) -> None:
    # /constants/add is the create-form route; a constant named "add"
    # would shadow its own edit link.
    variant = _variant(tmp_packs)
    with pytest.raises(ValueError, match="reserved"):
        save_constant(
            "federal", 2024, variant, "add", dict(_STATUS_VALUES), base_dir=tmp_packs
        )


def test_delete_constant_catches_unprefixed_table_paths(tmp_packs: Path) -> None:
    # get_constant strips an optional "constants." head, so a lookup with
    # table: "standard_deduction" (no prefix) loads and calculates — the
    # referential check must catch that form too.
    variant = _variant(tmp_packs)
    rules_path = tmp_packs / "federal" / "2024" / variant / "rules.yaml"
    data = yaml.safe_load(rules_path.read_text())
    data["rules"].append(
        {
            "id": "fed.2024.unprefixed_lookup",
            "description": "Bare table path",
            "type": "lookup",
            "table": "standard_deduction",
            "key": {"ref": "input.filing_status"},
        }
    )
    rules_path.write_text(yaml.safe_dump(data, sort_keys=False))
    # Remove the prefixed lookup so only the bare-path rule references it.
    data["rules"] = [r for r in data["rules"] if r["id"] != "fed.2024.standard_deduction"]
    rules_path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(ValueError, match="referenced by rule"):
        delete_constant("federal", 2024, variant, "standard_deduction", base_dir=tmp_packs)


# ─── Form parsing ───────────────────────────────────────────────


def _row(idx: int, name: str, values: dict[str, str]) -> list[tuple[str, str]]:
    fields = [(f"const_group_{idx}_name", name)]
    fields.extend((f"const_group_{idx}_{status}", v) for status, v in values.items())
    return fields


def test_parse_constant_form_flat() -> None:
    fd = FormData([("constant_name", "test_credit"), *_row(0, "", _STATUS_VALUES)])
    name, value = parse_constant_form(fd)
    assert name == "test_credit"
    assert value == _STATUS_VALUES


def test_parse_constant_form_grouped() -> None:
    fd = FormData(
        [
            ("constant_name", "phaseout"),
            *_row(0, "lower", _STATUS_VALUES),
            *_row(1, "upper", _STATUS_VALUES),
        ]
    )
    name, value = parse_constant_form(fd)
    assert name == "phaseout"
    assert set(value) == {"lower", "upper"}
    assert value["lower"] == _STATUS_VALUES


def test_parse_constant_form_requires_all_five_statuses() -> None:
    partial = {"single": "1", "mfj": "2"}
    fd = FormData([("constant_name", "partial"), *_row(0, "", partial)])
    with pytest.raises(ValueError, match="all five filing-status values"):
        parse_constant_form(fd)


def test_parse_constant_form_multiple_rows_need_names() -> None:
    fd = FormData(
        [
            ("constant_name", "phaseout"),
            *_row(0, "lower", _STATUS_VALUES),
            *_row(1, "", _STATUS_VALUES),
        ]
    )
    with pytest.raises(ValueError, match="group name"):
        parse_constant_form(fd)


def test_parse_constant_form_rejects_duplicate_groups() -> None:
    fd = FormData(
        [
            ("constant_name", "phaseout"),
            *_row(0, "lower", _STATUS_VALUES),
            *_row(1, "lower", _STATUS_VALUES),
        ]
    )
    with pytest.raises(ValueError, match="Duplicate group"):
        parse_constant_form(fd)


def test_parse_constant_form_skips_gaps() -> None:
    # A removed middle row leaves an index gap; later rows must survive.
    fd = FormData(
        [
            ("constant_name", "phaseout"),
            *_row(0, "lower", _STATUS_VALUES),
            *_row(2, "upper", _STATUS_VALUES),
        ]
    )
    _, value = parse_constant_form(fd)
    assert set(value) == {"lower", "upper"}


def test_constant_view_groups_round_trip() -> None:
    flat = {"single": "1", "mfj": "2", "mfs": "1", "hoh": "1", "qss": "2"}
    assert constant_view_groups(flat) == [{"name": "", "cells": flat}]
    grouped = {"lower": flat, "upper": flat}
    groups = constant_view_groups(grouped)
    assert groups is not None
    assert [g["name"] for g in groups] == ["lower", "upper"]
    assert groups[0]["cells"] == flat


def test_constant_view_groups_refuses_non_representable_shapes() -> None:
    flat = {"single": "1", "mfj": "2", "mfs": "1", "hoh": "1", "qss": "2"}
    # Keys outside the five filing statuses (e.g. child counts) would be
    # silently destroyed by a grid save.
    assert constant_view_groups({"0": "600", "1": "4200"}) is None
    # Mixed flat/nested values cannot round-trip either.
    assert constant_view_groups({"single": "1", "extra": flat}) is None
    # Three-level nesting inside a group.
    assert constant_view_groups({"group": {"single": flat}}) is None


def test_constant_groups_from_form_echoes_typed_rows() -> None:
    fd = FormData(
        [
            ("constant_name", "partial"),
            ("const_group_0_name", "lower"),
            ("const_group_0_single", "100"),
            # mfj..qss left blank — parse would reject, echo must keep it
        ]
    )
    groups = constant_groups_from_form(fd)
    assert groups == [
        {
            "name": "lower",
            "cells": {"single": "100", "mfj": "", "mfs": "", "hoh": "", "qss": ""},
        }
    ]


# ─── Routes ─────────────────────────────────────────────────────


def _route_variant(c: TestClient) -> str:
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "const_routes"},
        follow_redirects=False,
    )
    return str(resp.headers["location"]).rstrip("/").split("/")[-1]


def test_constant_add_form_renders() -> None:
    c = _client()
    variant = _route_variant(c)
    r = c.get(f"/rule-packs/federal/2024/{variant}/constants/add")
    assert r.status_code == 200
    assert "Add Constant" in r.text


def test_constant_add_edit_delete_via_routes() -> None:
    c = _client()
    variant = _route_variant(c)
    data = {"csrf_token": CSRF, "constant_name": "route_credit", "const_group_0_name": ""}
    for status, value in _STATUS_VALUES.items():
        data[f"const_group_0_{status}"] = value
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/constants/add",
        data=data,
        follow_redirects=False,
    )
    assert r.status_code == 303

    detail = c.get(f"/rule-packs/federal/2024/{variant}")
    assert "constants.route_credit" in detail.text

    edit = c.get(f"/rule-packs/federal/2024/{variant}/constants/route_credit")
    assert edit.status_code == 200
    assert 'value="150"' in edit.text  # hoh cell round-trips

    r = c.post(
        f"/rule-packs/federal/2024/{variant}/constants/route_credit/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303
    detail = c.get(f"/rule-packs/federal/2024/{variant}")
    assert "constants.route_credit" not in detail.text


def test_constant_delete_referenced_via_route_is_rejected() -> None:
    c = _client()
    variant = _route_variant(c)
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/constants/standard_deduction/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_constant_add_partial_row_rerenders_with_error() -> None:
    c = _client()
    variant = _route_variant(c)
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/constants/add",
        data={
            "csrf_token": CSRF,
            "constant_name": "partial",
            "const_group_0_name": "",
            "const_group_0_single": "100",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "all five filing-status values" in r.text


def test_constant_edit_missing_returns_404() -> None:
    c = _client()
    variant = _route_variant(c)
    r = c.get(f"/rule-packs/federal/2024/{variant}/constants/ghost")
    assert r.status_code == 404


def test_constant_error_rerender_preserves_typed_values() -> None:
    c = _client()
    variant = _route_variant(c)
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/constants/add",
        data={
            "csrf_token": CSRF,
            "constant_name": "partial",
            "const_group_0_name": "",
            "const_group_0_single": "1234",
            "const_group_0_mfj": "5678",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    # A rejected save must hand back what was typed, not a blank grid.
    assert 'value="1234"' in r.text and 'value="5678"' in r.text


def test_non_status_keyed_constant_shows_yaml_notice_instead_of_blank_grid() -> None:
    c = _client()
    variant = _route_variant(c)
    rules_path = (
        Path(__file__).resolve().parent.parent
        / "rule_packs"
        / "federal"
        / "2024"
        / variant
        / "rules.yaml"
    )
    data = yaml.safe_load(rules_path.read_text())
    data["constants"]["by_children"] = {"0": "600", "1": "4200"}
    rules_path.write_text(yaml.safe_dump(data, sort_keys=False))
    r = c.get(f"/rule-packs/federal/2024/{variant}/constants/by_children")
    assert r.status_code == 200
    # Saving through the grid would destroy the digit keys — the page must
    # refuse the grid, not render it blank.
    assert "cannot represent" in r.text
    assert "Save Constant" not in r.text


def test_standard_pack_constant_page_is_readonly() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard/constants/standard_deduction")
    assert r.status_code == 200
    assert "Standard Pack Protection" in r.text
    assert "Save Constant" not in r.text
