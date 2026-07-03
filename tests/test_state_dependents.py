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

"""State dependent exemption golden tests (Milestone 28).

Hand-verified against: O.C.G.A. §48-7-26 (GA dependent exemption —
$3,000 for 2023, raised to $4,000 by HB 1021 effective TY 2024), the
2024 IT-201 $1,000 per-dependent exemption (line 36), and the 2024
Form 540 exemption credits (lines 7–10: $149 per personal/blind/senior
unit with two personal units for MFJ/QSS, $461 per dependent; the
high-AGI phaseout under R&TC §17054.1 is unmodeled).
"""

from decimal import Decimal
from pathlib import Path

import pytest

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

BASE = Path("rule_packs")
FED = {y: RulePack.load(BASE / "federal" / str(y)) for y in (2023, 2024, 2025)}
STATE = {
    (s, y): RulePack.load(BASE / "state" / s / str(y))
    for s, y in [("GA", 2023), ("GA", 2024), ("GA", 2025), ("NY", 2024), ("CA", 2024)]
}


def _run(
    year: int,
    state: str,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    children: int = 0,
    other_dependents: int = 0,
    *,
    p65: bool = False,
    pblind: bool = False,
    renter: bool = False,
) -> tuple[CalculationEngine, ReturnRun]:
    taxpayers = [
        Taxpayer(
            role=TaxpayerRole.PRIMARY,
            first_name="Golden",
            last_name="Vector",
            w2s=[W2Data(employer_name="Acme", wages=Decimal(wages), state=state)],
            is_65_or_older=p65,
            is_blind=pblind,
        )
    ]
    if filing_status == FilingStatus.MFJ:
        taxpayers.append(Taxpayer(role=TaxpayerRole.SPOUSE, first_name="Pat", last_name="Vector"))
    inp = TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        qualifying_children=children,
        other_dependents=other_dependents,
        ca_renter=renter,
    )
    engine = CalculationEngine(FED[year], inp, state_packs={state: STATE[(state, year)]})
    return engine, engine.run()


# ─── Georgia dependent exemption ──────────────────────────────


def test_ga_2024_dependent_exemption_is_4000() -> None:
    """1 child + 1 other dependent, $30k wages: taxable 30k−12k−8k = $10k → $539."""
    e, _ = _run(2024, "GA", "30000", children=1, other_dependents=1)
    assert e.resolved["ga.2024.dependent_exemption"] == Decimal("8000")
    assert e.resolved["ga.2024.taxable_income"] == Decimal("10000")
    assert e.resolved["ga.2024.tax"] == Decimal("539")


def test_ga_2023_dependent_exemption_is_3000() -> None:
    """Pre-HB 1021: taxable = 30,000 − 5,400 − 2,700 − 3,000 = $18,900 → $914."""
    e, _ = _run(2023, "GA", "30000", children=1)
    assert e.resolved["ga.2023.dependent_exemption"] == Decimal("3000")
    assert e.resolved["ga.2023.taxable_income"] == Decimal("18900")
    assert e.resolved["ga.2023.tax"] == Decimal("914")


def test_ga_2025_keeps_the_4000_amount() -> None:
    e, _ = _run(2025, "GA", "30000", children=2)
    assert e.resolved["ga.2025.dependent_exemption"] == Decimal("8000")


def test_ga_without_dependents_is_unchanged() -> None:
    e, _ = _run(2024, "GA", "30000")
    assert e.resolved["ga.2024.taxable_income"] == Decimal("18000")


# ─── New York dependent exemption ─────────────────────────────


def test_ny_dependent_exemption_is_1000() -> None:
    """1 dependent, $58k wages: taxable 58k−8k−1k = $49,000 → $2,530."""
    e, _ = _run(2024, "NY", "58000", children=1)
    assert e.resolved["ny.2024.dependent_exemption"] == Decimal("1000")
    assert e.resolved["ny.2024.taxable_income"] == Decimal("49000")
    assert e.resolved["ny.2024.tax"] == Decimal("2530")


def test_ny_without_dependents_is_unchanged() -> None:
    e, _ = _run(2024, "NY", "58000")
    assert e.resolved["ny.2024.tax"] == Decimal("2585")


# ─── California exemption credits (Form 540 lines 7–11) ───────


def test_ca_personal_exemption_credit_single() -> None:
    """Every single filer gets the $149 personal credit against tax."""
    e, run = _run(2024, "CA", "50000")
    assert e.resolved["ca.2024.credits.exemption.personal"] == Decimal("149")
    assert e.resolved["ca.2024.credits.total"] == Decimal("149")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-1096")


def test_ca_mfj_two_personal_units_and_dependents() -> None:
    """MFJ + 2 dependents at $100k: $298 + 2 × $461 = $1,220 off a $2,490 tax."""
    e, run = _run(2024, "CA", "100000", FilingStatus.MFJ, children=2)
    assert e.resolved["ca.2024.tax"] == Decimal("2490")
    assert e.resolved["ca.2024.credits.exemption.personal"] == Decimal("298")
    assert e.resolved["ca.2024.credits.exemption.dependent"] == Decimal("922")
    assert e.resolved["ca.2024.credits.exemptions"] == Decimal("1220")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-1270")


def test_ca_senior_and_blind_credits() -> None:
    """A single filer 65+ and blind stacks three $149 units."""
    e, _ = _run(2024, "CA", "50000", p65=True, pblind=True)
    assert e.resolved["ca.2024.credits.exemption.senior"] == Decimal("149")
    assert e.resolved["ca.2024.credits.exemption.blind"] == Decimal("149")
    assert e.resolved["ca.2024.credits.exemptions"] == Decimal("447")


def test_ca_credits_cap_at_tax() -> None:
    """$6k wages renter + 1 dependent: $5 of tax absorbs everything."""
    e, run = _run(2024, "CA", "6000", children=1, renter=True)
    assert e.resolved["ca.2024.tax"] == Decimal("5")
    assert e.resolved["ca.2024.credits.total"] == Decimal("5")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("0")


@pytest.mark.parametrize(
    ("filing_status", "expected"),
    [
        (FilingStatus.SINGLE, "149"),
        (FilingStatus.MFJ, "298"),
        (FilingStatus.QSS, "298"),
        (FilingStatus.HOH, "149"),
        (FilingStatus.MFS, "149"),
    ],
)
def test_ca_personal_units_by_filing_status(filing_status: FilingStatus, expected: str) -> None:
    e, _ = _run(2024, "CA", "50000", filing_status)
    assert e.resolved["ca.2024.credits.exemption.personal"] == Decimal(expected)
