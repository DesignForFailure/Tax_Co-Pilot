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

"""Tax Copilot — Golden Tests (Milestones 1–5).

Covers:
  M1: Federal bracket calc, trace completeness
  M2: Two-person filing, multiple W-2s, 1099s, CSV import
  M3: What-If (MFJ vs MFS comparison)
  M4: Georgia state tax computation
  M5: Audit export (JSON + HTML generation)

Note:
- State calculations require passing state packs into CalculationEngine.
"""

import json
import tempfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.engine.whatif import WhatIfEngine
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Form1099INTData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.audit_export import export_json, generate_audit_html
from app.services.csv_import import import_csv

FED = RulePack.load(Path("rule_packs/federal/2024"))
GA = RulePack.load(Path("rule_packs/state/GA/2024"))


# ═══════════════════════════════════════════════════════════════
# M1: FEDERAL BASICS
# ═══════════════════════════════════════════════════════════════


def test_single_w2_mfj() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000")
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("85000.00")
    assert run.output.standard_deduction == Decimal("29200")
    assert run.output.taxable_income == Decimal("55800")
    assert run.output.federal_tax == Decimal("6232")
    assert run.output.refund_or_owed == Decimal("5768")


def test_trace_completeness() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X",
                        wages=Decimal("100000"),
                        federal_withheld=Decimal("15000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    ids = {t.rule_id for t in run.trace}
    expected = {
        "fed.2024.gross_income.wages",
        "fed.2024.gross_income.interest",
        "fed.2024.gross_income.dividends",
        "fed.2024.gross_income.capital_gains",
        "fed.2024.gross_income.capital_loss_limit",
        "fed.2024.gross_income.capital_gains_limited",
        "fed.2024.gross_income.self_employment",
        "fed.2024.gross_income.other",
        "fed.2024.gross_income.ss_half_benefits",
        "fed.2024.gross_income.ss_provisional",
        "fed.2024.gross_income.ss_base_threshold",
        "fed.2024.gross_income.ss_upper_threshold",
        "fed.2024.gross_income.ss_lower_calc",
        "fed.2024.gross_income.ss_upper_calc",
        "fed.2024.gross_income.ss_max_taxable",
        "fed.2024.gross_income.social_security",
        "fed.2024.gross_income.total",
        "fed.2024.adjustments.hsa_limit",
        "fed.2024.adjustments.student_loan",
        "fed.2024.adjustments.educator",
        "fed.2024.adjustments.hsa",
        "fed.2024.adjustments.ira",
        "fed.2024.adjustments.se_tax",
        "fed.2024.adjustments.total",
        "fed.2024.agi.total",
        "fed.2024.standard_deduction",
        "fed.2024.itemized.salt_cap",
        "fed.2024.itemized.salt_total",
        "fed.2024.itemized.medical_floor",
        "fed.2024.itemized.medical",
        "fed.2024.itemized.mortgage_interest",
        "fed.2024.itemized.charitable_agi_cap",
        "fed.2024.itemized.charitable_noncash_agi_cap",
        "fed.2024.itemized.charitable",
        "fed.2024.itemized.total",
        "fed.2024.deductions.applied",
        "fed.2024.taxable_income",
        "fed.2024.income.long_term_gains",
        "fed.2024.income.short_term_gains",
        "fed.2024.income.net_capital_gain",
        "fed.2024.income.preferential",
        "fed.2024.income.ordinary",
        "fed.2024.ltcg.threshold_0",
        "fed.2024.ltcg.threshold_15",
        "fed.2024.tax.ordinary",
        "fed.2024.tax.ltcg",
        "fed.2024.tax.total_before_credits",
        "fed.2024.se.has_nec",
        "fed.2024.se.net_earnings_raw",
        "fed.2024.se.applies",
        "fed.2024.se.net_earnings",
        "fed.2024.se.ss_taxable",
        "fed.2024.se.ss_tax",
        "fed.2024.se.medicare_tax",
        "fed.2024.se.total",
        "fed.2024.se.deduction",
        "fed.2024.tax.total_liability",
        "fed.2024.credits.eic.num_children",
        "fed.2024.credits.eic.earned_income",
        "fed.2024.credits.eic.max_credit",
        "fed.2024.credits.eic.phase_in_rate",
        "fed.2024.credits.eic.phase_out_start",
        "fed.2024.credits.eic.phase_out_rate",
        "fed.2024.credits.eic.phase_in_amount",
        "fed.2024.credits.eic.phase_out_amount",
        "fed.2024.credits.eic.tentative",
        "fed.2024.credits.eic.investment_income",
        "fed.2024.credits.eic.eligible",
        "fed.2024.credits.eic.final",
        "fed.2024.credits.edu.phaseout_lower",
        "fed.2024.credits.edu.phaseout_upper",
        "fed.2024.credits.edu.eligible",
        "fed.2024.credits.edu.ratio",
        "fed.2024.credits.edu.aotc_tentative",
        "fed.2024.credits.edu.aotc",
        "fed.2024.credits.edu.aotc_refundable",
        "fed.2024.credits.edu.aotc_nonrefundable",
        "fed.2024.credits.edu.llc_tentative",
        "fed.2024.credits.edu.llc",
        "fed.2024.credits.care.spouse_required",
        "fed.2024.credits.care.persons_capped",
        "fed.2024.credits.care.dollar_cap",
        "fed.2024.credits.care.earned_cap",
        "fed.2024.credits.care.eligible_expenses",
        "fed.2024.credits.care.agi_steps",
        "fed.2024.credits.care.rate",
        "fed.2024.credits.care.final",
        "fed.2024.niit.threshold",
        "fed.2024.niit.investment_income",
        "fed.2024.niit.magi_excess",
        "fed.2024.niit.final",
        "fed.2024.tax.other_taxes",
        "fed.2024.tax.brackets",
        "fed.2024.credits.ctc.base",
        "fed.2024.credits.ctc.threshold",
        "fed.2024.credits.ctc.phaseout_units",
        "fed.2024.credits.ctc.phaseout",
        "fed.2024.credits.ctc.final",
        "fed.2024.credits.total",
        "fed.2024.tax.after_credits",
        "fed.2024.total_withholding",
        "fed.2024.estimated_payments",
        "fed.2024.total_payments",
        "fed.2024.refund_or_owed",
    }
    assert expected == ids


# ═══════════════════════════════════════════════════════════════
# M2: TWO-PERSON, MULTIPLE INCOME TYPES, CSV
# ═══════════════════════════════════════════════════════════════


def test_two_person_mfj() -> None:
    """Primary $85k + Spouse $35k = $120k combined. MFJ."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="John",
                last_name="Doe",
                w2s=[
                    W2Data(
                        employer_name="Army",
                        wages=Decimal("85000"),
                        federal_withheld=Decimal("12000"),
                    )
                ],
            ),
            Taxpayer(
                role=TaxpayerRole.SPOUSE,
                first_name="Jane",
                last_name="Doe",
                w2s=[
                    W2Data(
                        employer_name="Cafe",
                        wages=Decimal("35000"),
                        federal_withheld=Decimal("4000"),
                    )
                ],
            ),
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("120000.00")
    assert run.output.total_withholding == Decimal("16000.00")
    assert run.output.taxable_income == Decimal("90800")


def test_1099_income_mix() -> None:
    """W-2 + 1099-INT + 1099-DIV + 1099-B."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000")
                    )
                ],
                form_1099_ints=[Form1099INTData(payer_name="Bank", interest_income=Decimal("500"))],
                form_1099_divs=[
                    Form1099DIVData(payer_name="Broker", ordinary_dividends=Decimal("1200"))
                ],
                form_1099_bs=[
                    Form1099BData(
                        description="BTC", proceeds=Decimal("900"), cost_basis=Decimal("200")
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("82400.00")


def test_csv_import_w2() -> None:
    csv_text = """employer_name,wages,federal_withheld,state,state_withheld
US Army,85000,12000,TX,0
Walmart,25000,3000,GA,1500
"""
    records, errors = import_csv(csv_text, "W2")
    assert errors == []
    assert len(records) == 2
    assert isinstance(records[0], W2Data)
    assert records[0].employer_name == "US Army"
    assert records[0].wages == Decimal("85000.00")
    assert isinstance(records[1], W2Data)
    assert records[1].state == "GA"


def test_csv_import_1099b() -> None:
    csv_text = """description,proceeds,cost_basis,is_long_term
BTC sale,900,200,false
ETH sale,5000,3000,true
"""
    records, errors = import_csv(csv_text, "1099-B")
    assert errors == []
    assert len(records) == 2
    assert isinstance(records[0], Form1099BData)
    assert records[0].net_gain == Decimal("700.00")
    assert isinstance(records[1], Form1099BData)
    assert records[1].is_long_term is True


# ═══════════════════════════════════════════════════════════════
# M3: WHAT-IF ENGINE
# ═══════════════════════════════════════════════════════════════


def test_whatif_mfj_vs_mfs() -> None:
    base = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000")
                    )
                ],
            ),
            Taxpayer(
                role=TaxpayerRole.SPOUSE,
                first_name="C",
                last_name="D",
                w2s=[
                    W2Data(
                        employer_name="Y", wages=Decimal("35000"), federal_withheld=Decimal("4000")
                    )
                ],
            ),
        ],
    )
    comparison = WhatIfEngine(FED).compare_filing_status(base)

    assert comparison.scenario_a.filing_status == FilingStatus.MFJ
    assert comparison.scenario_b.filing_status == FilingStatus.MFS
    assert comparison.scenario_a.total_tax < comparison.scenario_b.total_tax
    assert comparison.recommendation == comparison.scenario_a.scenario_name
    assert comparison.savings > 0


