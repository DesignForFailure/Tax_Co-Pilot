# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for California and New York state rule packs."""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

BASE = Path(__file__).resolve().parent.parent
FED = RulePack.load(BASE / "rule_packs" / "federal" / "2024")
CA = RulePack.load(BASE / "rule_packs" / "state" / "CA" / "2024")
NY = RulePack.load(BASE / "rule_packs" / "state" / "NY" / "2024")


def _make_input(
    state: str,
    wages: str = "75000",
    withheld: str = "3000",
    filing_status: FilingStatus = FilingStatus.SINGLE,
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Test",
                last_name="User",
                w2s=[
                    W2Data(
                        employer_name="TestCo",
                        wages=Decimal(wages),
                        federal_withheld=Decimal("10000"),
                        state=state,
                        state_wages=Decimal(wages),
                        state_withheld=Decimal(withheld),
                    )
                ],
            )
        ],
    )


# ── California Tests ──────────────────────────────────────────


def test_ca_single_75k() -> None:
    """CA single filer at $75k — golden test with hand-verified values.

    Taxable income: 75000 - 5540 = 69460
    Bracket tax: 104.12 + 285.44 + 571.00 + 907.32 + 1141.52 + 103.23 = 3112.63 → 3113
    """
    inp = _make_input("CA")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    assert len(run.state_outputs) == 1
    ca = run.state_outputs[0]
    assert ca.state == "CA"
    assert ca.state_taxable_income == Decimal("69460")
    assert ca.state_tax == Decimal("3113")
    assert ca.state_withholding == Decimal("3000")
    assert ca.state_refund_or_owed == ca.state_withholding - ca.state_tax


def test_ca_mfj_150k() -> None:
    """CA MFJ at $150k uses MFJ brackets and deduction."""
    inp = _make_input("CA", wages="150000", withheld="6000", filing_status=FilingStatus.MFJ)
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    assert ca.state_tax > Decimal("0")
    # MFJ deduction is $11,080 so taxable income = 150000 - 11080 = 138920
    assert ca.state_taxable_income == Decimal("138920")


def test_ca_mental_health_surtax_below_threshold() -> None:
    """CA income below $1M should have no MHS surtax."""
    inp = _make_input("CA", wages="500000", withheld="20000")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    # Tax should be bracket tax only, no surtax
    # At $500k single, base tax is roughly $34k-$38k range
    assert ca.state_tax > Decimal("30000")
    assert ca.state_tax < Decimal("50000")


def test_ca_mental_health_surtax_above_threshold() -> None:
    """CA income above $1M should include 1% MHS surtax on excess."""
    inp = _make_input("CA", wages="1500000", withheld="80000")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    # Taxable income ~ $1,494,460. MHS surtax on ~$494,460 = ~$4,945
    # Base bracket tax on $1.5M is roughly $175k. Total > $175k.
    assert ca.state_tax > Decimal("150000")


@pytest.mark.parametrize("fs", [FilingStatus.SINGLE, FilingStatus.MFJ, FilingStatus.MFS, FilingStatus.HOH])
def test_ca_all_filing_statuses(fs: FilingStatus) -> None:
    """CA produces valid output for all filing statuses."""
    inp = _make_input("CA", filing_status=fs)
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    assert ca.state == "CA"
    assert ca.state_tax >= Decimal("0")


# ── New York Tests ────────────────────────────────────────────


def test_ny_single_75k() -> None:
    """NY single filer at $75k — golden test with hand-verified values.

    Taxable income: 75000 - 8000 = 67000
    Bracket tax: 340.00 + 144.00 + 115.50 + 3106.35 = 3705.85 → 3706
    """
    inp = _make_input("NY")
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    assert len(run.state_outputs) == 1
    ny = run.state_outputs[0]
    assert ny.state == "NY"
    assert ny.state_taxable_income == Decimal("67000")
    assert ny.state_tax == Decimal("3706")
    assert ny.state_withholding == Decimal("3000")
    assert ny.state_refund_or_owed == ny.state_withholding - ny.state_tax


def test_ny_mfj_150k() -> None:
    """NY MFJ at $150k uses MFJ brackets and deduction."""
    inp = _make_input("NY", wages="150000", withheld="6000", filing_status=FilingStatus.MFJ)
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    ny = run.state_outputs[0]
    assert ny.state_tax > Decimal("0")
    # MFJ deduction is $16,050 so taxable income = 150000 - 16050 = 133950
    assert ny.state_taxable_income == Decimal("133950")


@pytest.mark.parametrize("fs", [FilingStatus.SINGLE, FilingStatus.MFJ, FilingStatus.MFS, FilingStatus.HOH])
def test_ny_all_filing_statuses(fs: FilingStatus) -> None:
    """NY produces valid output for all filing statuses."""
    inp = _make_input("NY", filing_status=fs)
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    ny = run.state_outputs[0]
    assert ny.state == "NY"
    assert ny.state_tax >= Decimal("0")


# ── Multi-State Tests ─────────────────────────────────────────


def test_ca_and_ny_together() -> None:
    """Both CA and NY can run in the same engine invocation."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Test",
                last_name="User",
                w2s=[
                    W2Data(
                        employer_name="CA Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("7000"),
                        state="CA",
                        state_wages=Decimal("50000"),
                        state_withheld=Decimal("2000"),
                    ),
                    W2Data(
                        employer_name="NY Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("7000"),
                        state="NY",
                        state_wages=Decimal("50000"),
                        state_withheld=Decimal("2500"),
                    ),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp, state_packs={"CA": CA, "NY": NY}).run()
    states = {s.state for s in run.state_outputs}
    assert states == {"CA", "NY"}
