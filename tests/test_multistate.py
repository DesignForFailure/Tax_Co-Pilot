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

"""Multi-state apportionment golden tests (Milestone 31).

Hand-verified against the standard two-state W-2 mechanics: nonresident
states tax the as-if-resident amount times the state-wage share (the
IT-203/540NR ratio method), and the residence state grants a credit for
taxes paid to other states — the smaller of their net tax or the
residence tax on the doubly-taxed wage share. An empty residence state
preserves the pre-M31 behavior (every state runs as a full-year
resident return).
"""

from decimal import Decimal
from pathlib import Path

from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.route_helpers.form_parsing import parse_tax_input_from_form

FED = RulePack.load(Path("rule_packs/federal/2024"))
STATE = {s: RulePack.load(Path(f"rule_packs/state/{s}/2024")) for s in ("GA", "CA", "NY")}


def _w2(wages: str, state: str) -> W2Data:
    return W2Data(
        employer_name=f"{state} employer",
        wages=Decimal(wages),
        state=state,
        state_wages=Decimal(wages),
    )


def _run(
    w2s: list[W2Data],
    residence: str,
    packs: tuple[str, ...] = ("GA", "NY"),
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        state_of_residence=residence,
        taxpayers=[
            Taxpayer(role=TaxpayerRole.PRIMARY, first_name="Multi", last_name="State", w2s=w2s)
        ],
    )
    engine = CalculationEngine(FED, inp, state_packs={s: STATE[s] for s in packs})
    return engine, engine.run()


TWO_STATE = [_w2("60000", "GA"), _w2("40000", "NY")]


def test_nonresident_state_is_wage_apportioned() -> None:
    """GA resident, 40% NY wages: NY as-if-resident $4,952 × 0.4 = $1,981."""
    e, _ = _run(TWO_STATE, residence="GA")
    assert e.resolved["input.state.apportionment.NY"] == Decimal("0.4000")
    assert e.resolved["ny.2024.tax.full"] == Decimal("4952")
    assert e.resolved["ny.2024.tax"] == Decimal("1981")
    assert e.resolved["ny.2024.credits.other_state"] == Decimal("0")


def test_resident_state_credits_other_state_tax() -> None:
    """GA taxes everything ($4,743) but credits the $1,981 NY tax, capped
    at GA's own tax on the NY share (4,743 × 0.4 = $1,897)."""
    e, run = _run(TWO_STATE, residence="GA")
    assert e.resolved["input.state.apportionment.GA"] == Decimal("1.0000")
    assert e.resolved["ga.2024.tax"] == Decimal("4743")
    assert e.resolved["input.state.other_state_tax"] == Decimal("1981")
    assert e.resolved["ga.2024.credits.other_state"] == Decimal("1897")
    ga = next(s for s in run.state_outputs if s.state == "GA")
    ny = next(s for s in run.state_outputs if s.state == "NY")
    assert ga.state_refund_or_owed == Decimal("-2846")
    assert ny.state_refund_or_owed == Decimal("-1981")


def test_reverse_residence_credits_fully() -> None:
    """NY resident with GA wages: GA apportioned $2,846 fully credits
    (under NY's $2,971 cap on the 60% share)."""
    e, run = _run(TWO_STATE, residence="NY")
    assert e.resolved["ga.2024.tax"] == Decimal("2846")
    assert e.resolved["ny.2024.tax"] == Decimal("4952")
    assert e.resolved["ny.2024.credits.other_state"] == Decimal("2846")
    ny = next(s for s in run.state_outputs if s.state == "NY")
    assert ny.state_refund_or_owed == Decimal("-2106")


def test_empty_residence_preserves_full_resident_runs() -> None:
    """No residence selected: both states tax in full with no credits
    (the pre-M31 behavior, keeping older runs reproducible)."""
    e, _ = _run(TWO_STATE, residence="")
    assert e.resolved["ga.2024.tax"] == Decimal("4743")
    assert e.resolved["ny.2024.tax"] == Decimal("4952")
    assert e.resolved["ga.2024.credits.other_state"] == Decimal("0")
    assert e.resolved["ny.2024.credits.other_state"] == Decimal("0")


def test_single_state_resident_is_unchanged() -> None:
    """The M23 GA golden vector holds under the new chain."""
    e, _ = _run([_w2("30000", "GA")], residence="GA", packs=("GA",))
    assert e.resolved["ga.2024.tax"] == Decimal("970")
    assert e.resolved["input.state.apportionment.GA"] == Decimal("1.0000")


def test_credit_caps_at_residence_tax_on_shared_income() -> None:
    """CA resident with 50% NY wages: the credit is the smaller leg."""
    w2s = [_w2("50000", "CA"), _w2("50000", "NY")]
    e, _ = _run(w2s, residence="CA", packs=("CA", "NY"))
    ny_apportioned = e.resolved["ny.2024.tax"]
    cap = (e.resolved["ca.2024.tax.full"] * Decimal("0.5")).quantize(Decimal("1"))
    assert e.resolved["ca.2024.credits.other_state"] == min(ny_apportioned, cap)


def test_box_16_blank_falls_back_to_box_1() -> None:
    """A W-2 with a state code but no Box 16 counts its Box 1 wages."""
    w2s = [
        W2Data(employer_name="A", wages=Decimal("60000"), state="GA"),
        W2Data(employer_name="B", wages=Decimal("40000"), state="NY"),
    ]
    e, _ = _run(w2s, residence="GA")
    assert e.resolved["input.state.apportionment.NY"] == Decimal("0.4000")


def test_form_parsing_round_trips_residence() -> None:
    fd = FormData(
        [
            ("tax_year", "2024"),
            ("filing_status", "single"),
            ("state_of_residence", "ga"),
            ("p_first", "A"),
            ("p_last", "B"),
            ("p_w2_0_employer", "Acme"),
            ("p_w2_0_wages", "50000"),
        ]
    )
    inp = parse_tax_input_from_form(fd, [2024])
    assert inp.state_of_residence == "GA"
