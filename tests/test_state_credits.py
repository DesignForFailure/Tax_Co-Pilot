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

"""State credit and city-tax golden tests (Milestone 23).

Hand-verified against: O.C.G.A. 48-7A-3 (Georgia low income credit
schedule), the 2024 IT-201 NYC rate schedule (cumulative amounts $3,264
at $90,000 MFJ and $2,176 at $60,000 HoH match the published schedule),
the 16.75% Yonkers resident surcharge, and FTB's 2024 nonrefundable
renter's credit ($60/$120 with CA AGI ceilings $52,421/$104,842).
"""

from decimal import Decimal
from pathlib import Path

import pytest
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

BASE = Path("rule_packs")
FED = {y: RulePack.load(BASE / "federal" / str(y)) for y in (2023, 2024, 2025)}
STATE = {
    (s, y): RulePack.load(BASE / "state" / s / str(y))
    for s, y in [("GA", 2023), ("GA", 2024), ("GA", 2025), ("CA", 2024), ("NY", 2024)]
}


def _run(
    year: int,
    state: str,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    children: int = 0,
    *,
    nyc: bool = False,
    yonkers: bool = False,
    renter: bool = False,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        qualifying_children=children,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages), state=state)],
            )
        ],
        nyc_full_year_resident=nyc,
        yonkers_full_year_resident=yonkers,
        ca_renter=renter,
    )
    engine = CalculationEngine(FED[year], inp, state_packs={state: STATE[(state, year)]})
    return engine, engine.run()


# ─── Georgia low income credit (O.C.G.A. 48-7A-3) ─────────────


@pytest.mark.parametrize(
    ("wages", "expected"),
    [
        ("5999.99", "26"),
        ("6000", "20"),
        ("7999.99", "20"),
        ("8000", "14"),
        ("9999.99", "14"),
        ("10000", "8"),
        ("14999.99", "8"),
        ("15000", "5"),
        ("19999.99", "5"),
        ("20000", "0"),
        ("25000", "0"),
    ],
)
def test_ga_low_income_credit_bands(wages: str, expected: str) -> None:
    """Every statutory AGI band boundary maps to the right per-exemption amount."""
    e, _ = _run(2024, "GA", wages)
    assert e.resolved["ga.2024.credits.low_income.per_exemption"] == Decimal(expected)


def test_ga_low_income_credit_reduces_balance_due() -> None:
    """Single, $15k wages: GA tax $162 (3,000 × 5.39%), credit $5 → owes $157."""
    e, run = _run(2024, "GA", "15000")
    assert e.resolved["ga.2024.tax"] == Decimal("162")
    assert e.resolved["ga.2024.credits.low_income"] == Decimal("5")
    st = run.state_outputs[0]
    assert st.state_credits == Decimal("5")
    assert st.state_refund_or_owed == Decimal("-157")


def test_ga_low_income_credit_capped_at_tax() -> None:
    """Single, $5k wages: taxable income is zero, so the $26 credit caps at $0."""
    e, run = _run(2024, "GA", "5000")
    assert e.resolved["ga.2024.credits.low_income.per_exemption"] == Decimal("26")
    assert e.resolved["ga.2024.credits.low_income"] == Decimal("0")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("0")


def test_ga_exemption_count_includes_spouse_and_children() -> None:
    """MFJ + 3 children at $8k AGI: 5 exemptions × $14 band (capped at $0 tax)."""
    e, _ = _run(2024, "GA", "8000", FilingStatus.MFJ, children=3)
    assert e.resolved["ga.2024.credits.low_income.exemptions"] == Decimal("5")
    assert e.resolved["ga.2024.credits.low_income.per_exemption"] == Decimal("14")


def test_ga_2023_credit_with_graduated_brackets() -> None:
    """GA 2023 single, $15k wages: taxable $6,900 → tax $225, credit $5 → owes $220."""
    e, run = _run(2023, "GA", "15000")
    assert e.resolved["ga.2023.tax"] == Decimal("225")
    assert e.resolved["ga.2023.credits.low_income"] == Decimal("5")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-220")


def test_ga_2025_credit_with_519_flat_rate() -> None:
    """GA 2025 single, $15k wages: taxable $3,000 → tax $156, credit $5 → owes $151."""
    e, run = _run(2025, "GA", "15000")
    assert e.resolved["ga.2025.tax"] == Decimal("156")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-151")


# ─── New York City resident tax and Yonkers surcharge ─────────


def test_nyc_resident_tax_single() -> None:
    """Single, $58k wages: NY taxable $50k → state tax $2,585, NYC tax $1,813."""
    e, run = _run(2024, "NY", "58000", nyc=True)
    assert e.resolved["ny.2024.tax"] == Decimal("2585")
    assert e.resolved["ny.2024.city_tax.nyc.base"] == Decimal("1813.17")
    assert e.resolved["ny.2024.city_tax.nyc"] == Decimal("1813")
    st = run.state_outputs[0]
    assert st.state_city_tax == Decimal("1813")
    assert st.state_refund_or_owed == Decimal("-4398")


