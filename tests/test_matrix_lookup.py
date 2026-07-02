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

"""matrix_lookup rule type tests (Milestone 16).

Covers loader validation (key list shape, table depth, numeric leaves,
string keys), evaluation across key combinations, numeric key
canonicalization, dependency ordering, trace output, clear errors for
unknown key paths, and the web-editor guard.
"""

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml
from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack, RulePackError
from app.models.domain import FilingStatus, TaxReturnInput
from app.route_helpers.form_parsing import parse_rule_form

# 2024 EIC maximum credit table (the M19 use case this type unblocks).
_EIC_TABLE = {
    "single": {"0": "632", "1": "4213", "2": "6960", "3": "7830"},
    "mfj": {"0": "632", "1": "4213", "2": "6960", "3": "7830"},
}


def _matrix_rule(**overrides: Any) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "id": "fed.2024.credits.eic.max_credit",
        "type": "matrix_lookup",
        "description": "EIC maximum credit by filing status and children",
        "keys": ["input.filing_status", "input.qualifying_children"],
        "table": _EIC_TABLE,
    }
    rule.update(overrides)
    return rule


def _write_pack(tmp_path: Path, rules: list[dict], constants: dict | None = None) -> Path:
    (tmp_path / "manifest.yaml").write_text(
        yaml.safe_dump({"version": "1.0.0", "tax_year": 2024, "jurisdiction": "federal"})
    )
    (tmp_path / "rules.yaml").write_text(
        yaml.safe_dump({"constants": constants or {}, "rules": rules})
    )
    return tmp_path


def _input(filing_status: FilingStatus = FilingStatus.SINGLE, children: int = 0) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=2024, filing_status=filing_status, qualifying_children=children
    )


def _evaluate(pack_dir: Path, inputs: TaxReturnInput) -> CalculationEngine:
    engine = CalculationEngine(RulePack.load(pack_dir), inputs)
    engine.run()
    return engine


# ─── Loader validation ─────────────────────────────────────────


def test_valid_matrix_lookup_loads(tmp_path: Path) -> None:
    pack = RulePack.load(_write_pack(tmp_path, [_matrix_rule()]))
    assert "fed.2024.credits.eic.max_credit" in pack.rules


def test_keys_must_be_a_list_of_two_or_more(tmp_path: Path) -> None:
    for bad_keys in (None, "input.filing_status", ["input.filing_status"], []):
        pack_dir = _write_pack(tmp_path, [_matrix_rule(keys=bad_keys)])
        with pytest.raises(RulePackError, match="at least 2 entries"):
            RulePack.load(pack_dir)


def test_key_entries_must_be_ref_strings_or_ref_mappings(tmp_path: Path) -> None:
    for bad_entry in (7, "", {"literal": "1"}, {"ref": ""}):
        pack_dir = _write_pack(
            tmp_path, [_matrix_rule(keys=["input.filing_status", bad_entry])]
        )
        with pytest.raises(RulePackError, match="keys\\[1\\]"):
            RulePack.load(pack_dir)


def test_table_must_be_non_empty_mapping(tmp_path: Path) -> None:
    bad_tables: tuple[Any, ...] = (None, {}, "single", ["632"])
    for bad_table in bad_tables:
        pack_dir = _write_pack(tmp_path, [_matrix_rule(table=bad_table)])
        with pytest.raises(RulePackError, match="non-empty 'table'"):
            RulePack.load(pack_dir)


def test_table_too_shallow_is_rejected(tmp_path: Path) -> None:
    # 2 keys declared, but the table bottoms out after one level.
    pack_dir = _write_pack(tmp_path, [_matrix_rule(table={"single": "632"})])
    with pytest.raises(RulePackError, match="nested mapping level"):
        RulePack.load(pack_dir)


def test_table_too_deep_is_rejected(tmp_path: Path) -> None:
    # 2 keys declared, but leaves are another mapping level.
    pack_dir = _write_pack(
        tmp_path, [_matrix_rule(table={"single": {"0": {"x": "632"}}})]
    )
    with pytest.raises(RulePackError, match="must be numeric"):
        RulePack.load(pack_dir)


def test_non_numeric_leaf_is_rejected(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path, [_matrix_rule(table={"single": {"0": "not-a-number"}})]
    )
    with pytest.raises(RulePackError, match="must be numeric"):
        RulePack.load(pack_dir)


def test_non_string_table_key_is_rejected(tmp_path: Path) -> None:
    # Unquoted YAML numeric keys parse as ints and would never match the
    # canonicalized string lookup, so the loader rejects them with guidance.
    pack_dir = _write_pack(tmp_path, [_matrix_rule(table={"single": {0: "632"}})])
    with pytest.raises(RulePackError, match="quote numeric keys"):
        RulePack.load(pack_dir)


def test_unknown_rule_type_still_rejected(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path, [_matrix_rule(type="tensor_lookup")])
    with pytest.raises(RulePackError, match="Unsupported rule type"):
        RulePack.load(pack_dir)