def test_whatif_rejects_unallocated_household_fields() -> None:
    base = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        other_income=Decimal("1000"),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000")
                    )
                ],
            ),
            Taxpayer(
                role=TaxpayerRole.SPOUSE,
                first_name="C",
                last_name="D",
                w2s=[
                    W2Data(
                        employer_name="Y", wages=Decimal("35000"), federal_withheld=Decimal("4000")
                    )
                ],
            ),
        ],
    )

    with pytest.raises(ValueError, match="cannot safely allocate household-level"):
        WhatIfEngine(FED).compare_filing_status(base)


# ═══════════════════════════════════════════════════════════════
# M4: GEORGIA STATE (MVP)
# ═══════════════════════════════════════════════════════════════


def test_georgia_state_tax_flow() -> None:
    """Basic GA flow: starts from federal AGI, applies GA deduction/exemption, flat rate."""
    inp = TaxReturnInput(
        tax_year=2024,
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

    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()
    assert run.state_outputs, "Expected GA output"
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    # Sanity checks only (constants are embedded and may evolve):
    assert ga.state_agi == run.output.agi
    assert ga.state_taxable_income >= 0


# ═══════════════════════════════════════════════════════════════
# M5: AUDIT EXPORT
# ═══════════════════════════════════════════════════════════════


def test_audit_export_json_and_html() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000")
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "audit.json"
        export_json(run, out_path)
        data = json.loads(out_path.read_text(encoding="utf-8"))
        assert data["rule_pack_checksum"] == run.rule_pack_checksum

    html = generate_audit_html(run)
    assert "<!doctype html>" in html.lower()
    assert "audit report" in html.lower()
