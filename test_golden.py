"""Golden tests for the Tax Copilot calculation engine.

These tests verify known-correct tax computations against hand-calculated
results for the embedded 2024 federal bracket table.

Security/QA intent:
- Ensure deterministic outputs for the same inputs.
- Ensure trace completeness and audit metadata (checksum/version).
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


def test_single_w2_mfj():
    """Single W-2, MFJ filing.

    Wages: $85,000. Withheld: $12,000.
    Standard deduction (MFJ 2024): $29,200
    Taxable income: $55,800
    Tax: 10% on $23,200 = $2,320 + 12% on $32,600 = $3,912 → $6,232
    Refund: $12,000 - $6,232 = $5,768
    """
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Test",
                last_name="User",
                w2s=[
                    W2Data(
                        employer_name="Acme Corp",
                        wages=Decimal("85000"),
                        federal_withheld=Decimal("12000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.gross_income == Decimal("85000.00")
    assert run.output.agi == Decimal("85000.00")
    assert run.output.standard_deduction == Decimal("29200")
    assert run.output.taxable_income == Decimal("55800")
    assert run.output.federal_tax == Decimal("6232")
    assert run.output.total_withholding == Decimal("12000.00")
    assert run.output.refund_or_owed == Decimal("5768")
    assert len(run.trace) > 0


def test_single_filing():
    """Single filing, $50k wages.

    Standard deduction: $14,600. Taxable: $35,400.
    Tax: 10% on $11,600 = $1,160 + 12% on $23,800 = $2,856 → $4,016
    """
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Solo",
                last_name="Filer",
                w2s=[
                    W2Data(
                        employer_name="Solo Inc",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("6000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.taxable_income == Decimal("35400")
    assert run.output.federal_tax == Decimal("4016")
    assert run.output.refund_or_owed == Decimal("1984")


def test_with_capital_gains():
    """W-2 + crypto gain. Wages $85k + $700 net gain. MFJ.

    Gross: $85,700. Taxable: $56,500.
    Tax: 10% on $23,200 = $2,320 + 12% on $33,300 = $3,996 → $6,316
    """
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Crypto",
                last_name="Trader",
                w2s=[
                    W2Data(
                        employer_name="Day Job",
                        wages=Decimal("85000"),
                        federal_withheld=Decimal("12000"),
                    )
                ],
                form_1099_bs=[
                    Form1099BData(
                        description="BTC sale",
                        proceeds=Decimal("900"),
                        cost_basis=Decimal("200"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.gross_income == Decimal("85700.00")
    assert run.output.taxable_income == Decimal("56500")
    assert run.output.federal_tax == Decimal("6316")


def test_zero_income():
    """Zero income should produce zero tax."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="No",
                last_name="Income",
                w2s=[W2Data(employer_name="None", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_trace_contains_all_rules():
    """Every rule in the pack should appear in the trace."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Trace",
                last_name="Test",
                w2s=[W2Data(employer_name="Corp", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()
    traced_ids = {t.rule_id for t in run.trace}

    expected = {
        "fed.2024.gross_income.wages",
        "fed.2024.gross_income.interest",
        "fed.2024.gross_income.dividends",
        "fed.2024.gross_income.capital_gains",
        "fed.2024.gross_income.total",
        "fed.2024.agi.total",
        "fed.2024.standard_deduction",
        "fed.2024.taxable_income",
        "fed.2024.tax.brackets",
        "fed.2024.total_withholding",
        "fed.2024.refund_or_owed",
    }
    assert expected == traced_ids


def test_immutable_run_has_snapshot_and_metadata():
    """ReturnRun must contain a frozen input snapshot + audit metadata."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Snap",
                last_name="Shot",
                w2s=[W2Data(employer_name="Corp", wages=Decimal("75000"), federal_withheld=Decimal("10000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.input_snapshot.taxpayers[0].w2s[0].wages == Decimal("75000")
    assert run.rule_pack_version == "1.0.0"
    assert len(run.rule_pack_checksum) == 64  # SHA-256 hex


def test_high_income_hits_multiple_brackets():
    """$300k income, single. Hits 6 brackets.

    Standard deduction: $14,600. Taxable: $285,400.
    Total: $70,264.75 → $70,265 (rounded)
    """
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="High",
                last_name="Earner",
                w2s=[W2Data(employer_name="BigCo", wages=Decimal("300000"), federal_withheld=Decimal("80000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.taxable_income == Decimal("285400")
    assert run.output.federal_tax == Decimal("70265")