# ─── Evaluation ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("filing_status", "children", "expected"),
    [
        (FilingStatus.SINGLE, 0, "632"),
        (FilingStatus.SINGLE, 2, "6960"),
        (FilingStatus.MFJ, 1, "4213"),
        (FilingStatus.MFJ, 3, "7830"),
    ],
)
def test_matrix_lookup_evaluates_key_combinations(
    tmp_path: Path, filing_status: FilingStatus, children: int, expected: str
) -> None:
    engine = _evaluate(
        _write_pack(tmp_path, [_matrix_rule()]), _input(filing_status, children)
    )
    assert engine.resolved["fed.2024.credits.eic.max_credit"] == Decimal(expected)


def test_filing_status_key_accepts_ref_mapping_form(tmp_path: Path) -> None:
    rule = _matrix_rule(
        keys=[{"ref": "input.filing_status"}, "input.qualifying_children"]
    )
    engine = _evaluate(_write_pack(tmp_path, [rule]), _input(FilingStatus.MFJ, 2))
    assert engine.resolved["fed.2024.credits.eic.max_credit"] == Decimal("6960")


def test_numeric_keys_are_canonicalized(tmp_path: Path) -> None:
    """A rounded Decimal like 2.00 must index table key "2"."""
    rules = [
        _matrix_rule(keys=["input.filing_status", {"ref": "fed.2024.kids_capped"}]),
        {
            "id": "fed.2024.kids_capped",
            "type": "formula",
            "description": "children capped at 3",
            "expression": "min(kids, 3)",
            "inputs": {"kids": {"ref": "input.qualifying_children"}},
            "rounding_precision": 2,
        },
    ]
    engine = _evaluate(_write_pack(tmp_path, rules), _input(FilingStatus.SINGLE, 2))
    assert engine.resolved["fed.2024.kids_capped"] == Decimal("2.00")
    assert engine.resolved["fed.2024.credits.eic.max_credit"] == Decimal("6960")


def test_key_rule_dependency_orders_before_matrix_rule(tmp_path: Path) -> None:
    """A {ref: ...} key is a graph edge: the referenced rule sorts first."""
    rules = [
        _matrix_rule(keys=["input.filing_status", {"ref": "fed.2024.kids_capped"}]),
        {
            "id": "fed.2024.kids_capped",
            "type": "formula",
            "description": "",
            "expression": "min(kids, 3)",
            "inputs": {"kids": {"ref": "input.qualifying_children"}},
        },
    ]
    pack = RulePack.load(_write_pack(tmp_path, rules))
    order = pack.rule_order
    assert order.index("fed.2024.kids_capped") < order.index(
        "fed.2024.credits.eic.max_credit"
    )


def test_unknown_key_value_produces_clear_error(tmp_path: Path) -> None:
    engine = CalculationEngine(
        RulePack.load(_write_pack(tmp_path, [_matrix_rule()])),
        _input(FilingStatus.SINGLE, 7),
    )
    with pytest.raises(RulePackError, match="no entry for key '7' at dimension 1"):
        engine.run()


def test_missing_filing_status_dimension_produces_clear_error(tmp_path: Path) -> None:
    engine = CalculationEngine(
        RulePack.load(_write_pack(tmp_path, [_matrix_rule()])),
        _input(FilingStatus.HOH, 1),
    )
    with pytest.raises(RulePackError, match="no entry for key 'hoh' at dimension 0"):
        engine.run()


def test_three_dimensional_lookup(tmp_path: Path) -> None:
    rule = _matrix_rule(
        keys=[
            "input.filing_status",
            "input.qualifying_children",
            {"ref": "fed.2024.flag"},
        ],
        table={"single": {"1": {"0": "10", "1": "20"}}},
    )
    flag = {
        "id": "fed.2024.flag",
        "type": "sum",
        "description": "",
        "inputs": {"items": [{"literal": "1"}]},
        "rounding_precision": 0,
    }
    engine = _evaluate(_write_pack(tmp_path, [rule, flag]), _input(FilingStatus.SINGLE, 1))
    assert engine.resolved["fed.2024.credits.eic.max_credit"] == Decimal("20")


def test_trace_node_records_lookup_path(tmp_path: Path) -> None:
    engine = _evaluate(_write_pack(tmp_path, [_matrix_rule()]), _input(FilingStatus.MFJ, 2))
    trace = next(
        t for t in engine.traces if t.rule_id == "fed.2024.credits.eic.max_credit"
    )
    assert trace.inputs["keys"] == ["mfj", "2"]
    assert trace.inputs["path"] == "mfj → 2"
    assert trace.result["value"] == "6960"
    assert "mfj × 2" in trace.explanation


def test_matrix_rule_result_feeds_downstream_formula(tmp_path: Path) -> None:
    rules = [
        _matrix_rule(),
        {
            "id": "fed.2024.credits.eic.half",
            "type": "formula",
            "description": "",
            "expression": "credit / 2",
            "inputs": {"credit": {"ref": "fed.2024.credits.eic.max_credit"}},
        },
    ]
    engine = _evaluate(_write_pack(tmp_path, rules), _input(FilingStatus.SINGLE, 3))
    assert engine.resolved["fed.2024.credits.eic.half"] == Decimal("3915")


# ─── Web editor guard ──────────────────────────────────────────


def test_web_editor_rejects_matrix_lookup_edits() -> None:
    fd = FormData(
        [("rule_id", "fed.2024.credits.eic.max_credit"), ("rule_type", "matrix_lookup")]
    )
    with pytest.raises(ValueError, match="matrix_lookup rules cannot be edited"):
        parse_rule_form(fd)
