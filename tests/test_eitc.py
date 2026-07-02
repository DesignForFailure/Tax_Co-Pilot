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

"""Earned Income Tax Credit golden tests (Milestone 19).

Hand-verified against IRC §32 and Pub 596: phase-in capped at the
maximum credit, phaseout on the greater of AGI or earned income, the
investment income limit, MFS ineligibility, SE earned income via
Worksheet B, the 3-child parameter cap, and refundability (EIC joins
payments on 1040 line 27 rather than the nonrefundable credit total).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099INTData,
    Form1099NECData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.form_mapper import map_return_run

FED_2024 = RulePack.load(Path("rule_packs/federal/2024"))
FED_2023 = RulePack.load(Path("rule_packs/federal/2023"))
FED_2025 = RulePack.load(Path("rule_packs/federal/2025"))


def _run(
    pack: RulePack,
    filing_status: FilingStatus,
    wages: str | None = None,
    children: int = 0,
    nec: str | None = None,
    interest: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=filing_status,
        qualifying_children=children,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))] if wages else [],
                form_1099_necs=(
                    [Form1099NECData(payer_name="Client", nonemployee_compensation=Decimal(nec))]
                    if nec
                    else []
                ),
                form_1099_ints=(
                    [Form1099INTData(payer_name="Bank", interest_income=Decimal(interest))]
                    if interest
                    else []
                ),
            )
        ],
    )
    engine = CalculationEngine(pack, inp)
    return engine, engine.run()


def test_single_one_child_phase_in_reaches_max() -> None:
    """Single, 1 child, $15k wages: 15,000 × 34% caps at the $4,213 max."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "15000", children=1)
    assert e.resolved["fed.2024.credits.eic.phase_in_amount"] == Decimal("4213")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("4213")
    assert run.output.earned_income_credit == Decimal("4213")


def test_single_one_child_partial_phase_in() -> None:
    """Single, 1 child, $10k wages: still phasing in — 10,000 × 34% = 3,400."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "10000", children=1)
    assert e.resolved["fed.2024.credits.eic.phase_in_amount"] == Decimal("3400.00")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("3400")


def test_mfj_two_children_receives_max() -> None:
    """MFJ, 2 children, $25k wages: AGI below the $29,640 MFJ threshold."""
    e, _ = _run(FED_2024, FilingStatus.MFJ, "25000", children=2)
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("6960")


def test_single_no_children_above_phaseout() -> None:
    """Single, 0 children, $60k wages: fully phased out."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "60000", children=0)
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("0")


def test_phaseout_math_exact() -> None:
    """Single, 1 child, $30k: 4,213 − (30,000 − 22,720) × 15.98% → 3,050."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "30000", children=1)
    assert e.resolved["fed.2024.credits.eic.phase_out_amount"] == Decimal("1163.34")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("3050")


def test_phaseout_uses_greater_of_agi_or_earned_income() -> None:
    """$20k wages + $11k interest: phaseout runs on AGI 31,000, not 20,000."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "20000", children=1, interest="11000")
    assert run.output.agi == Decimal("31000.00")
    assert e.resolved["fed.2024.credits.eic.phase_out_amount"] == Decimal("1323.14")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("2890")


def test_investment_income_over_limit_disqualifies() -> None:
    """$12k interest exceeds the 2024 $11,600 limit → credit is zero."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "15000", children=1, interest="12000")
    assert e.resolved["fed.2024.credits.eic.investment_income"] == Decimal("12000.00")
    assert e.resolved["fed.2024.credits.eic.eligible"] == Decimal("0.00")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("0")
    assert run.output.earned_income_credit == Decimal("0")


def test_investment_income_at_limit_still_eligible() -> None:
    """Exactly $11,600 of investment income is allowed (limit is 'more than')."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "15000", children=1, interest="11600")
    assert e.resolved["fed.2024.credits.eic.eligible"] == Decimal("1.00")
    assert e.resolved["fed.2024.credits.eic.final"] > Decimal("0")


def test_mfs_is_ineligible() -> None:
    """MFS filers cannot claim the EITC (IRC §32(d))."""
    e, _ = _run(FED_2024, FilingStatus.MFS, "15000", children=1)
    assert e.resolved["fed.2024.credits.eic.max_credit"] == Decimal("0")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("0")


def test_se_income_counts_as_earned_income() -> None:
    """$20k NEC, 1 child: earned income = 20,000 − 1,413 half-SE-tax deduction."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, children=1, nec="20000")
    assert e.resolved["fed.2024.credits.eic.earned_income"] == Decimal("18587.00")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("4213")


def test_children_capped_at_three_for_parameters() -> None:
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "15000", children=5)
    assert e.resolved["fed.2024.credits.eic.num_children"] == Decimal("3")
    assert e.resolved["fed.2024.credits.eic.max_credit"] == Decimal("7830")


def test_eic_is_refundable_via_payments() -> None:
    """CTC zeroes the income tax; the EIC still pays out as a refund."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "15000", children=1)
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("0")
    assert e.resolved["fed.2024.total_payments"] == Decimal("4213.00")
    assert run.output.refund_or_owed == Decimal("4213")


def test_form_mapper_line_27_and_consistency() -> None:
    _, run = _run(FED_2024, FilingStatus.SINGLE, "15000", children=1)
    pkt = map_return_run(run)
    assert pkt.form_1040.line_27 == Decimal("4213")
    assert pkt.form_1040.line_33 == Decimal("4213.00")
    assert pkt.form_1040.line_34 == Decimal("4213.00")
    assert pkt.consistency_errors == []


def test_no_children_small_credit_works() -> None:
    """Single, 0 children, $8k wages: 8,000 × 7.65% = 612 (under the 632 max)."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "8000", children=0)
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("612")


def test_high_earner_gets_nothing_regardless_of_children() -> None:
    e, run = _run(FED_2024, FilingStatus.MFJ, "120000", children=3)
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("0")
    assert run.output.earned_income_credit == Decimal("0")


@pytest.mark.parametrize(
    ("pack", "yr", "max_1_child", "inv_limit_over"),
    [
        (FED_2023, 2023, "3995", "11500"),
        (FED_2024, 2024, "4213", "12000"),
        (FED_2025, 2025, "4328", "12500"),
    ],
)
def test_year_parameters(pack: RulePack, yr: int, max_1_child: str, inv_limit_over: str) -> None:
    """Per-year maximum credit and investment income limit."""
    e, _ = _run(pack, FilingStatus.SINGLE, "15000", children=1)
    assert e.resolved[f"fed.{yr}.credits.eic.max_credit"] == Decimal(max_1_child)
    assert e.resolved[f"fed.{yr}.credits.eic.final"] == Decimal(max_1_child)

    e, _ = _run(pack, FilingStatus.SINGLE, "15000", children=1, interest=inv_limit_over)
    assert e.resolved[f"fed.{yr}.credits.eic.final"] == Decimal("0")
