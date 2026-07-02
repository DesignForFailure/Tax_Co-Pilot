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

"""Long-term capital gains preferential rate golden tests (Milestone 17).

Hand-verified against the 2024 Qualified Dividends and Capital Gain Tax
Worksheet (Form 1040 instructions): 0%/15%/20% rate stacking on top of
ordinary income, short-term gains at ordinary rates, Schedule D
short/long netting, qualified dividend treatment, and the worksheet's
final smaller-of comparison against all-ordinary tax.
"""

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED_2024 = RulePack.load(Path("rule_packs/federal/2024"))
FED_2023 = RulePack.load(Path("rule_packs/federal/2023"))
FED_2025 = RulePack.load(Path("rule_packs/federal/2025"))


def _gain(amount: str, long_term: bool) -> Form1099BData:
    return Form1099BData(
        description="lot",
        proceeds=Decimal(amount),
        cost_basis=Decimal("0"),
        is_long_term=long_term,
    )


def _loss(amount: str, long_term: bool) -> Form1099BData:
    return Form1099BData(
        description="lot",
        proceeds=Decimal("0"),
        cost_basis=Decimal(amount),
        is_long_term=long_term,
    )


def _engine(
    pack: RulePack,
    filing_status: FilingStatus,
    wages: str,
    bs: list[Form1099BData] | None = None,
    divs: list[Form1099DIVData] | None = None,
) -> CalculationEngine:
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))],
                form_1099_bs=bs or [],
                form_1099_divs=divs or [],
            )
        ],
    )
    engine = CalculationEngine(pack, inp)
    engine.run()
    return engine


# ─── 2024 golden vectors ───────────────────────────────────────


def test_single_ltcg_split_between_zero_and_fifteen() -> None:
    """Single, $50k wages, $20k LTCG.

    Taxable 55,400 → ordinary 35,400 (tax 4,016). LTCG: 11,625 fits under
    the $47,025 0% ceiling, remaining 8,375 at 15% = 1,256. Total 5,272 —
    not the 7,241 that all-ordinary treatment would charge.
    """
    e = _engine(FED_2024, FilingStatus.SINGLE, "50000", [_gain("20000", True)])
    assert e.resolved["fed.2024.income.preferential"] == Decimal("20000")
    assert e.resolved["fed.2024.income.ordinary"] == Decimal("35400")
    assert e.resolved["fed.2024.tax.ordinary"] == Decimal("4016")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("1256")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("5272")
    assert e.resolved["fed.2024.tax.brackets"] == Decimal("7241")


def test_mfj_ltcg_entirely_in_zero_bracket() -> None:
    """MFJ, $80k wages, $30k LTCG → all preferential income under $94,050."""
    e = _engine(FED_2024, FilingStatus.MFJ, "80000", [_gain("30000", True)])
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("0")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("5632")


def test_single_high_income_ltcg_fifteen_twenty_split() -> None:
    """Single, $500k wages, $100k LTCG.

    Ordinary 485,400 (tax 140,265). LTCG: 33,500 fills to the $518,900
    15% ceiling (5,025), remaining 66,500 at 20% (13,300) → 158,590.
    """
    e = _engine(FED_2024, FilingStatus.SINGLE, "500000", [_gain("100000", True)])
    assert e.resolved["fed.2024.tax.ordinary"] == Decimal("140265")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("18325")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("158590")


def test_short_term_gains_stay_at_ordinary_rates() -> None:
    """Single, $50k wages, $20k STCG → no preferential income at all."""
    e = _engine(FED_2024, FilingStatus.SINGLE, "50000", [_gain("20000", False)])
    assert e.resolved["fed.2024.income.preferential"] == Decimal("0")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("0")
    assert (
        e.resolved["fed.2024.tax.total_before_credits"]
        == e.resolved["fed.2024.tax.brackets"]
        == Decimal("7241")
    )


def test_mixed_short_and_long_term_gains() -> None:
    """$10k LTCG + $5k STCG: only the long-term part is preferential."""
    e = _engine(
        FED_2024,
        FilingStatus.SINGLE,
        "50000",
        [_gain("10000", True), _gain("5000", False)],
    )
    assert e.resolved["fed.2024.income.preferential"] == Decimal("10000")
    # Taxable 50,400; ordinary 40,400 → 1,160 + 12% × 28,800 = 4,616.
    assert e.resolved["fed.2024.tax.ordinary"] == Decimal("4616")
    # 0% ceiling leaves 6,625 free; 3,375 at 15% = 506.25 → 506.
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("506")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("5122")


def test_short_term_loss_nets_against_long_term_gain() -> None:
    """Schedule D netting: $10k LT gain − $4k ST loss → $6k preferential."""
    e = _engine(
        FED_2024,
        FilingStatus.SINGLE,
        "50000",
        [_gain("10000", True), _loss("4000", False)],
    )
    assert e.resolved["fed.2024.income.net_capital_gain"] == Decimal("6000")
    assert e.resolved["fed.2024.income.preferential"] == Decimal("6000")


