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


def test_single_w2_mfj() -> None:
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


def test_single_filing() -> None:
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


def test_with_capital_gains() -> None:
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


def test_zero_income() -> None:
    """Zero income should produce zero tax."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="No",
                last_name="Income",
                w2s=[
                    W2Data(employer_name="None", wages=Decimal("0"), federal_withheld=Decimal("0"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_trace_contains_all_rules() -> None:
    """Every rule in the pack should appear in the trace."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Trace",
                last_name="Test",
                w2s=[
                    W2Data(
                        employer_name="Corp",
                        wages=Decimal("100000"),
                        federal_withheld=Decimal("15000"),
                    )
                ],
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
    assert expected == traced_ids


def test_immutable_run_has_snapshot_and_metadata() -> None:
    """ReturnRun must contain a frozen input snapshot + audit metadata."""
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Snap",
                last_name="Shot",
                w2s=[
                    W2Data(
                        employer_name="Corp",
                        wages=Decimal("75000"),
                        federal_withheld=Decimal("10000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.input_snapshot.taxpayers[0].w2s[0].wages == Decimal("75000")
    assert run.rule_pack_version == "1.5.0"
    assert len(run.rule_pack_checksum) == 64  # SHA-256 hex


def test_high_income_hits_multiple_brackets() -> None:
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
                w2s=[
                    W2Data(
                        employer_name="BigCo",
                        wages=Decimal("300000"),
                        federal_withheld=Decimal("80000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inputs).run()

    assert run.output.taxable_income == Decimal("285400")
    assert run.output.federal_tax == Decimal("70265")