def test_nyc_mfj_matches_published_schedule() -> None:
    """MFJ at exactly $90k NYC taxable income owes $3,264 per the rate schedule."""
    e, _ = _run(2024, "NY", "106050", FilingStatus.MFJ, nyc=True)
    assert e.resolved["ny.2024.taxable_income"] == Decimal("90000")
    assert e.resolved["ny.2024.city_tax.nyc"] == Decimal("3264")


def test_nyc_hoh_matches_published_schedule() -> None:
    """HoH at exactly $60k NYC taxable income owes $2,176 per the rate schedule."""
    e, _ = _run(2024, "NY", "71200", FilingStatus.HOH, nyc=True)
    assert e.resolved["ny.2024.taxable_income"] == Decimal("60000")
    assert e.resolved["ny.2024.city_tax.nyc"] == Decimal("2176")


def test_yonkers_surcharge_is_1675_percent_of_state_tax() -> None:
    """Single, $58k wages: $2,585 × 16.75% = $432.99 → $433."""
    e, run = _run(2024, "NY", "58000", yonkers=True)
    assert e.resolved["ny.2024.city_tax.yonkers"] == Decimal("433")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-3018")


def test_ny_without_city_flags_is_unchanged() -> None:
    """No residency flags: city tax is zero and the balance matches pre-M23 math."""
    e, run = _run(2024, "NY", "58000")
    assert e.resolved["ny.2024.city_tax"] == Decimal("0")
    assert run.state_outputs[0].state_city_tax == Decimal("0")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-2585")


def test_nyc_and_yonkers_flags_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="New York City and Yonkers"):
        _run(2024, "NY", "58000", nyc=True, yonkers=True)


# ─── California nonrefundable renter's credit ─────────────────


def test_ca_renter_credit_single() -> None:
    """Single renter, $50k wages: CA tax $1,245, renter $60 + personal
    exemption credit $149 (added in M28) → owes $1,036."""
    e, run = _run(2024, "CA", "50000", renter=True)
    assert e.resolved["ca.2024.tax"] == Decimal("1245")
    assert e.resolved["ca.2024.credits.renter"] == Decimal("60")
    st = run.state_outputs[0]
    assert st.state_credits == Decimal("209")
    assert st.state_refund_or_owed == Decimal("-1036")


def test_ca_renter_credit_agi_ceiling_boundary() -> None:
    """Eligible at exactly $52,421 CA AGI; ineligible above it."""
    e, _ = _run(2024, "CA", "52421", renter=True)
    assert e.resolved["ca.2024.credits.renter"] == Decimal("60")
    e, _ = _run(2024, "CA", "52500", renter=True)
    assert e.resolved["ca.2024.credits.renter"] == Decimal("0")


def test_ca_renter_credit_mfj_amount_and_ceiling() -> None:
    """MFJ renters at $100k CA AGI (under $104,842) receive $120."""
    e, _ = _run(2024, "CA", "100000", FilingStatus.MFJ, renter=True)
    assert e.resolved["ca.2024.credits.renter"] == Decimal("120")


def test_ca_renter_credit_requires_renter_flag() -> None:
    e, _ = _run(2024, "CA", "50000")
    assert e.resolved["ca.2024.credits.renter"] == Decimal("0")


def test_ca_renter_credit_capped_at_tax() -> None:
    """Nonrefundable: $6k wages → CA tax $5, so the credit is $5, not $60."""
    e, run = _run(2024, "CA", "6000", renter=True)
    assert e.resolved["ca.2024.tax"] == Decimal("5")
    assert e.resolved["ca.2024.credits.renter"] == Decimal("5")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("0")


# ─── Web form wiring ──────────────────────────────────────────


def test_form_parses_state_flags() -> None:
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Ada",
            "p_last": "Lovelace",
            "p_w2_0_wages": "58000",
            "nyc_resident": "1",
            "ca_renter": "1",
        }
    )
    inp = parse_tax_input_from_form(fd, [2023, 2024, 2025])
    assert inp.nyc_full_year_resident is True
    assert inp.yonkers_full_year_resident is False
    assert inp.ca_renter is True


def test_form_defaults_leave_state_flags_off() -> None:
    fd = FormData(
        {
            "tax_year": "2024",
            "filing_status": "single",
            "p_first": "Ada",
            "p_last": "Lovelace",
            "p_w2_0_wages": "58000",
        }
    )
    inp = parse_tax_input_from_form(fd, [2023, 2024, 2025])
    assert inp.nyc_full_year_resident is False
    assert inp.yonkers_full_year_resident is False
    assert inp.ca_renter is False
