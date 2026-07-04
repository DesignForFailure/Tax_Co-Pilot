# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end authoring proof: a pack built entirely from editor form data
must load and calculate a real return.

This walks the exact path a non-coder takes in the GUI: create an empty
pack, save constants and rules through the same parsers the routes use,
then run the calculation engine against the result.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from starlette.datastructures import FormData, UploadFile

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import FilingStatus, Taxpayer, TaxpayerRole, TaxReturnInput, W2Data
from app.route_helpers.form_parsing import parse_constant_form, parse_rule_form
from app.services.rule_pack_editor import create_empty_pack, save_constant, save_rule

_STATUSES = ("single", "mfj", "mfs", "hoh", "qss")


def _rule_form(fields: dict[str, str]) -> dict[str, object]:
    return parse_rule_form(FormData(list(fields.items())))


def _bracket_fields(rule_id: str) -> dict[str, str]:
    fields = {
        "rule_id": rule_id,
        "rule_type": "bracket_table",
        "description": "Two-bracket schedule",
        "bracket_input_ref": "fed.2024.taxable_income",
        "bracket_key_ref": "input.filing_status",
    }
    for status in _STATUSES:
        fields[f"bracket_{status}_0_lower"] = "0"
        fields[f"bracket_{status}_0_upper"] = "10000"
        fields[f"bracket_{status}_0_rate"] = "0.10"
        fields[f"bracket_{status}_1_lower"] = "10000"
        fields[f"bracket_{status}_1_upper"] = ""
        fields[f"bracket_{status}_1_rate"] = "0.20"
    return fields


def test_form_authored_pack_calculates_a_return(tmp_path: Path) -> None:
    info = create_empty_pack("federal", 2024, "form_authored", base_dir=tmp_path)
    variant = info.variant

    # Constant through the constants-editor form encoding.
    constant_fields: list[tuple[str, str | UploadFile]] = [
        ("constant_name", "standard_deduction"),
        ("const_group_0_name", ""),
    ]
    deduction = {"single": "14600", "mfj": "29200", "mfs": "14600", "hoh": "21900", "qss": "29200"}
    constant_fields.extend(
        (f"const_group_0_{status}", value) for status, value in deduction.items()
    )
    name, value = parse_constant_form(FormData(constant_fields))
    save_constant("federal", 2024, variant, name, value, base_dir=tmp_path)

    # Rules through the rule-editor form encoding — one of each shape the
    # engine's required headline outputs need.
    rules = [
        _rule_form(
            {
                "rule_id": "fed.2024.wages",
                "rule_type": "sum",
                "description": "Total W-2 wages",
                "sum_items_ref": "input.w2.wages",
            }
        ),
        _rule_form(
            {
                "rule_id": "fed.2024.agi.total",
                "rule_type": "formula",
                "description": "AGI",
                "expression": "wages",
                "input_name_0": "wages",
                "input_type_0": "ref",
                "input_value_0": "fed.2024.wages",
            }
        ),
        _rule_form(
            {
                "rule_id": "fed.2024.standard_deduction",
                "rule_type": "lookup",
                "description": "Standard deduction",
                "lookup_table": "constants.standard_deduction",
                "lookup_key_ref": "input.filing_status",
            }
        ),
        _rule_form(
            {
                "rule_id": "fed.2024.taxable_income",
                "rule_type": "formula",
                "description": "Taxable income",
                "expression": "max(agi - deduction, 0)",
                "input_name_0": "agi",
                "input_type_0": "ref",
                "input_value_0": "fed.2024.agi.total",
                "input_name_1": "deduction",
                "input_type_1": "ref",
                "input_value_1": "fed.2024.standard_deduction",
            }
        ),
        _rule_form(_bracket_fields("fed.2024.tax.after_credits")),
        _rule_form(
            {
                "rule_id": "fed.2024.refund_or_owed",
                "rule_type": "formula",
                "description": "Refund or owed",
                "expression": "withholding - tax",
                "input_name_0": "withholding",
                "input_type_0": "ref",
                "input_value_0": "input.withholding.federal",
                "input_name_1": "tax",
                "input_type_1": "ref",
                "input_value_1": "fed.2024.tax.after_credits",
            }
        ),
    ]
    for rule in rules:
        save_rule("federal", 2024, variant, str(rule["id"]), rule, base_dir=tmp_path)

    pack = RulePack.load(tmp_path / "federal" / "2024" / variant)
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Form",
                last_name="Authored",
                w2s=[
                    W2Data(
                        employer_name="Acme",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("5000"),
                    )
                ],
            )
        ],
    )
    engine = CalculationEngine(pack, inputs)
    engine.run()

    # 50000 - 14600 = 35400 taxable; 10000*0.10 + 25400*0.20 = 6080 tax;
    # 5000 withheld - 6080 = -1080 owed.
    assert engine.resolved["fed.2024.taxable_income"] == Decimal("35400")
    assert engine.resolved["fed.2024.tax.after_credits"] == Decimal("6080")
    assert engine.resolved["fed.2024.refund_or_owed"] == Decimal("-1080")
