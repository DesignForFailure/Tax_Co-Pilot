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

"""Self-employment tax golden tests (Milestone 18).

Hand-verified against Schedule SE: the 92.35% net-earnings factor, the
$400 floor (IRC 1402(b)(2)), the Social Security wage base reduced by
W-2 wages, the uncapped 2.9% Medicare portion, the employer-equivalent
half deduction flowing into AGI, the manual-deduction fallback, and the
new total-liability line that settles the refund.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
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
    wages: str | None = None,
    nec: str | None = None,
    manual_deduction: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=FilingStatus.SINGLE,
        adjustments=(
            AdjustmentsData(self_employment_tax_deduction=Decimal(manual_deduction))
            if manual_deduction
            else AdjustmentsData()
        ),
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
            )
        ],
    )
    engine = CalculationEngine(pack, inp)
    return engine, engine.run()


def test_100k_nec_no_w2() -> None:
    """$100k NEC → SE tax $14,130 (92.35% × 15.3%), deduction $7,065."""
    e, run = _run(FED_2024, nec="100000")
    assert e.resolved["fed.2024.se.net_earnings"] == Decimal("92350.00")
    assert e.resolved["fed.2024.se.ss_tax"] == Decimal("11451.40")
    assert e.resolved["fed.2024.se.medicare_tax"] == Decimal("2678.15")
    assert e.resolved["fed.2024.se.total"] == Decimal("14130")
    assert e.resolved["fed.2024.se.deduction"] == Decimal("7065")
    assert run.output.self_employment_tax == Decimal("14130")


def test_se_deduction_flows_into_agi() -> None:
    """$100k NEC: AGI = 100,000 − 7,065 (auto SE deduction)."""
    _, run = _run(FED_2024, nec="100000")
    assert run.output.adjustments_total == Decimal("7065.00")
    assert run.output.agi == Decimal("92935.00")


def test_ss_wage_base_reduced_by_w2_wages() -> None:
    """$200k W-2 + $50k NEC: the wage base is exhausted by W-2 wages, so
    only the uncapped 2.9% Medicare portion applies."""
    e, _ = _run(FED_2024, wages="200000", nec="50000")
    assert e.resolved["fed.2024.se.ss_taxable"] == Decimal("0.00")
    assert e.resolved["fed.2024.se.ss_tax"] == Decimal("0.00")
    assert e.resolved["fed.2024.se.medicare_tax"] == Decimal("1339.08")
    assert e.resolved["fed.2024.se.total"] == Decimal("1339")
    assert e.resolved["fed.2024.se.deduction"] == Decimal("670")


def test_ss_wage_base_partially_used_by_w2_wages() -> None:
    """$150k W-2 + $50k NEC: only 168,600 − 150,000 = 18,600 of the SE
    earnings take the 12.4% Social Security rate."""
    e, _ = _run(FED_2024, wages="150000", nec="50000")
    assert e.resolved["fed.2024.se.ss_taxable"] == Decimal("18600.00")
    assert e.resolved["fed.2024.se.ss_tax"] == Decimal("2306.40")
    assert e.resolved["fed.2024.se.medicare_tax"] == Decimal("1339.08")
    assert e.resolved["fed.2024.se.total"] == Decimal("3645")


def test_zero_nec_manual_deduction_still_works() -> None:
    """No NEC income: no SE tax, and the manual deduction passes through."""
    e, run = _run(FED_2024, wages="60000", manual_deduction="3500")
    assert e.resolved["fed.2024.se.total"] == Decimal("0")
    assert e.resolved["fed.2024.adjustments.se_tax"] == Decimal("3500.00")
    assert run.output.agi == Decimal("56500.00")
    assert run.output.self_employment_tax == Decimal("0")


def test_calculated_deduction_wins_over_manual_when_nec_exists() -> None:
    """$50k NEC + a bogus manual override: the calculated value is used."""
    e, _ = _run(FED_2024, nec="50000", manual_deduction="9999")
    assert e.resolved["fed.2024.se.deduction"] == Decimal("3533")
    assert e.resolved["fed.2024.adjustments.se_tax"] == Decimal("3533.00")


def test_400_dollar_floor_no_se_tax_below() -> None:
    """$400 NEC → net earnings $369.40 < $400 → no SE tax at all."""
    e, run = _run(FED_2024, nec="400")
    assert e.resolved["fed.2024.se.net_earnings_raw"] == Decimal("369.40")
    assert e.resolved["fed.2024.se.applies"] == Decimal("0.00")
    assert e.resolved["fed.2024.se.total"] == Decimal("0")
    assert run.output.self_employment_tax == Decimal("0")


def test_400_dollar_floor_se_tax_at_or_above() -> None:
    """$500 NEC → net earnings $461.75 ≥ $400 → SE tax applies."""
    e, _ = _run(FED_2024, nec="500")
    assert e.resolved["fed.2024.se.applies"] == Decimal("1.00")
    # 461.75 × 12.4% = 57.26; × 2.9% = 13.39; total 70.65 → 71.
    assert e.resolved["fed.2024.se.total"] == Decimal("71")
    assert e.resolved["fed.2024.se.deduction"] == Decimal("36")


def test_refund_settles_against_total_liability() -> None:
    """$100k NEC: refund line owes income tax + SE tax together."""
    e, run = _run(FED_2024, nec="100000")
    # Taxable 78,335 → income tax 12,287; + SE 14,130 = 26,417 owed.
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("12287")
    assert e.resolved["fed.2024.tax.total_liability"] == Decimal("26417")
    assert run.output.refund_or_owed == Decimal("-26417")


def test_form_mapper_lines_23_24_and_owed() -> None:
    """SE tax reaches 1040 lines 23/24 and the mapper's owed amount."""
    _, run = _run(FED_2024, nec="100000")
    pkt = map_return_run(run)
    assert pkt.form_1040.line_23 == Decimal("14130")
    assert pkt.form_1040.line_24 == Decimal("26417")
    assert pkt.form_1040.line_37 == Decimal("26417")
    assert pkt.consistency_errors == []


