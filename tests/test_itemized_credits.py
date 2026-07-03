# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for Milestone 8: Itemized Deductions and Child Tax Credit.

Covers: itemized vs standard deduction election, SALT cap, medical
7.5% AGI floor, charitable 60% AGI cap, child tax credit with phaseout.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    ItemizedDeductionData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


# ─── Itemized deduction tests ─────────────────────────────────


def test_itemized_wins_over_standard() -> None:
    """Single filer, $100k wages, large itemized deductions.

    AGI: $100,000. Standard deduction: $14,600.
    Medical: $12,000 - 7.5% × $100k = $12,000 - $7,500 = $4,500.
    SALT: $8,000 (under $10k cap).
    Mortgage: $6,000.
    Charitable cash: $3,000 (under 60% AGI cap).
    Total itemized: $4,500 + $8,000 + $6,000 + $3,000 = $21,500.
    Applied: max($14,600, $21,500) = $21,500.
    Taxable: $100,000 - $21,500 = $78,500.
    Tax: 10% on $11,600 = $1,160 + 12% on $35,550 = $4,266 + 22% on $31,350 = $6,897 = $12,323.
    Refund: $15,000 - $12,323 = $2,677.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("12000"),
            state_local_taxes=Decimal("8000"),
            mortgage_interest=Decimal("6000"),
            charitable_cash=Decimal("3000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.itemized_deductions == Decimal("21500")
    assert run.output.deduction_applied == Decimal("21500")
    assert run.output.taxable_income == Decimal("78500")
    assert run.output.tax_before_credits == Decimal("12323")
    assert run.output.federal_tax == Decimal("12323")
    assert run.output.refund_or_owed == Decimal("2677")


def test_standard_wins_over_itemized() -> None:
    """Single filer, $60k wages, small itemized → standard wins.

    Itemized: medical $0 (below floor) + SALT $3k + mortgage $2k + charitable $4k = $9k.
    Standard: $14,600. Applied: $14,600.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("3000"),
            mortgage_interest=Decimal("2000"),
            charitable_cash=Decimal("4000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.standard_deduction == Decimal("14600")
    assert run.output.itemized_deductions == Decimal("9000")
    assert run.output.deduction_applied == Decimal("14600")


def test_salt_cap_enforced() -> None:
    """SALT cap at $10,000: state taxes $8k + property taxes $6k = $14k → capped to $10k."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("120000"), federal_withheld=Decimal("20000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("8000"),
            real_estate_taxes=Decimal("6000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    # SALT should be capped at $10,000
    salt_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.salt_total")
    assert Decimal(salt_trace.result["value"]) == Decimal("10000")


def test_salt_cap_mfs_5000() -> None:
    """MFS filers get $5,000 SALT cap instead of $10,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFS,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("4000"),
            real_estate_taxes=Decimal("3000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    salt_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.salt_total")
    assert Decimal(salt_trace.result["value"]) == Decimal("5000")


def test_medical_floor_below_threshold() -> None:
    """Medical expenses below 7.5% AGI floor produce $0 deduction."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("5000"),  # below 7.5% × $100k = $7,500
        ),
    )
    run = CalculationEngine(FED, inp).run()

    med_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.medical")
    assert Decimal(med_trace.result["value"]) == Decimal("0")


def test_charitable_agi_cap() -> None:
    """Cash charitable capped at 60% of AGI."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            charitable_cash=Decimal("40000"),  # 60% of $50k = $30k cap
            charitable_noncash=Decimal("1000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    char_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.charitable")
    # min(40k cash, 30k cap) + 1k noncash = 31k, then the combined 60%-of-AGI
    # cap (deep-review fix) brings it back to 30k.
    assert Decimal(char_trace.result["value"]) == Decimal("30000.00")


# ─── Child Tax Credit tests ───────────────────────────────────


def test_ctc_basic() -> None:
    """MFJ, $85k wages, 2 children. CTC: $4,000, no phaseout.

    Tax before credits: $6,232. CTC: $4,000. Tax after: $2,232.
    Withholding: $12,000. Refund: $12,000 - $2,232 = $9,768.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
        qualifying_children=2,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("4000")
    assert run.output.tax_before_credits == Decimal("6232")
    assert run.output.federal_tax == Decimal("2232")
    assert run.output.refund_or_owed == Decimal("9768")


def test_ctc_phaseout_single() -> None:
    """Single, $220k wages, 1 child. CTC phases out.

    AGI: $220,000. Threshold: $200,000. Excess: $20,000.
    Phaseout: $20,000 × 0.05 = $1,000. CTC: max($2,000 - $1,000, 0) = $1,000.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("220000"), federal_withheld=Decimal("40000"))],
            )
        ],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("1000")


def test_ctc_fully_phased_out() -> None:
    """Single, $300k wages, 1 child. CTC fully phased out.

    AGI: $300,000. Threshold: $200,000. Excess: $100,000.
    Phaseout: $100,000 × 0.05 = $5,000. CTC: max($2,000 - $5,000, 0) = $0.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("300000"), federal_withheld=Decimal("60000"))],
            )
        ],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("0")


def test_ctc_zero_children() -> None:
    """No children means no CTC — backward compatible."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("0")
    assert run.output.total_credits == Decimal("0")
    # federal_tax = tax_before_credits when no credits
    assert run.output.federal_tax == run.output.tax_before_credits


def test_ctc_cannot_exceed_tax() -> None:
    """CTC is nonrefundable — cannot reduce tax below zero.

    MFJ, $30k wages, 3 children. CTC base: $6,000.
    Tax before credits: low. CTC capped by tax amount.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("30000"), federal_withheld=Decimal("2000"))],
            )
        ],
        qualifying_children=3,
    )
    run = CalculationEngine(FED, inp).run()

    # Tax after credits cannot go below 0
    assert run.output.federal_tax >= 0
    assert run.output.federal_tax == Decimal("0") or run.output.federal_tax < run.output.tax_before_credits


# ─── Combined test ─────────────────────────────────────────────


def test_itemized_plus_ctc() -> None:
    """Itemized deductions AND child tax credit combined.

    MFJ, $200k wages, 2 children, large itemized.
    Medical: $25k - 7.5% × $200k = $25k - $15k = $10k.
    SALT: $10k (at cap). Mortgage: $15k. Charitable: $5k.
    Itemized: $10k + $10k + $15k + $5k = $40k.
    Standard: $29,200. Applied: $40,000.
    Taxable: $200,000 - $40,000 = $160,000.
    Tax: $2,320 + $8,532 + $14,454 = $25,306.
    CTC: 2 × $2,000 = $4,000 (no phaseout, MFJ threshold $400k).
    Tax after credits: $25,306 - $4,000 = $21,306.
    Withholding: $35,000. Refund: $35,000 - $21,306 = $13,694.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("200000"), federal_withheld=Decimal("35000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("25000"),
            state_local_taxes=Decimal("8000"),
            real_estate_taxes=Decimal("4000"),
            mortgage_interest=Decimal("15000"),
            charitable_cash=Decimal("5000"),
        ),
        qualifying_children=2,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.itemized_deductions == Decimal("40000")
    assert run.output.deduction_applied == Decimal("40000")
    assert run.output.taxable_income == Decimal("160000")
    assert run.output.tax_before_credits == Decimal("25306")
    assert run.output.child_tax_credit == Decimal("4000")
    assert run.output.federal_tax == Decimal("21306")
    assert run.output.refund_or_owed == Decimal("13694")
