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

"""Schedule 8812 golden tests: refundable ACTC and the ODC (Milestone 26).

Hand-verified against Schedule 8812 / IRC §24: the $500 nonrefundable
credit for other dependents sharing the CTC's $50-per-$1,000 AGI
phaseout; the refundable Additional Child Tax Credit — unused CTC/ODC
limited to the per-child ceiling ($1,600 for 2023, $1,700 for 2024/2025
per Rev. Procs.) and 15% of earned income over $2,500 — flowing to 1040
line 28; and the mandatory inclusion of nontaxable combat pay in Form
8812 earned income (unlike the elective EIC treatment).
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.engine.whatif import WhatIfEngine
from app.models.domain import (
    FilingStatus,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.form_mapper import map_return_run

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}


def _input(
    year: int,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    children: int = 0,
    other_dependents: int = 0,
    combat: str = "0",
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        qualifying_children=children,
        other_dependents=other_dependents,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))],
                nontaxable_combat_pay=Decimal(combat),
            )
        ],
    )


def _run(inp: TaxReturnInput) -> tuple[CalculationEngine, ReturnRun]:
    engine = CalculationEngine(FED[inp.tax_year], inp)
    return engine, engine.run()


# ─── Refundable ACTC ──────────────────────────────────────────


def test_unused_ctc_refunds_as_actc() -> None:
    """Single, 2 children, $25k wages: tax $1,040 absorbed, $2,960 refunds."""
    e, run = _run(_input(2024, "25000", children=2))
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("1040")
    assert e.resolved["fed.2024.credits.ctc.combined"] == Decimal("4000")
    assert e.resolved["fed.2024.credits.ctc.final"] == Decimal("1040")
    assert e.resolved["fed.2024.credits.actc.unused"] == Decimal("2960")
    assert e.resolved["fed.2024.credits.actc.cap"] == Decimal("3400")
    assert e.resolved["fed.2024.credits.actc.phase_in"] == Decimal("3375")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("2960")
    assert run.output.additional_child_tax_credit == Decimal("2960")


def test_phase_in_limits_the_refund() -> None:
    """1 child, $8k wages: zero tax, ACTC = 15% × $5,500 = $825."""
    e, _ = _run(_input(2024, "8000", children=1))
    assert e.resolved["fed.2024.credits.ctc.final"] == Decimal("0")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("825")


def test_per_child_cap_limits_the_refund() -> None:
    """Combat pay drives the phase-in past the cap: 1 child caps at $1,700."""
    e, _ = _run(_input(2024, "0", children=1, combat="20000"))
    assert e.resolved["fed.2024.credits.actc.earned_income"] == Decimal("20000.00")
    assert e.resolved["fed.2024.credits.actc.phase_in"] == Decimal("2625")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("1700")


@pytest.mark.parametrize(("year", "cap"), [(2023, "3200"), (2024, "3400"), (2025, "3400")])
def test_rev_proc_caps_by_year(year: int, cap: str) -> None:
    """2 children, $5k wages + $30k combat pay: the per-child ceiling binds."""
    e, _ = _run(_input(year, "5000", children=2, combat="30000"))
    assert e.resolved[f"fed.{year}.credits.actc.cap"] == Decimal(cap)
    assert e.resolved[f"fed.{year}.credits.actc.final"] == Decimal(cap)


def test_2025_obbba_base_with_unchanged_refundable_cap() -> None:
    """OBBBA raises the CTC to $2,200/child; the refundable cap stays $1,700."""
    e, _ = _run(_input(2025, "8000", children=1))
    assert e.resolved["fed.2025.credits.ctc.base"] == Decimal("2200")
    assert e.resolved["fed.2025.credits.actc.final"] == Decimal("825")


# ─── Credit for other dependents ──────────────────────────────


def test_odc_reduces_tax() -> None:
    """0 children, 2 other dependents, $60k wages: $1,000 off a $5,216 tax."""
    e, _ = _run(_input(2024, "60000", other_dependents=2))
    assert e.resolved["fed.2024.credits.odc.base"] == Decimal("1000")
    assert e.resolved["fed.2024.credits.ctc.final"] == Decimal("1000")
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("4216")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("0")


def test_odc_is_never_refundable() -> None:
    """Zero tax: the unused $500 ODC dies because the ACTC cap is 0 × child."""
    e, _ = _run(_input(2024, "8000", other_dependents=1))
    assert e.resolved["fed.2024.credits.actc.unused"] == Decimal("500")
    assert e.resolved["fed.2024.credits.actc.cap"] == Decimal("0")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("0")


def test_phaseout_applies_to_combined_credit() -> None:
    """MFJ, 2 children + 1 ODC at $420k AGI: $50 × 20 units off the $4,500."""
    e, _ = _run(_input(2024, "420000", FilingStatus.MFJ, children=2, other_dependents=1))
    assert e.resolved["fed.2024.credits.ctc.phaseout"] == Decimal("1000")
    assert e.resolved["fed.2024.credits.ctc.combined"] == Decimal("3500")


def test_no_dependents_leaves_credits_unchanged() -> None:
    e, _ = _run(_input(2024, "60000"))
    assert e.resolved["fed.2024.credits.ctc.final"] == Decimal("0")
    assert e.resolved["fed.2024.credits.actc.final"] == Decimal("0")


def test_other_credits_apply_before_ctc_limit() -> None:
    """The Form 8812 Credit Limit Worksheet subtracts other credits first."""
    e, _ = _run(_input(2024, "25000", children=2))
    assert e.resolved["fed.2024.credits.other_nonrefundable"] == Decimal("0")
    assert e.resolved["fed.2024.credits.ctc.tax_limit"] == Decimal("1040")


# ─── 1040 wiring ──────────────────────────────────────────────


def test_actc_lands_on_line_28_with_consistent_payments() -> None:
    e, run = _run(_input(2024, "25000", children=2))
    pkt = map_return_run(run)
    assert pkt.form_1040.line_28 == Decimal("2960")
    assert pkt.consistency_errors == []
    assert run.output.total_payments >= Decimal("2960")


# ─── What-if election isolation ───────────────────────────────


def test_whatif_election_is_isolated_from_the_actc() -> None:
    """Zeroing combat pay would misstate ACTC (8812 inclusion is mandatory);
    the no-election scenario must differ from the elected one by EIC only."""
    comp = WhatIfEngine(FED[2024]).compare_combat_pay_election(
        _input(2024, "4000", children=1, combat="8000")
    )
    assert comp.diffs[0]["a"] == "4080"
    assert comp.diffs[0]["b"] == "1360"
    assert comp.savings == Decimal("2720")
    assert comp.scenario_a.refund_or_owed - comp.scenario_b.refund_or_owed == Decimal("2720")
