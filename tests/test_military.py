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

"""Military tax provision golden tests (Milestone 24).

Hand-verified against IRC §112 / Pub 3 (combat zone exclusion and the
commissioned-officer monthly caps: $10,011.00 for 2023, $10,519.80 for
2024, $10,983.00 for 2025 — highest enlisted basic pay plus $225 hostile
fire/imminent danger pay), IRC §217(g) (military moving expenses),
IRC §62(a)(2)(E) (reservist travel), and the IRC §32(c)(2)(B)(vi) EITC
combat pay election (Pub 596: all-or-nothing, take the better result).
"""

from decimal import Decimal
from pathlib import Path

import pytest
from starlette.datastructures import FormData

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
from app.route_helpers.form_parsing import parse_tax_input_from_form

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}


def _input(
    year: int,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    children: int = 0,
    combat: str = "0",
    *,
    officer: bool = False,
    months: int = 0,
    moving: str = "0",
    travel: str = "0",
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        qualifying_children=children,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="DFAS", wages=Decimal(wages))],
                nontaxable_combat_pay=Decimal(combat),
                is_commissioned_officer=officer,
                combat_zone_months=months,
                active_duty_moving_expenses=Decimal(moving),
                reservist_travel_expenses=Decimal(travel),
            )
        ],
    )


def _run(inp: TaxReturnInput) -> tuple[CalculationEngine, ReturnRun]:
    engine = CalculationEngine(FED[inp.tax_year], inp)
    return engine, engine.run()


# ─── Combat pay exclusion (IRC §112) ──────────────────────────


def test_combat_pay_never_enters_agi() -> None:
    """Box 12 Q is already absent from Box 1; the engine must not re-touch AGI."""
    e, run = _run(_input(2024, "30000", combat="20000"))
    assert e.resolved["fed.2024.agi.total"] == Decimal("30000.00")
    assert e.resolved["fed.2024.military.combat_pay_exclusion"] == Decimal("20000.00")
    assert run.output.agi == Decimal("30000.00")


def test_exclusion_appears_in_trace() -> None:
    e, run = _run(_input(2024, "30000", combat="20000"))
    nodes = [t for t in run.trace if t.rule_id == "fed.2024.military.combat_pay_exclusion"]
    assert len(nodes) == 1
    assert nodes[0].form_line == "W-2 Box 12 Q"


# ─── Officer exclusion cap (IRC §112(b)) ──────────────────────


def test_officer_cap_flags_excess() -> None:
    """Officer, 6 months, $70k Q: cap 6 × $10,519.80 = $63,118.80 → $6,881.20 over."""
    e, _ = _run(_input(2024, "100000", combat="70000", officer=True, months=6))
    assert e.resolved["fed.2024.military.officer_cap"] == Decimal("63118.80")
    assert e.resolved["fed.2024.military.officer_excess"] == Decimal("6881.20")


def test_enlisted_exclusion_is_uncapped() -> None:
    e, _ = _run(_input(2024, "100000", combat="70000", officer=False, months=6))
    assert e.resolved["fed.2024.military.officer_excess"] == Decimal("0.00")


def test_officer_within_cap_has_no_excess() -> None:
    e, _ = _run(_input(2024, "100000", combat="60000", officer=True, months=6))
    assert e.resolved["fed.2024.military.officer_excess"] == Decimal("0.00")


@pytest.mark.parametrize(
    ("year", "cap", "excess"),
    [
        (2023, "10011.00", "4989.00"),
        (2025, "10983.00", "4017.00"),
    ],
)
def test_officer_monthly_caps_by_year(year: int, cap: str, excess: str) -> None:
    """Pub 3 monthly limits: $9,786/$10,294.80/$10,758 enlisted max + $225 IDP."""
    e, _ = _run(_input(year, "50000", combat="15000", officer=True, months=1))
    assert e.resolved[f"fed.{year}.military.officer_cap"] == Decimal(cap)
    assert e.resolved[f"fed.{year}.military.officer_excess"] == Decimal(excess)


# ─── Military adjustments (Schedule 1) ────────────────────────


