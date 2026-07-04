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

"""Additional Medicare Tax golden tests (Milestone 27).

Hand-verified against Form 8959 / IRC §3101(b)(2): 0.9% of Medicare
wages and self-employment earnings above the statutory — never indexed —
thresholds ($200k single/HoH, $250k MFJ/QSS, $125k MFS), with the SE
threshold reduced (not below zero) by wages. Box 1 wages stand in for
Box 5; employer surtax withholding (Part IV) is unmodeled.
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

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}


def _run(
    year: int,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    nec: str | None = None,
    interest: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))],
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
    engine = CalculationEngine(FED[year], inp)
    return engine, engine.run()


def test_wages_above_threshold() -> None:
    """Single, $250k wages: 0.9% × $50k = $450, joining line 23."""
    e, run = _run(2024, "250000")
    assert e.resolved["fed.2024.addl_medicare.wage_excess"] == Decimal("50000.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("450")
    assert e.resolved["fed.2024.tax.other_taxes"] == Decimal("450")
    assert run.output.additional_medicare_tax == Decimal("450")


def test_mfj_threshold_250k() -> None:
    e, _ = _run(2024, "250000", FilingStatus.MFJ)
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("0")


def test_mfs_threshold_125k() -> None:
    e, _ = _run(2024, "150000", FilingStatus.MFS)
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("225")


def test_se_income_with_wage_offset() -> None:
    """$150k wages + $100k NEC: SE threshold $50k → 0.9% × $42,350 = $381."""
    e, _ = _run(2024, "150000", nec="100000")
    assert e.resolved["fed.2024.se.net_earnings"] == Decimal("92350.00")
    assert e.resolved["fed.2024.addl_medicare.se_threshold"] == Decimal("50000.00")
    assert e.resolved["fed.2024.addl_medicare.se_excess"] == Decimal("42350.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("381")


def test_wages_and_se_both_above() -> None:
    """$220k wages + $50k NEC: (20,000 + 46,175) × 0.9% = $595.58 → $596."""
    e, _ = _run(2024, "220000", nec="50000")
    assert e.resolved["fed.2024.addl_medicare.wage_excess"] == Decimal("20000.00")
    assert e.resolved["fed.2024.addl_medicare.se_threshold"] == Decimal("0.00")
    assert e.resolved["fed.2024.addl_medicare.se_excess"] == Decimal("46175.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("596")


def test_below_threshold_owes_nothing() -> None:
    e, run = _run(2024, "150000")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("0")
    assert run.output.additional_medicare_tax == Decimal("0")


def test_se_400_floor_gates_medicare_se_income() -> None:
    """NEC under $400 produces no Schedule SE earnings, so no SE surtax base."""
    e, _ = _run(2024, "250000", nec="300")
    assert e.resolved["fed.2024.se.net_earnings"] == Decimal("0.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("450")


@pytest.mark.parametrize("year", [2023, 2025])
def test_thresholds_are_statutory_across_years(year: int) -> None:
    """IRC §3101(b)(2) thresholds are not inflation-indexed."""
    e, _ = _run(year, "250000")
    assert e.resolved[f"fed.{year}.addl_medicare.threshold"] == Decimal("200000")
    assert e.resolved[f"fed.{year}.addl_medicare.final"] == Decimal("450")


def test_stacks_with_se_tax_and_niit_on_line_23() -> None:
    """All three Schedule 2 taxes aggregate into 1040 line 23."""
    e, run = _run(2024, "250000", nec="50000", interest="30000")
    se = e.resolved["fed.2024.se.total"]
    niit = e.resolved["fed.2024.niit.final"]
    medicare = e.resolved["fed.2024.addl_medicare.final"]
    assert medicare == Decimal("866")
    assert e.resolved["fed.2024.tax.other_taxes"] == se + niit + medicare
    pkt = map_return_run(run)
    assert pkt.form_1040.line_23 == se + niit + medicare
    assert pkt.consistency_errors == []


def test_liability_settles_including_the_surtax() -> None:
    e, run = _run(2024, "250000")
    liability = e.resolved["fed.2024.tax.total_liability"]
    assert liability == e.resolved["fed.2024.tax.after_credits"] + Decimal("450")
    assert run.output.refund_or_owed == -liability
