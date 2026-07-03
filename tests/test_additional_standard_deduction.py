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

"""Additional standard deduction golden tests (Milestone 25).

Hand-verified against IRC §63(f) / Rev. Procs. 2022-38, 2023-34, 2024-40:
per checked age-65+/blind condition, $1,850/$1,950/$2,000 for unmarried
filers (single/HoH) and $1,500/$1,550/$1,600 for married filers
(MFJ/MFS/QSS) across 2023/2024/2025. Also covers the Georgia low income
credit's extra exemption per taxpayer 65+ (IT-511 worksheet line 3),
previously a documented limitation.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    ItemizedDeductionData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.route_helpers.form_parsing import parse_tax_input_from_form

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}
GA_2024 = RulePack.load(Path("rule_packs/state/GA/2024"))


def _input(
    year: int,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    *,
    p65: bool = False,
    pblind: bool = False,
    s65: bool = False,
    sblind: bool = False,
    itemized: ItemizedDeductionData | None = None,
    state: str = "",
) -> TaxReturnInput:
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
        taxpayers.append(
            Taxpayer(
                role=TaxpayerRole.SPOUSE,
                first_name="Pat",
                last_name="Vector",
                is_65_or_older=s65,
                is_blind=sblind,
            )
        )
    return TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        itemized_deductions=itemized or ItemizedDeductionData(),
    )


def _run(inp: TaxReturnInput) -> tuple[CalculationEngine, ReturnRun]:
    engine = CalculationEngine(FED[inp.tax_year], inp)
    return engine, engine.run()


def test_single_65_gets_one_addition() -> None:
    """Single 65+: $14,600 + $1,950 = $16,550 → taxable $43,450 → tax $4,982."""
    e, run = _run(_input(2024, "60000", p65=True))
    assert e.resolved["fed.2024.deductions.additional_standard"] == Decimal("1950")
    assert e.resolved["fed.2024.deductions.standard_total"] == Decimal("16550")
    assert e.resolved["fed.2024.taxable_income"] == Decimal("43450")
    assert e.resolved["fed.2024.tax.brackets"] == Decimal("4982")
    assert run.output.standard_deduction == Decimal("16550")


def test_single_65_and_blind_gets_two_additions() -> None:
    e, _ = _run(_input(2024, "60000", p65=True, pblind=True))
    assert e.resolved["fed.2024.deductions.standard_total"] == Decimal("18500")


def test_mfj_three_boxes_at_married_rate() -> None:
    """Both spouses 65+, one blind: 3 × $1,550 = $4,650 on top of $29,200."""
    e, _ = _run(_input(2024, "90000", FilingStatus.MFJ, p65=True, pblind=True, s65=True))
    assert e.resolved["fed.2024.deductions.additional_standard"] == Decimal("4650")
    assert e.resolved["fed.2024.deductions.standard_total"] == Decimal("33850")


def test_no_boxes_leaves_deduction_unchanged() -> None:
    e, run = _run(_input(2024, "60000"))
    assert e.resolved["fed.2024.deductions.standard_total"] == Decimal("14600")
    assert run.output.standard_deduction == Decimal("14600")


def test_itemized_comparison_uses_the_full_standard_total() -> None:
    """$17k itemized beats single-65+ ($16,550) but loses to 65+blind ($18,500)."""
    item = ItemizedDeductionData(mortgage_interest=Decimal("17000"))
    e, _ = _run(_input(2024, "60000", p65=True, itemized=item))
    assert e.resolved["fed.2024.deductions.applied"] == Decimal("17000.00")
    e, _ = _run(_input(2024, "60000", p65=True, pblind=True, itemized=item))
    assert e.resolved["fed.2024.deductions.applied"] == Decimal("18500.00")


@pytest.mark.parametrize(
    ("year", "single_addition", "married_addition"),
    [
        (2023, "1850", "1500"),
        (2024, "1950", "1550"),
        (2025, "2000", "1600"),
    ],
)
def test_rev_proc_amounts_by_year(year: int, single_addition: str, married_addition: str) -> None:
    e, _ = _run(_input(year, "60000", p65=True))
    assert e.resolved[f"fed.{year}.deductions.additional_standard"] == Decimal(single_addition)
    e, _ = _run(_input(year, "90000", FilingStatus.MFJ, p65=True))
    assert e.resolved[f"fed.{year}.deductions.additional_standard"] == Decimal(married_addition)


def test_ga_low_income_credit_counts_seniors() -> None:
    """GA single 65+ at $15k AGI: 2 exemptions × $5 band = $10 credit."""
    inp = _input(2024, "15000", p65=True, state="GA")
    engine = CalculationEngine(FED[2024], inp, state_packs={"GA": GA_2024})
    engine.run()
    assert engine.resolved["ga.2024.credits.low_income.exemptions"] == Decimal("2")
    assert engine.resolved["ga.2024.credits.low_income"] == Decimal("10")


def test_form_parses_age_blind_flags() -> None:
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "mfj",
            "p_first": "Ada",
            "p_last": "Lovelace",
            "p_w2_0_wages": "60000",
            "p_65": "1",
            "s_first": "Grace",
            "s_last": "Hopper",
            "s_blind": "1",
        }
    )
    inp = parse_tax_input_from_form(fd, [2023, 2024, 2025])
    assert inp.taxpayers[0].is_65_or_older is True
    assert inp.taxpayers[0].is_blind is False
    assert inp.taxpayers[1].is_blind is True
    assert inp.age_blind_boxes() == Decimal("2")
    assert inp.seniors_count() == Decimal("1")


def test_spouse_with_only_age_flag_still_counts() -> None:
    """A box checked for an otherwise-empty spouse must not be silently dropped."""
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "mfj",
            "p_first": "Ada",
            "p_last": "Lovelace",
            "p_w2_0_wages": "60000",
            "s_65": "1",
        }
    )
    inp = parse_tax_input_from_form(fd, [2023, 2024, 2025])
    assert len(inp.taxpayers) == 2
    assert inp.age_blind_boxes() == Decimal("1")