def test_moving_and_reservist_expenses_reduce_agi() -> None:
    """$2,000 PCS move + $1,500 reservist travel: AGI drops from $50k to $46.5k."""
    e, run = _run(_input(2024, "50000", moving="2000", travel="1500"))
    assert e.resolved["fed.2024.adjustments.military_moving"] == Decimal("2000.00")
    assert e.resolved["fed.2024.adjustments.reservist_travel"] == Decimal("1500.00")
    assert e.resolved["fed.2024.adjustments.total"] == Decimal("3500.00")
    assert run.output.agi == Decimal("46500.00")


# ─── EITC combat pay election (IRC §32(c)(2)(B)(vi)) ──────────


def test_election_taken_when_it_raises_the_credit() -> None:
    """$4k wages + $8k combat pay, 1 child: 34% of $12k beats 34% of $4k."""
    e, run = _run(_input(2024, "4000", children=1, combat="8000"))
    assert e.resolved["fed.2024.credits.eic.tentative"] == Decimal("1360")
    assert e.resolved["fed.2024.credits.eic.tentative_elected"] == Decimal("4080")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("4080")
    assert run.output.earned_income_credit == Decimal("4080")


def test_election_skipped_when_it_lowers_the_credit() -> None:
    """$18k wages + $20k combat pay: electing lands in the phaseout, base wins."""
    e, _ = _run(_input(2024, "18000", children=1, combat="20000"))
    assert e.resolved["fed.2024.credits.eic.tentative"] == Decimal("4213")
    assert e.resolved["fed.2024.credits.eic.tentative_elected"] == Decimal("1771")
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("4213")


def test_no_combat_pay_leaves_eic_unchanged() -> None:
    """Without Box 12 Q the elected chain mirrors the base chain exactly."""
    e, _ = _run(_input(2024, "18000", children=1))
    assert (
        e.resolved["fed.2024.credits.eic.tentative_elected"]
        == e.resolved["fed.2024.credits.eic.tentative"]
    )
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("4213")


def test_elected_eic_flows_to_payments() -> None:
    """The elected EIC lands on 1040 line 27 via total payments (refundable)."""
    _, run = _run(_input(2024, "4000", children=1, combat="8000"))
    assert run.output.total_payments >= Decimal("4080")


# ─── What-if: combat pay election scenario ────────────────────


def test_whatif_election_recommends_electing_when_beneficial() -> None:
    comp = WhatIfEngine(FED[2024]).compare_combat_pay_election(
        _input(2024, "4000", children=1, combat="8000")
    )
    assert comp.scenario_a.scenario_name == "elect combat pay"
    assert comp.scenario_b.scenario_name == "no election"
    assert comp.recommendation == "elect combat pay"
    assert comp.savings == Decimal("2720")
    assert comp.diffs[0]["a"] == "4080"
    assert comp.diffs[0]["b"] == "1360"


def test_whatif_election_never_recommends_a_worse_outcome() -> None:
    """The engine already maxes, so the election scenario can never lose money."""
    comp = WhatIfEngine(FED[2024]).compare_combat_pay_election(
        _input(2024, "18000", children=1, combat="20000")
    )
    assert comp.recommendation == "no election"
    assert comp.savings == Decimal("0")


def test_whatif_election_requires_combat_pay() -> None:
    with pytest.raises(ValueError, match="combat pay"):
        WhatIfEngine(FED[2024]).compare_combat_pay_election(_input(2024, "18000", children=1))


# ─── Web form wiring ──────────────────────────────────────────


def test_form_parses_military_fields() -> None:
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Pat",
            "p_last": "Miller",
            "p_w2_0_wages": "40000",
            "p_combat_pay": "12000",
            "p_combat_months": "4",
            "p_officer": "1",
            "p_moving_expenses": "1800",
            "p_reservist_travel": "600",
        }
    )
    inp = parse_tax_input_from_form(fd, [2023, 2024, 2025])
    tp = inp.taxpayers[0]
    assert tp.nontaxable_combat_pay == Decimal("12000")
    assert tp.is_commissioned_officer is True
    assert tp.combat_zone_months == 4
    assert tp.active_duty_moving_expenses == Decimal("1800")
    assert tp.reservist_travel_expenses == Decimal("600")


def test_form_rejects_out_of_range_combat_months() -> None:
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Pat",
            "p_last": "Miller",
            "p_w2_0_wages": "40000",
            "p_combat_months": "13",
        }
    )
    with pytest.raises(ValueError, match="0 to 12"):
        parse_tax_input_from_form(fd, [2023, 2024, 2025])
