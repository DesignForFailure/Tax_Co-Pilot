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

"""Child and Dependent Care Credit golden tests (Milestone 21).

Hand-verified against Form 2441 / IRC §21: the $3,000/$6,000 expense
caps, the 35%→20% sliding rate ($1 per $2,000-or-fraction step of AGI
over $15,000), the earned income limit (lesser spouse for MFJ), and
nonrefundability.
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

FED_2024 = RulePack.load(Path("rule_packs/federal/2024"))
FED_2023 = RulePack.load(Path("rule_packs/federal/2023"))
FED_2025 = RulePack.load(Path("rule_packs/federal/2025"))


def _run(
    pack: RulePack,
    filing_status: FilingStatus,
    primary_wages: str,
    spouse_wages: str | None = None,
    persons: int = 0,
    expenses: str = "0",
) -> tuple[CalculationEngine, ReturnRun]:
    taxpayers = [
        Taxpayer(
            role=TaxpayerRole.PRIMARY,
            first_name="Golden",
            last_name="Vector",
            w2s=[W2Data(employer_name="Acme", wages=Decimal(primary_wages))],
        )
    ]
    if spouse_wages is not None:
        taxpayers.append(
            Taxpayer(
                role=TaxpayerRole.SPOUSE,
                first_name="Spouse",
                last_name="Vector",
                w2s=(
                    [W2Data(employer_name="Beta", wages=Decimal(spouse_wages))]
                    if spouse_wages != "0"
                    else []
                ),
            )
        )
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        dependent_care_expenses=Decimal(expenses),
        dependent_care_qualifying_persons=persons,
    )
    engine = CalculationEngine(pack, inp)
    return engine, engine.run()


def test_one_person_cap_and_floor_rate() -> None:
    """Single $50k, one child, $5,000 paid: capped at $3,000 × 20% = $600."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "50000", persons=1, expenses="5000")
    assert e.resolved["fed.2024.credits.care.dollar_cap"] == Decimal("3000")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.20")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("600")
    assert run.output.dependent_care_credit == Decimal("600")


def test_maximum_rate_at_low_agi() -> None:
    """AGI $15,000 keeps the full 35% rate: $3,000 × 35% = $1,050."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "15000", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.35")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("1050")


def test_sliding_rate_mid_table() -> None:
    """AGI $25,000 → 5 steps → 30%; two kids, $7,000 paid → $6,000 × 30%."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "25000", persons=2, expenses="7000")
    assert e.resolved["fed.2024.credits.care.agi_steps"] == Decimal("5")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.30")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("1800")


def test_rate_table_boundary_at_43000() -> None:
    """The IRS table: $41k–$43k → 21%; over $43k → the 20% floor."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "43000", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.21")
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "43001", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.20")


def test_fraction_of_a_step_rounds_up() -> None:
    """AGI $15,001 is 'over $15,000' → one step → 34%."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "15001", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.agi_steps"] == Decimal("1")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.34")


def test_mfj_limited_by_lesser_earning_spouse() -> None:
    """MFJ: $40k + $2k earners → expenses capped at $2,000 (21% at $42k AGI)."""
    e, _ = _run(
        FED_2024, FilingStatus.MFJ, "40000", spouse_wages="2000", persons=2, expenses="5000"
    )
    assert e.resolved["fed.2024.credits.care.earned_cap"] == Decimal("2000.00")
    assert e.resolved["fed.2024.credits.care.rate"] == Decimal("0.21")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("420")


def test_mfj_spouse_without_earned_income_gets_nothing() -> None:
    """Both spouses need earned income (student/disabled exception unmodeled)."""
    e, _ = _run(
        FED_2024, FilingStatus.MFJ, "40000", spouse_wages="0", persons=1, expenses="3000"
    )
    assert e.resolved["fed.2024.credits.care.earned_cap"] == Decimal("0.00")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("0")


def test_single_filer_not_limited_by_spouse_input() -> None:
    """Non-MFJ statuses use only the primary earned income."""
    e, _ = _run(FED_2024, FilingStatus.HOH, "30000", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.earned_cap"] == Decimal("30000.00")
    assert e.resolved["fed.2024.credits.care.final"] > Decimal("0")


def test_zero_qualifying_persons_zero_credit() -> None:
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "30000", persons=0, expenses="3000")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("0")


def test_three_persons_capped_at_6000() -> None:
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "25000", persons=3, expenses="9000")
    assert e.resolved["fed.2024.credits.care.dollar_cap"] == Decimal("6000")


def test_credit_is_nonrefundable() -> None:
    """Low-income filer: the credit absorbs the tax but never pays out."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "16000", persons=1, expenses="3000")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("1020")
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("0")
    # The refund is exactly the childless EIC at this income — no care payout.
    assert run.output.refund_or_owed == e.resolved["fed.2024.credits.eic.final"]


def test_no_care_inputs_changes_nothing() -> None:
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "85000")
    assert e.resolved["fed.2024.credits.care.final"] == Decimal("0")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("10541")


@pytest.mark.parametrize("pack", [FED_2023, FED_2025])
def test_other_years_share_the_statutory_parameters(pack: RulePack) -> None:
    """IRC §21 amounts are not inflation-indexed (post-ARPA)."""
    yr = pack.tax_year
    e, _ = _run(pack, FilingStatus.SINGLE, "25000", persons=2, expenses="7000")
    assert e.resolved[f"fed.{yr}.credits.care.rate"] == Decimal("0.30")
    assert e.resolved[f"fed.{yr}.credits.care.final"] == Decimal("1800")


def test_calculate_route_parses_care_fields() -> None:
    """The web form's dependent-care fields reach the engine."""
    from fastapi.testclient import TestClient

    from app.services.database import init_db, list_return_runs
    from main import app

    init_db()
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("csrf", "care-csrf")
    resp = client.post(
        "/calculate",
        data={
            "csrf_token": "care-csrf",
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Working",
            "p_last": "Parent",
            "p_w2_0_employer": "Acme",
            "p_w2_0_wages": "25000",
            "care_persons": "2",
            "care_expenses": "7000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    runs, _ = list_return_runs(page=1, page_size=1)
    data = client.get(f"/runs/{runs[0]['id']}/export/json").json()
    assert Decimal(data["output"]["dependent_care_credit"]) == Decimal("1800")
    assert data["input_snapshot"]["dependent_care_qualifying_persons"] == 2
