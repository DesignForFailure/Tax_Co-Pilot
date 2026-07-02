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

"""Golden tests for the state rule pack corrections.

Hand-verified against: 2024 GA IT-511 (SB 56 standard deduction, 5.39%
flat rate), pre-2024 O.C.G.A. 48-7-20(b) (GA HoH uses the MFJ bracket
schedule), FTB 2024 Schedule Z (CA HoH), NY IT-201 2024 (5.5%/6.0%
middle rates, HoH schedule), and NH RSA 77 (3% I&D tax, final year 2024).
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099DIVData,
    Form1099INTData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

BASE = Path("rule_packs")
FED_2024 = RulePack.load(BASE / "federal" / "2024")
FED_2023 = RulePack.load(BASE / "federal" / "2023")


def _wage_input(
    tax_year: int,
    state: str,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=tax_year,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X",
                        wages=Decimal(wages),
                        federal_withheld=Decimal("0"),
                        state=state,
                        state_wages=Decimal(wages),
                        state_withheld=Decimal("0"),
                    )
                ],
            )
        ],
    )


def test_ga_2024_single_85k_golden() -> None:
    """GA 2024: 85000 AGI - 12000 standard deduction = 73000 taxable.

    73000 x 5.39% = 3934.70 -> 3935. Under the stale pre-SB 56 constants
    (5400 + 2700) the tax was 4145.
    """
    ga = RulePack.load(BASE / "state" / "GA" / "2024")
    run = CalculationEngine(FED_2024, _wage_input(2024, "GA", "85000"), state_packs={"GA": ga}).run()
    out = run.state_outputs[0]
    assert out.state_standard_deduction == Decimal("12000")
    assert out.state_personal_exemption == Decimal("0")
    assert out.state_taxable_income == Decimal("73000")
    assert out.state_tax == Decimal("3935")


def test_ga_2024_mfj_deduction_is_24000() -> None:
    ga = RulePack.load(BASE / "state" / "GA" / "2024")
    inp = _wage_input(2024, "GA", "100000", FilingStatus.MFJ)
    run = CalculationEngine(FED_2024, inp, state_packs={"GA": ga}).run()
    out = run.state_outputs[0]
    assert out.state_standard_deduction == Decimal("24000")


def test_ga_2023_hoh_uses_mfj_bracket_schedule() -> None:
    """GA 2023 HoH, $50k wages: taxable = 50000 - 5400 - 2700 = 41900.

    Pre-2024 O.C.G.A. 48-7-20(b) puts HoH on the MFJ schedule:
    10 + 40 + 60 + 80 + 150 + 5.75% x 31900 (=1834.25) = 2174.25 -> 2174.
    The single schedule would give 2204.
    """
    ga = RulePack.load(BASE / "state" / "GA" / "2023")
    inp = _wage_input(2023, "GA", "50000", FilingStatus.HOH)
    run = CalculationEngine(FED_2023, inp, state_packs={"GA": ga}).run()
    out = run.state_outputs[0]
    assert out.state_taxable_income == Decimal("41900")
    assert out.state_tax == Decimal("2174")


def test_ca_2024_hoh_uses_schedule_z() -> None:
    """CA 2024 HoH, $75k wages: taxable = 75000 - 11080 = 63920.

    Schedule Z: 215.27 + 589.46 (2% on 21527-51000) + 516.80
    (4% on 51000-63920) = 1321.53 -> 1322.
    """
    ca = RulePack.load(BASE / "state" / "CA" / "2024")
    inp = _wage_input(2024, "CA", "75000", FilingStatus.HOH)
    run = CalculationEngine(FED_2024, inp, state_packs={"CA": ca}).run()
    out = run.state_outputs[0]
    assert out.state_taxable_income == Decimal("63920")
    assert out.state_tax == Decimal("1322")


def test_ny_2024_hoh_uses_own_schedule() -> None:
    """NY 2024 HoH, $75k wages: taxable = 75000 - 11200 = 63800.

    HoH schedule: 512.00 + 218.25 + 170.63 + 5.5% x 42900 (=2359.50)
    = 3260.38 -> 3260.
    """
    ny = RulePack.load(BASE / "state" / "NY" / "2024")
    inp = _wage_input(2024, "NY", "75000", FilingStatus.HOH)
    run = CalculationEngine(FED_2024, inp, state_packs={"NY": ny}).run()
    out = run.state_outputs[0]
    assert out.state_taxable_income == Decimal("63800")
    assert out.state_tax == Decimal("3260")


def test_nh_2024_interest_dividends_taxed_at_3_percent() -> None:
    """NH 2024: $5,000 interest + $1,000 dividends - $2,400 exemption
    = $3,600 taxable; 3% = $108. Repealed for 2025, but in force for 2024.
    """
    nh = RulePack.load(BASE / "state" / "NH" / "2024")
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X",
                        wages=Decimal("60000"),
                        federal_withheld=Decimal("0"),
                        state="NH",
                        state_withheld=Decimal("0"),
                    )
                ],
                form_1099_ints=[Form1099INTData(interest_income=Decimal("5000"))],
                form_1099_divs=[Form1099DIVData(ordinary_dividends=Decimal("1000"))],
            )
        ],
    )
    run = CalculationEngine(FED_2024, inp, state_packs={"NH": nh}).run()
    out = run.state_outputs[0]
    assert out.state_taxable_income == Decimal("3600")
    assert out.state_tax == Decimal("108")


def test_nh_2024_wages_only_still_untaxed() -> None:
    nh = RulePack.load(BASE / "state" / "NH" / "2024")
    run = CalculationEngine(
        FED_2024, _wage_input(2024, "NH", "85000"), state_packs={"NH": nh}
    ).run()
    assert run.state_outputs[0].state_tax == Decimal("0")
