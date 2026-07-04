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

"""Education credit golden tests (Milestone 20).

Hand-verified against Form 8863 / IRC §25A: the per-student AOTC tiers
(100% of the first $2,000 + 25% of the next $2,000), the 40%/60%
refundable split, the per-return LLC (20% of up to $10,000), the shared
MAGI phaseout ($80k–$90k, doubled for MFJ), and MFS ineligibility.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    EducationExpenseData,
    FilingStatus,
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
    wages: str,
    student_expenses: list[str] | None = None,
    llc: str = "0",
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=filing_status,
        llc_expenses=Decimal(llc),
        education_students=[
            EducationExpenseData(student_name=f"Student {i}", qualified_expenses=Decimal(x))
            for i, x in enumerate(student_expenses or [])
        ],
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))],
            )
        ],
    )
    engine = CalculationEngine(pack, inp)
    return engine, engine.run()


def test_aotc_full_credit_single_student() -> None:
    """$4,000 expenses: 2,000 + 25% × 2,000 = $2,500; split $1,000/$1,500."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "50000", ["4000"])
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("2500")
    assert e.resolved["fed.2024.credits.edu.aotc_refundable"] == Decimal("1000")
    assert e.resolved["fed.2024.credits.edu.aotc_nonrefundable"] == Decimal("1500")
    assert run.output.education_credits == Decimal("2500")


def test_aotc_tiers_partial_expenses() -> None:
    """$1,500 expenses: all in the 100% tier → $1,500."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "50000", ["1500"])
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("1500")


def test_aotc_second_tier_at_25_percent() -> None:
    """$3,000 expenses: 2,000 + 25% × 1,000 = $2,250."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "50000", ["3000"])
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("2250")


def test_aotc_caps_per_student() -> None:
    """$9,000 for one student still caps at $2,500."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "50000", ["9000"])
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("2500")


def test_aotc_multiple_students_stack() -> None:
    """Two students ($4,000 + $1,000): $2,500 + $1,000 = $3,500."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "50000", ["4000", "1000"])
    assert e.resolved["fed.2024.credits.edu.aotc_tentative"] == Decimal("3500.00")
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("3500")


def test_aotc_nonrefundable_part_reduces_tax() -> None:
    """Single, $50k, $4k expenses: tax 4,016 − 1,500 nonrefundable = 2,516;
    the $1,000 refundable part then reduces the balance due to 1,516."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "50000", ["4000"])
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("2516")
    assert run.output.refund_or_owed == Decimal("-1516")


def test_refundable_aotc_pays_out_with_zero_tax() -> None:
    """A low-income student owes no tax but still gets 40% of the AOTC."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "8000", ["4000"])
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("0")
    assert e.resolved["fed.2024.credits.edu.aotc_refundable"] == Decimal("1000")
    # Refund = 1,000 refundable AOTC + 612 childless EIC at this income.
    assert run.output.refund_or_owed == Decimal("1612")


def test_llc_twenty_percent_capped_at_10k() -> None:
    """$12,000 LLC expenses → 20% of the $10,000 cap = $2,000."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "50000", llc="12000")
    assert e.resolved["fed.2024.credits.edu.llc"] == Decimal("2000")


def test_llc_is_nonrefundable() -> None:
    """LLC never creates a refund: zero-tax filer gets nothing from it."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "10000", llc="10000")
    assert e.resolved["fed.2024.credits.edu.llc"] == Decimal("2000")
    assert e.resolved["fed.2024.tax.after_credits"] == Decimal("0")
    # Refund equals the childless EIC only — no LLC payout.
    assert run.output.refund_or_owed == e.resolved["fed.2024.credits.eic.final"]


def test_aotc_and_llc_combine() -> None:
    e, run = _run(FED_2024, FilingStatus.SINGLE, "50000", ["4000"], llc="12000")
    assert e.resolved["fed.2024.credits.total"] == Decimal("3500")  # 1,500 + 2,000
    assert run.output.education_credits == Decimal("4500")


def test_phaseout_midpoint_single() -> None:
    """MAGI $85,000: ratio (90,000 − 85,000)/10,000 = 0.5 → AOTC $1,250."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "85000", ["4000"])
    assert e.resolved["fed.2024.credits.edu.ratio"] == Decimal("0.500")
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("1250")


def test_phaseout_midpoint_mfj_uses_doubled_range() -> None:
    """MFJ MAGI $170,000 sits mid-range of $160k–$180k."""
    e, _ = _run(FED_2024, FilingStatus.MFJ, "170000", ["4000"])
    assert e.resolved["fed.2024.credits.edu.ratio"] == Decimal("0.500")


def test_phaseout_ratio_rounds_to_three_places() -> None:
    """Form 8863 line 6 rounds to at least three decimal places."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "84375", ["4000"])
    assert e.resolved["fed.2024.credits.edu.ratio"] == Decimal("0.563")


def test_above_phaseout_ceiling_no_credit() -> None:
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "95000", ["4000"], llc="10000")
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("0")
    assert e.resolved["fed.2024.credits.edu.llc"] == Decimal("0")


def test_mfs_is_ineligible() -> None:
    """MFS filers are barred from both education credits (IRC §25A(g)(6))."""
    e, run = _run(FED_2024, FilingStatus.MFS, "50000", ["4000"], llc="10000")
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("0")
    assert e.resolved["fed.2024.credits.edu.llc"] == Decimal("0")
    assert run.output.education_credits == Decimal("0")


def test_form_mapper_line_29_and_consistency() -> None:
    _, run = _run(FED_2024, FilingStatus.SINGLE, "50000", ["4000"])
    pkt = map_return_run(run)
    assert pkt.form_1040.line_29 == Decimal("1000")
    assert pkt.consistency_errors == []


def test_no_education_inputs_changes_nothing() -> None:
    """Regression: returns without education data are unaffected."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "85000")
    assert e.resolved["fed.2024.credits.edu.aotc"] == Decimal("0")
    assert e.resolved["fed.2024.credits.edu.llc"] == Decimal("0")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("10541")


@pytest.mark.parametrize("pack", [FED_2023, FED_2025])
def test_other_years_share_the_statutory_parameters(pack: RulePack) -> None:
    """The 25A phaseout has been fixed by statute since 2021."""
    yr = pack.tax_year
    e, _ = _run(pack, FilingStatus.SINGLE, "85000", ["4000"])
    assert e.resolved[f"fed.{yr}.credits.edu.ratio"] == Decimal("0.500")
    assert e.resolved[f"fed.{yr}.credits.edu.aotc"] == Decimal("1250")


def test_calculate_route_parses_education_fields() -> None:
    """The web form's education card reaches the engine."""
    from fastapi.testclient import TestClient

    from app.services.database import init_db, list_return_runs
    from main import app

    init_db()
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("csrf", "edu-csrf")
    resp = client.post(
        "/calculate",
        data={
            "csrf_token": "edu-csrf",
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "College",
            "p_last": "Parent",
            "p_w2_0_employer": "Acme",
            "p_w2_0_wages": "50000",
            "edu_0_student": "Kid One",
            "edu_0_expenses": "4000",
            "llc_expenses": "5000",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    runs, _ = list_return_runs(page=1, page_size=1)
    data = client.get(f"/runs/{runs[0]['id']}/export/json").json()
    assert Decimal(data["output"]["education_credits"]) == Decimal("3500")  # 2,500 + 1,000
    snap = data["input_snapshot"]
    assert Decimal(snap["education_students"][0]["qualified_expenses"]) == Decimal("4000")
    assert Decimal(snap["llc_expenses"]) == Decimal("5000")
