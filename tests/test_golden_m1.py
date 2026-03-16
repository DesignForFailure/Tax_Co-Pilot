# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden tests for Federal Completeness milestone.

Covers: new income categories (1099-NEC, SSA, other income),
above-the-line adjustments, capital loss limitation, edge cases,
and explainability improvements.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Form1099INTData,
    Form1099NECData,
    Form1099SSAData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
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


def test_se_income_resolves() -> None:
    """Self-employment income from 1099-NEC should be included in gross income."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_necs=[
                    Form1099NECData(
                        payer_name="Client A",
                        nonemployee_compensation=Decimal("50000"),
                        federal_withheld=Decimal("0"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("50000.00")


def test_student_loan_adjustment_capped() -> None:
    """Student loan interest capped at $2,500."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(student_loan_interest=Decimal("5000")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("57500.00")
    assert run.output.adjustments_total == Decimal("2500.00")


def test_zero_adjustments_backward_compatible() -> None:
    """With no adjustments, AGI should equal gross income (backward compatible)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == run.output.gross_income
    assert run.output.adjustments_total == Decimal("0")


def test_educator_expense_capped_at_300() -> None:
    """Educator expenses capped at $300."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(educator_expenses=Decimal("500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="School", wages=Decimal("45000"), federal_withheld=Decimal("5000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("44700.00")


def test_hsa_limit_varies_by_filing_status() -> None:
    """HSA limit is $4,150 for single, $8,300 for MFJ."""
    for fs, expected_limit in [
        (FilingStatus.SINGLE, Decimal("4150")),
        (FilingStatus.MFJ, Decimal("8300")),
    ]:
        inp = TaxReturnInput(
            tax_year=2024,
            filing_status=fs,
            adjustments=AdjustmentsData(hsa_contributions=Decimal("10000")),
            taxpayers=[
                Taxpayer(
                    role=TaxpayerRole.PRIMARY,
                    w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
                )
            ],
        )
        run = CalculationEngine(FED, inp).run()
        assert run.output.agi == Decimal("80000") - expected_limit


def test_capital_loss_limited_to_neg_3000() -> None:
    """Net capital losses are limited to -$3,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Big loss", proceeds=Decimal("1000"), cost_basis=Decimal("20000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("57000.00")


def test_capital_loss_at_exactly_neg_3000() -> None:
    """Exactly -$3,000 loss should pass through unchanged."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Small loss", proceeds=Decimal("2000"), cost_basis=Decimal("5000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("57000.00")


def test_capital_gain_not_affected_by_loss_limit() -> None:
    """Positive capital gains should not be affected by the loss limit rule."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Gain", proceeds=Decimal("10000"), cost_basis=Decimal("3000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("67000.00")


def test_ss_benefits_below_threshold_not_taxed() -> None:
    """SS benefits not taxed when provisional income is below base threshold.

    Provisional = $0 other income + 50% of $12,000 = $6,000, below $25k single threshold.
    Taxable SS = $0, so gross income = $0 (only the taxable portion enters gross income).
    Any SSA withholding would still produce a refund — this is correct IRS behavior.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("0.00")
    assert run.output.federal_tax == Decimal("0")
    assert run.output.refund_or_owed >= Decimal("0")


def test_ss_benefits_partially_taxed() -> None:
    """SS benefits partially taxed between base and upper thresholds."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("20000"), federal_withheld=Decimal("2000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Provisional = 20000 + 9000 = 29000
    # lower_calc = min((29000-25000)*0.50, (34000-25000)*0.50) = min(2000, 4500) = 2000
    # upper_calc = max((29000-34000)*0.85, 0) = 0
    # taxable SS = min(18000*0.85, 2000+0) = min(15300, 2000) = 2000
    assert run.output.gross_income == Decimal("22000.00")


def test_ss_benefits_max_85_percent_taxed() -> None:
    """High-income: up to 85% of SS benefits are taxable."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("24000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Provisional = 80000 + 12000 = 92000
    # lower_calc = min((92000-25000)*0.50, (34000-25000)*0.50) = min(33500, 4500) = 4500
    # upper_calc = max((92000-34000)*0.85, 0) = 49300
    # taxable SS = min(24000*0.85, 4500+49300) = min(20400, 53800) = 20400
    assert run.output.gross_income == Decimal("100400.00")


@pytest.mark.parametrize(
    "fs,std_ded,first_bracket_top,expected_tax",
    [
        (FilingStatus.SINGLE, Decimal("14600"), Decimal("11600"), Decimal("1160")),
        (FilingStatus.MFJ, Decimal("29200"), Decimal("23200"), Decimal("2320")),
        (FilingStatus.MFS, Decimal("14600"), Decimal("11600"), Decimal("1160")),
        (FilingStatus.HOH, Decimal("21900"), Decimal("16550"), Decimal("1655")),
        (FilingStatus.QSS, Decimal("29200"), Decimal("23200"), Decimal("2320")),
    ],
)
def test_bracket_boundary_exact(
    fs: FilingStatus, std_ded: Decimal, first_bracket_top: Decimal, expected_tax: Decimal
) -> None:
    """Income at exact first bracket boundary for each filing status."""
    wages = first_bracket_top + std_ded
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=fs,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=wages, federal_withheld=expected_tax)],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == first_bracket_top
    assert run.output.federal_tax == expected_tax