def test_wages_only_return_unaffected() -> None:
    """Regression: W-2-only filers see no SE rules changing their bottom line."""
    e, run = _run(FED_2024, wages="85000")
    assert e.resolved["fed.2024.se.total"] == Decimal("0")
    assert e.resolved["fed.2024.tax.total_liability"] == e.resolved["fed.2024.tax.after_credits"]
    assert run.output.refund_or_owed == -e.resolved["fed.2024.tax.after_credits"]


@pytest.mark.parametrize(
    ("pack", "yr", "wage_base"),
    [
        (FED_2023, 2023, "160200"),
        (FED_2024, 2024, "168600"),
        (FED_2025, 2025, "176100"),
    ],
)
def test_wage_base_by_year(pack: RulePack, yr: int, wage_base: str) -> None:
    """Each year's pack caps the SS portion at that year's wage base."""
    e, _ = _run(pack, nec="300000")
    # 300,000 × 92.35% = 277,050 net earnings, above every year's base.
    assert e.resolved[f"fed.{yr}.se.ss_taxable"] == Decimal(wage_base)
    assert e.resolved[f"fed.{yr}.se.ss_tax"] == Decimal(wage_base) * Decimal("0.124")

def test_calculate_route_parses_1099_nec() -> None:
    """The web form's 1099-NEC rows reach the engine and charge SE tax."""
    from fastapi.testclient import TestClient

    from app.services.database import init_db, list_return_runs
    from main import app

    init_db()
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("csrf", "se-csrf")
    resp = client.post(
        "/calculate",
        data={
            "csrf_token": "se-csrf",
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Sole",
            "p_last": "Proprietor",
            "p_1099nec_0_payer": "Client LLC",
            "p_1099nec_0_compensation": "100000",
            "p_1099nec_0_federal_withheld": "0",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    runs, _ = list_return_runs(page=1, page_size=1)
    run_id = str(runs[0]["id"])
    data = client.get(f"/runs/{run_id}/export/json").json()
    assert Decimal(data["output"]["self_employment_tax"]) == Decimal("14130")
    assert Decimal(data["output"]["agi"]) == Decimal("92935.00")
    assert Decimal(data["output"]["refund_or_owed"]) == Decimal("-26417")
