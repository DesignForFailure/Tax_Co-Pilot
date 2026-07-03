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

"""Regression tests for engine and loader hardening.

Covers: duplicate trace nodes / runtime cycles from bare-string refs,
strict rounding-mode validation, bracket-table ordering validation,
reserved jurisdiction namespaces, state pack prefix enforcement, and the
what-if guard against empty taxpayer lists.
"""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.engine.calculator import CalculationEngine, _round
from app.engine.rule_loader import RulePack, RulePackError, _jurisdiction_prefix
from app.engine.whatif import WhatIfEngine
from app.models.domain import FilingStatus, TaxReturnInput

FED_2024_DIR = Path("rule_packs/federal/2024")


def _write_pack(
    tmp_path: Path,
    rules: list[dict],
    jurisdiction: str = "federal",
    constants: dict | None = None,
) -> Path:
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tax_year": 2024, "jurisdiction": jurisdiction})
    )
    (tmp_path / "rules.yaml").write_text(
        yaml.safe_dump({"constants": constants or {}, "rules": rules})
    )
    return tmp_path


def _minimal_input() -> TaxReturnInput:
    return TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE)


# ─── Rounding modes ─────────────────────────────────────────────


def test_round_rejects_unknown_mode() -> None:
    with pytest.raises(RulePackError, match="Unsupported rounding mode"):
        _round(Decimal("1.5"), "ROUND_HALF_EVEN", 0)


def test_loader_rejects_unknown_rounding_mode(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.x",
                "type": "sum",
                "description": "",
                "rounding": "ROUND_HALF_EVEN",
                "inputs": {"items": [{"literal": "1"}]},
            }
        ],
    )
    with pytest.raises(RulePackError, match="unsupported rounding mode"):
        RulePack.load(pack_dir)


# ─── Bracket table validation ───────────────────────────────────


def _bracket_rule(brackets: list[dict]) -> dict:
    return {
        "id": "fed.2024.tax",
        "type": "bracket_table",
        "description": "",
        "input": {"literal": "1000"},
        "key": "input.filing_status",
        "tables": {"single": brackets},
    }


def test_loader_rejects_out_of_order_brackets(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            _bracket_rule(
                [
                    {"lower": "11600", "upper": "47150", "rate": "0.12"},
                    {"lower": "0", "upper": "11600", "rate": "0.10"},
                ]
            )
        ],
    )
    with pytest.raises(RulePackError, match="overlaps the previous bracket"):
        RulePack.load(pack_dir)


def test_loader_rejects_inverted_bracket_bounds(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [_bracket_rule([{"lower": "1000", "upper": "500", "rate": "0.10"}])],
    )
    with pytest.raises(RulePackError, match="upper 500 <= lower 1000"):
        RulePack.load(pack_dir)


def test_loader_rejects_unbounded_middle_bracket(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            _bracket_rule(
                [
                    {"lower": "0", "rate": "0.10"},
                    {"lower": "11600", "upper": None, "rate": "0.12"},
                ]
            )
        ],
    )
    with pytest.raises(RulePackError, match="not the last bracket"):
        RulePack.load(pack_dir)


def test_loader_accepts_shipped_federal_pack() -> None:
    pack = RulePack.load(FED_2024_DIR)
    assert pack.tax_year == 2024


# ─── Rule id charset ────────────────────────────────────────────


def test_loader_rejects_rule_id_with_quote(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.x');alert(1);//",
                "type": "sum",
                "description": "",
                "inputs": {"items": [{"literal": "1"}]},
            }
        ],
    )
    with pytest.raises(RulePackError, match="unsupported characters"):
        RulePack.load(pack_dir)


# ─── Reserved namespaces / state prefix enforcement ─────────────


def test_jurisdiction_input_is_reserved() -> None:
    with pytest.raises(RulePackError, match="reserved"):
        _jurisdiction_prefix("input")


def test_state_pack_prefix_must_match_state_key(tmp_path: Path) -> None:
    fed = RulePack.load(FED_2024_DIR)
    rogue_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "ny.2024.tax",
                "type": "sum",
                "description": "",
                "inputs": {"items": [{"literal": "1"}]},
            }
        ],
        jurisdiction="NY",
    )
    rogue = RulePack.load(rogue_dir)
    engine = CalculationEngine(fed, _minimal_input(), state_packs={"GA": rogue})
    with pytest.raises(RulePackError, match="expected prefix 'ga.'"):
        engine.run()


# ─── Duplicate traces and runtime cycles (bare-string refs) ─────


def test_bare_string_forward_ref_does_not_duplicate_trace(tmp_path: Path) -> None:
    # "fed.2024.a" sorts before "fed.2024.b" and references it with a bare
    # string, which the loader's dependency graph does not see.
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.a",
                "type": "sum",
                "description": "",
                "inputs": {"items": ["fed.2024.b"]},
            },
            {
                "id": "fed.2024.b",
                "type": "sum",
                "description": "",
                "inputs": {"items": [{"literal": "5"}]},
            },
        ],
    )
    pack = RulePack.load(pack_dir)
    engine = CalculationEngine(pack, _minimal_input())
    engine.evaluate()

    node_ids = [t.rule_id for t in engine.traces]
    assert node_ids.count("fed.2024.b") == 1
    assert engine.resolved["fed.2024.a"] == Decimal("5.00")


def test_bare_string_cycle_raises_rule_pack_error(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.a",
                "type": "sum",
                "description": "",
                "inputs": {"items": ["fed.2024.b"]},
            },
            {
                "id": "fed.2024.b",
                "type": "sum",
                "description": "",
                "inputs": {"items": ["fed.2024.a"]},
            },
        ],
    )
    pack = RulePack.load(pack_dir)
    engine = CalculationEngine(pack, _minimal_input())
    with pytest.raises(RulePackError, match="cycle detected at runtime"):
        engine.evaluate()


# ─── What-if guard ──────────────────────────────────────────────


def test_whatif_rejects_empty_taxpayers() -> None:
    fed = RulePack.load(FED_2024_DIR)
    base = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        other_income=Decimal("100000"),
    )
    with pytest.raises(ValueError, match="at least one taxpayer"):
        WhatIfEngine(fed).compare_filing_status(base)
