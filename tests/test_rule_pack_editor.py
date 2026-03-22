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

# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for rule pack editor service."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml  # type: ignore

from app.services.rule_pack_editor import (
    PackInfo,
    _pack_path,
    _validate_path_param,
    export_yaml,
    list_all_packs,
    load_pack_detail,
    validate_pack,
)


@pytest.fixture
def tmp_packs(tmp_path: Path) -> Path:
    """Create a temporary rule_packs directory with a standard federal pack."""
    fed_dir = tmp_path / "federal" / "2024"
    fed_dir.mkdir(parents=True)

    manifest = {"version": "1.0.0", "tax_year": 2024, "jurisdiction": "federal"}
    rules = {
        "constants": {"standard_deduction": {"single": "14600", "mfj": "29200"}},
        "rules": [
            {
                "id": "fed.2024.gross_income.wages",
                "description": "Total W-2 wages",
                "type": "sum",
                "inputs": {"items": {"ref": "input.w2.wages"}},
            }
        ],
    }

    (fed_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (fed_dir / "rules.yaml").write_text(yaml.dump(rules), encoding="utf-8")
    return tmp_path


def test_validate_path_param_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        _validate_path_param("../etc", "jurisdiction")


def test_validate_path_param_rejects_slash() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        _validate_path_param("foo/bar", "jurisdiction")


def test_validate_path_param_accepts_valid() -> None:
    _validate_path_param("federal", "jurisdiction")
    _validate_path_param("CA", "jurisdiction")
    _validate_path_param("custom_v1", "variant")


def test_pack_path_federal_standard(tmp_packs: Path) -> None:
    p = _pack_path("federal", 2024, "standard", base_dir=tmp_packs)
    assert p == tmp_packs / "federal" / "2024"


def test_pack_path_federal_custom(tmp_packs: Path) -> None:
    p = _pack_path("federal", 2024, "custom_v1", base_dir=tmp_packs)
    assert p == tmp_packs / "federal" / "2024" / "custom_v1"


def test_pack_path_state_standard(tmp_packs: Path) -> None:
    p = _pack_path("CA", 2024, "standard", base_dir=tmp_packs)
    assert p == tmp_packs / "state" / "CA" / "2024"


def test_list_all_packs_discovers_standard(tmp_packs: Path) -> None:
    packs = list_all_packs(base_dir=tmp_packs)
    assert len(packs) == 1
    assert packs[0].jurisdiction == "federal"
    assert packs[0].year == 2024
    assert packs[0].variant == "standard"
    assert packs[0].is_custom is False


def test_list_all_packs_discovers_custom(tmp_packs: Path) -> None:
    custom_dir = tmp_packs / "federal" / "2024" / "custom_v1"
    custom_dir.mkdir()
    manifest = {
        "version": "1",
        "tax_year": 2024,
        "jurisdiction": "federal",
        "custom": True,
        "custom_name": "test_scenario",
    }
    rules = {
        "constants": {},
        "rules": [
            {
                "id": "fed.2024.test_rule",
                "description": "Test",
                "type": "formula",
                "expression": "x",
                "inputs": {"x": {"ref": "input.w2.wages"}},
            }
        ],
    }
    (custom_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (custom_dir / "rules.yaml").write_text(yaml.dump(rules), encoding="utf-8")

    packs = list_all_packs(base_dir=tmp_packs)
    assert len(packs) == 2
    custom = [p for p in packs if p.is_custom]
    assert len(custom) == 1
    assert custom[0].variant == "custom_v1"
    assert custom[0].custom_name == "test_scenario"


def test_list_all_packs_skips_underscore_dirs(tmp_packs: Path) -> None:
    tmpl = tmp_packs / "state" / "_template" / "2024"
    tmpl.mkdir(parents=True)
    (tmpl / "manifest.yaml").write_text(
        yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "template"})
    )
    (tmpl / "rules.yaml").write_text(yaml.dump({"rules": []}))
    packs = list_all_packs(base_dir=tmp_packs)
    assert not any(p.jurisdiction == "template" for p in packs)


def test_load_pack_detail(tmp_packs: Path) -> None:
    detail = load_pack_detail("federal", 2024, "standard", base_dir=tmp_packs)
    assert detail["jurisdiction"] == "federal"
    assert detail["year"] == 2024
    assert len(detail["rules"]) == 1
    assert detail["rules"][0]["id"] == "fed.2024.gross_income.wages"


def test_validate_pack_valid(tmp_packs: Path) -> None:
    errors = validate_pack("federal", 2024, "standard", base_dir=tmp_packs)
    assert errors == []


def test_validate_pack_invalid(tmp_packs: Path) -> None:
    bad_dir = tmp_packs / "federal" / "2024" / "custom_v99"
    bad_dir.mkdir()
    (bad_dir / "manifest.yaml").write_text(
        yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "federal"})
    )
    (bad_dir / "rules.yaml").write_text(
        yaml.dump(
            {
                "rules": [
                    {
                        "id": "WRONG.id",
                        "type": "sum",
                        "inputs": {"items": {"ref": "input.w2.wages"}},
                    }
                ]
            }
        )
    )
    errors = validate_pack("federal", 2024, "custom_v99", base_dir=tmp_packs)
    assert len(errors) > 0
    assert "prefix" in errors[0].lower() or "WRONG" in errors[0]


def test_export_yaml(tmp_packs: Path) -> None:
    manifest_bytes, rules_bytes = export_yaml("federal", 2024, "standard", base_dir=tmp_packs)
    assert b"tax_year" in manifest_bytes
    assert b"fed.2024" in rules_bytes


# Ensure PackInfo is importable and usable directly
def test_pack_info_dataclass() -> None:
    info = PackInfo(jurisdiction="federal", year=2024, variant="standard", is_custom=False)
    assert info.jurisdiction == "federal"
    assert info.custom_name == ""
