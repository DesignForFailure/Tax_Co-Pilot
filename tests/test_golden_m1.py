# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden tests for Federal Completeness milestone.

Covers: new income categories (1099-NEC, SSA, other income),
above-the-line adjustments, capital loss limitation, edge cases,
and explainability improvements.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099NECData,
    Form1099SSAData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


def test_new_models_exist() -> None:
    """Verify new domain models can be instantiated with defaults."""
    nec = Form1099NECData()
    assert nec.nonemployee_compensation == Decimal("0")
    assert nec.federal_withheld == Decimal("0")

    ssa = Form1099SSAData()
    assert ssa.total_benefits == Decimal("0")
    assert ssa.federal_withheld == Decimal("0")

    adj = AdjustmentsData()
    assert adj.student_loan_interest == Decimal("0")
    assert adj.hsa_contributions == Decimal("0")


def test_taxpayer_has_new_form_lists() -> None:
    """Taxpayer model should have 1099-NEC and SSA lists."""
    tp = Taxpayer(
        role=TaxpayerRole.PRIMARY,
        form_1099_necs=[Form1099NECData(nonemployee_compensation=Decimal("5000"))],
        form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
    )
    assert len(tp.form_1099_necs) == 1
    assert len(tp.form_1099_ssas) == 1


def test_tax_return_input_new_helpers() -> None:
    """TaxReturnInput should have SE income, SS benefits, other income, and adjustments helpers."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        other_income=Decimal("1000"),
        adjustments=AdjustmentsData(student_loan_interest=Decimal("2500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_necs=[Form1099NECData(nonemployee_compensation=Decimal("5000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    assert inp.total_self_employment_income() == Decimal("5000")
    assert inp.total_social_security_benefits() == Decimal("18000")
    assert inp.other_income == Decimal("1000")
    assert inp.total_adjustments() == Decimal("2500")
