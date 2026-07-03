# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for Milestone 9: Multi-Year Support.

Covers: dynamic rule pack loading, 2023 federal calculations,
2023 GA state calculations, year-over-year comparison.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.database import init_db, list_all_return_runs
from main import app

FED_2023 = RulePack.load(Path("rule_packs/federal/2023"))
FED_2024 = RulePack.load(Path("rule_packs/federal/2024"))
GA_2023 = RulePack.load(Path("rule_packs/state/GA/2023"))

CSRF = "test-csrf-token"


# ─── Pack loading ─────────────────────────────────────────────


def test_2023_pack_loads_correct_year() -> None:
    assert FED_2023.tax_year == 2023
    assert FED_2023.jurisdiction == "federal"
    assert len(FED_2023.rules) == 132


def test_2024_pack_loads_correct_year() -> None:
    assert FED_2024.tax_year == 2024
    assert FED_2024.jurisdiction == "federal"
    assert len(FED_2024.rules) == 132


# ─── 2023 Federal golden tests ───────────────────────────────


def test_2023_single_w2() -> None:
    """Single filer, $50k wages, 2023.

    Standard deduction: $13,850. Taxable: $36,150.
    Tax: 10% on $11,000 = $1,100 + 12% on $25,150 = $3,018 = $4,118
    Refund: $6,000 - $4,118 = $1,882
    """
    inp = TaxReturnInput(
        tax_year=2023,
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
    run = CalculationEngine(FED_2023, inp).run()

    assert run.output.standard_deduction == Decimal("13850")
    assert run.output.taxable_income == Decimal("36150")
    assert run.output.federal_tax == Decimal("4118")
    assert run.output.refund_or_owed == Decimal("1882")


def test_2023_mfj_w2() -> None:
    """MFJ, $85k wages, 2023.

    Standard deduction: $27,700. Taxable: $57,300.
    Tax: 10% on $22,000 = $2,200 + 12% on $35,300 = $4,236 = $6,436
    Refund: $12,000 - $6,436 = $5,564
    """
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp).run()

    assert run.output.standard_deduction == Decimal("27700")
    assert run.output.taxable_income == Decimal("57300")
    assert run.output.federal_tax == Decimal("6436")
    assert run.output.refund_or_owed == Decimal("5564")


def test_2023_differs_from_2024() -> None:
    """Same inputs should produce different results for 2023 vs 2024."""
    inp_2023 = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    inp_2024 = inp_2023.model_copy(update={"tax_year": 2024})

    run_2023 = CalculationEngine(FED_2023, inp_2023).run()
    run_2024 = CalculationEngine(FED_2024, inp_2024).run()

    # Different standard deductions
    assert run_2023.output.standard_deduction == Decimal("13850")
    assert run_2024.output.standard_deduction == Decimal("14600")

    # Different taxable income and tax
    assert run_2023.output.taxable_income != run_2024.output.taxable_income
    assert run_2023.output.federal_tax != run_2024.output.federal_tax