def test_net_capital_loss_has_no_preferential_income() -> None:
    """LT $5k gain − ST $10k loss → net loss; nothing preferential."""
    e = _engine(
        FED_2024,
        FilingStatus.SINGLE,
        "50000",
        [_gain("5000", True), _loss("10000", False)],
    )
    assert e.resolved["fed.2024.income.net_capital_gain"] == Decimal("0")
    assert e.resolved["fed.2024.income.preferential"] == Decimal("0")
    # The capped -3,000 loss still reduces ordinary income (existing rule).
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000")


def test_qualified_dividends_get_preferential_treatment() -> None:
    """Single, $40k wages, $5k ordinary dividends ($3k qualified)."""
    e = _engine(
        FED_2024,
        FilingStatus.SINGLE,
        "40000",
        divs=[
            Form1099DIVData(
                payer_name="Fund",
                ordinary_dividends=Decimal("5000"),
                qualified_dividends=Decimal("3000"),
            )
        ],
    )
    # Taxable 30,400; preferential 3,000 (all under the 0% ceiling).
    assert e.resolved["fed.2024.income.preferential"] == Decimal("3000")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("0")
    # Ordinary 27,400 → 1,160 + 12% × 15,800 = 3,056.
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("3056")


def test_worksheet_smaller_of_clause_picks_all_ordinary_tax() -> None:
    """Preferential dollars in the 12%-bracket band above the 0% ceiling
    would pay 15% stacked; the worksheet's final comparison charges the
    smaller all-ordinary figure instead."""
    e = _engine(FED_2024, FilingStatus.SINGLE, "61625", [_gain("125", True)])
    assert e.resolved["fed.2024.income.ordinary"] == Decimal("47025")
    stacked = e.resolved["fed.2024.tax.ordinary"] + e.resolved["fed.2024.tax.ltcg"]
    assert stacked == Decimal("5430")
    assert e.resolved["fed.2024.tax.brackets"] == Decimal("5426")
    assert e.resolved["fed.2024.tax.total_before_credits"] == Decimal("5426")


def test_return_output_carries_worksheet_total() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"))],
                form_1099_bs=[_gain("20000", True)],
            )
        ],
    )
    run = CalculationEngine(FED_2024, inp).run()
    assert run.output.tax_before_credits == Decimal("5272")
    assert run.output.federal_tax == Decimal("5272")
    trace_ids = {t.rule_id for t in run.trace}
    assert "fed.2024.tax.ltcg" in trace_ids
    assert "fed.2024.income.preferential" in trace_ids


def test_wages_only_return_is_unchanged_by_ltcg_rules() -> None:
    """Regression: no preferential income → identical to pre-M17 tax."""
    e = _engine(FED_2024, FilingStatus.SINGLE, "85000")
    assert e.resolved["fed.2024.income.preferential"] == Decimal("0")
    assert (
        e.resolved["fed.2024.tax.total_before_credits"]
        == e.resolved["fed.2024.tax.brackets"]
        == Decimal("10541")
    )


# ─── 2023 / 2025 threshold spot checks ─────────────────────────


@pytest.mark.parametrize(
    ("pack", "yr", "t0", "t15"),
    [
        (FED_2023, 2023, "44625", "492300"),
        (FED_2024, 2024, "47025", "518900"),
        (FED_2025, 2025, "48350", "533400"),
    ],
)
def test_single_thresholds_by_year(pack: RulePack, yr: int, t0: str, t15: str) -> None:
    e = _engine(pack, FilingStatus.SINGLE, "50000", [_gain("1000", True)])
    assert e.resolved[f"fed.{yr}.ltcg.threshold_0"] == Decimal(t0)
    assert e.resolved[f"fed.{yr}.ltcg.threshold_15"] == Decimal(t15)


def test_2023_mfj_ltcg_zero_bracket() -> None:
    """MFJ 2023, $75k wages, $20k LTCG: taxable 67,300, ordinary 47,300;
    preferential all under the $89,250 0% ceiling."""
    e = _engine(FED_2023, FilingStatus.MFJ, "75000", [_gain("20000", True)])
    assert e.resolved["fed.2023.tax.ltcg"] == Decimal("0")
    # 2023 MFJ std deduction 27,700; ordinary 47,300 → 2,200 + 12% × 25,300.
    assert e.resolved["fed.2023.income.ordinary"] == Decimal("47300")


def test_2025_single_ltcg_fifteen_percent_band() -> None:
    """Single 2025, $100k wages, $10k LTCG: ordinary income exceeds the
    $48,350 0% ceiling, so the whole gain is taxed at 15%."""
    e = _engine(FED_2025, FilingStatus.SINGLE, "100000", [_gain("10000", True)])
    assert e.resolved["fed.2025.tax.ltcg"] == Decimal("1500")