@pytest.mark.parametrize("fs", list(FilingStatus))
def test_zero_income_all_filing_statuses(fs: FilingStatus) -> None:
    """Zero income should produce zero tax for all filing statuses."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=fs,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="None", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_trace_explanations_include_form_line() -> None:
    """Trace explanations should include IRS form line references."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    wages_trace = next(t for t in run.trace if t.rule_id == "fed.2024.gross_income.wages")
    assert "1040 Line 1a" in wages_trace.explanation

    deduction_trace = next(t for t in run.trace if t.rule_id == "fed.2024.standard_deduction")
    assert "1040 Line 13" in deduction_trace.explanation

    tax_trace = next(t for t in run.trace if t.rule_id == "fed.2024.tax.brackets")
    assert "1040 Line 16" in tax_trace.explanation


def test_se_tax_deduction_passthrough() -> None:
    """SE tax deduction is a pass-through (user provides the deductible half)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(self_employment_tax_deduction=Decimal("3500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("56500.00")


def test_agi_floors_at_zero() -> None:
    """AGI cannot go negative — max(gross - adj, 0) floors at zero."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(
            ira_contributions=Decimal("7000"),
            hsa_contributions=Decimal("4150"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("5000"), federal_withheld=Decimal("500"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("0.00")
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_ira_capped_at_7000() -> None:
    """IRA contributions capped at $7,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(ira_contributions=Decimal("10000")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("53000.00")


def test_multiple_adjustments_stack() -> None:
    """Multiple adjustments should all reduce AGI."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
            ira_contributions=Decimal("7000"),
            hsa_contributions=Decimal("4150"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.adjustments_total == Decimal("13950.00")
    assert run.output.agi == Decimal("66050.00")


def test_mixed_income_household() -> None:
    """Full household: W-2 + 1099-NEC + 1099-INT + 1099-DIV + 1099-B + SSA + other + adjustments."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        other_income=Decimal("500"),
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="Army", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
                form_1099_necs=[Form1099NECData(payer_name="Client", nonemployee_compensation=Decimal("10000"))],
                form_1099_ints=[Form1099INTData(payer_name="Bank", interest_income=Decimal("500"))],
                form_1099_divs=[Form1099DIVData(payer_name="Broker", ordinary_dividends=Decimal("1200"))],
                form_1099_bs=[Form1099BData(description="Stock", proceeds=Decimal("5000"), cost_basis=Decimal("3000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.gross_income > Decimal("85000")
    assert run.output.adjustments_total == Decimal("2800.00")
    assert run.output.agi == run.output.gross_income - Decimal("2800.00")
    assert run.output.federal_tax > Decimal("0")