def test_2023_zero_income() -> None:
    """Zero income produces zero tax for 2023."""
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp).run()
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_2023_trace_completeness() -> None:
    """Every rule in the 2023 pack should appear in the trace."""
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp).run()
    traced_ids = {t.rule_id for t in run.trace}
    expected = {
        "fed.2023.gross_income.wages",
        "fed.2023.gross_income.interest",
        "fed.2023.gross_income.dividends",
        "fed.2023.gross_income.capital_gains",
        "fed.2023.gross_income.capital_loss_limit",
        "fed.2023.gross_income.capital_gains_limited",
        "fed.2023.gross_income.self_employment",
        "fed.2023.gross_income.other",
        "fed.2023.gross_income.ss_half_benefits",
        "fed.2023.gross_income.ss_provisional",
        "fed.2023.gross_income.ss_base_threshold",
        "fed.2023.gross_income.ss_upper_threshold",
        "fed.2023.gross_income.ss_lower_calc",
        "fed.2023.gross_income.ss_upper_calc",
        "fed.2023.gross_income.ss_max_taxable",
        "fed.2023.gross_income.social_security",
        "fed.2023.gross_income.total",
        "fed.2023.adjustments.hsa_limit",
        "fed.2023.adjustments.student_loan",
        "fed.2023.adjustments.educator",
        "fed.2023.adjustments.hsa",
        "fed.2023.adjustments.ira",
        "fed.2023.adjustments.se_tax",
        "fed.2023.adjustments.total",
        "fed.2023.agi.total",
        "fed.2023.standard_deduction",
        "fed.2023.itemized.salt_cap",
        "fed.2023.itemized.salt_total",
        "fed.2023.itemized.medical_floor",
        "fed.2023.itemized.medical",
        "fed.2023.itemized.mortgage_interest",
        "fed.2023.itemized.charitable_agi_cap",
        "fed.2023.itemized.charitable_noncash_agi_cap",
        "fed.2023.itemized.charitable",
        "fed.2023.itemized.total",
        "fed.2023.deductions.applied",
        "fed.2023.taxable_income",
        "fed.2023.income.long_term_gains",
        "fed.2023.income.short_term_gains",
        "fed.2023.income.net_capital_gain",
        "fed.2023.income.preferential",
        "fed.2023.income.ordinary",
        "fed.2023.ltcg.threshold_0",
        "fed.2023.ltcg.threshold_15",
        "fed.2023.tax.ordinary",
        "fed.2023.tax.ltcg",
        "fed.2023.tax.total_before_credits",
        "fed.2023.se.has_nec",
        "fed.2023.se.net_earnings_raw",
        "fed.2023.se.applies",
        "fed.2023.se.net_earnings",
        "fed.2023.se.ss_taxable",
        "fed.2023.se.ss_tax",
        "fed.2023.se.medicare_tax",
        "fed.2023.se.total",
        "fed.2023.se.deduction",
        "fed.2023.tax.total_liability",
        "fed.2023.credits.eic.num_children",
        "fed.2023.credits.eic.earned_income",
        "fed.2023.credits.eic.max_credit",
        "fed.2023.credits.eic.phase_in_rate",
        "fed.2023.credits.eic.phase_out_start",
        "fed.2023.credits.eic.phase_out_rate",
        "fed.2023.credits.eic.phase_in_amount",
        "fed.2023.credits.eic.phase_out_amount",
        "fed.2023.credits.eic.tentative",
        "fed.2023.credits.eic.investment_income",
        "fed.2023.credits.eic.eligible",
        "fed.2023.credits.eic.final",
        "fed.2023.credits.edu.phaseout_lower",
        "fed.2023.credits.edu.phaseout_upper",
        "fed.2023.credits.edu.eligible",
        "fed.2023.credits.edu.ratio",
        "fed.2023.credits.edu.aotc_tentative",
        "fed.2023.credits.edu.aotc",
        "fed.2023.credits.edu.aotc_refundable",
        "fed.2023.credits.edu.aotc_nonrefundable",
        "fed.2023.credits.edu.llc_tentative",
        "fed.2023.credits.edu.llc",
        "fed.2023.credits.care.spouse_required",
        "fed.2023.credits.care.persons_capped",
        "fed.2023.credits.care.dollar_cap",
        "fed.2023.credits.care.earned_cap",
        "fed.2023.credits.care.eligible_expenses",
        "fed.2023.credits.care.agi_steps",
        "fed.2023.credits.care.rate",
        "fed.2023.credits.care.final",
        "fed.2023.niit.threshold",
        "fed.2023.niit.investment_income",
        "fed.2023.niit.magi_excess",
        "fed.2023.niit.final",
        "fed.2023.tax.other_taxes",
        "fed.2023.military.combat_pay_exclusion",
        "fed.2023.military.officer_cap",
        "fed.2023.military.officer_excess",
        "fed.2023.adjustments.military_moving",
        "fed.2023.adjustments.reservist_travel",
        "fed.2023.credits.eic.earned_income_elected",
        "fed.2023.credits.eic.phase_in_elected",
        "fed.2023.credits.eic.phase_out_elected",
        "fed.2023.credits.eic.tentative_elected",
        "fed.2023.deductions.additional_rate",
        "fed.2023.deductions.additional_standard",
        "fed.2023.deductions.standard_total",
        "fed.2023.credits.odc.base",
        "fed.2023.credits.ctc.combined",
        "fed.2023.credits.other_nonrefundable",
        "fed.2023.credits.ctc.tax_limit",
        "fed.2023.credits.actc.unused",
        "fed.2023.credits.actc.cap",
        "fed.2023.credits.actc.earned_income",
        "fed.2023.credits.actc.phase_in",
        "fed.2023.credits.actc.final",
        "fed.2023.addl_medicare.threshold",
        "fed.2023.addl_medicare.wage_excess",
        "fed.2023.addl_medicare.se_threshold",
        "fed.2023.addl_medicare.se_excess",
        "fed.2023.addl_medicare.final",
        "fed.2023.addl_medicare.regular_withholding",
        "fed.2023.addl_medicare.withholding",
        "fed.2023.tax.brackets",
        "fed.2023.credits.ctc.base",
        "fed.2023.credits.ctc.threshold",
        "fed.2023.credits.ctc.phaseout_units",
        "fed.2023.credits.ctc.phaseout",
        "fed.2023.credits.ctc.final",
        "fed.2023.credits.total",
        "fed.2023.tax.after_credits",
        "fed.2023.total_withholding",
        "fed.2023.estimated_payments",
        "fed.2023.total_payments",
        "fed.2023.refund_or_owed",
    }
    assert expected == traced_ids


# ─── 2023 GA state test ──────────────────────────────────────


def test_2023_ga_state_tax() -> None:
    """GA 2023: $85k MFJ, GA graduated brackets."""
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X",
                        wages=Decimal("85000"),
                        federal_withheld=Decimal("12000"),
                        state="GA",
                        state_withheld=Decimal("2000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp, state_packs={"GA": GA_2023}).run()
    assert run.state_outputs, "Expected GA output"
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    assert ga.state_agi == run.output.agi
    assert ga.state_taxable_income >= 0
    # GA 2023 uses graduated brackets (top 5.75%), not flat 5.39%
    assert ga.state_tax > 0


# ─── Route integration tests ─────────────────────────────────


@pytest.fixture()
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def test_calculate_with_2023(_ensure_db: None) -> None:
    """Submit a calculation using tax year 2023 via the form."""
    client = _client()
    form = {
        "csrf_token": CSRF,
        "tax_year": "2023",
        "filing_status": "single",
        "p_first": "Test",
        "p_last": "User",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "50000",
        "p_w2_0_federal_withheld": "6000",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303

    runs = list_all_return_runs()
    assert runs
    # Verify at least one run used 2023 (don't rely on ordering)
    assert any(r["tax_year"] == 2023 for r in runs)


def test_calculate_form_shows_year_dropdown(_ensure_db: None) -> None:
    """The calculate form should show available years as a dropdown."""
    client = _client()
    r = client.get("/calculate")
    assert r.status_code == 200
    assert "2023" in r.text
    assert "2024" in r.text
    assert "<select" in r.text
