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

"""W-2 Box 5/6 and Form 8959 Part IV golden tests (Milestone 29).

Hand-verified against Form 8959: the Additional Medicare Tax base is
Medicare wages (Box 5, which pre-tax retirement deferrals do NOT
reduce), and Part IV credits employer-withheld surtax — Box 6 in
excess of 1.45% of Box 5 — as federal withholding on 1040 line 25c.
A blank Box 5 falls back to Box 1 per W-2 (the M27 behavior).
"""

from decimal import Decimal
from pathlib import Path

import pytest
from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099NECData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.route_helpers.form_parsing import parse_w2s
from app.services.csv_import import import_csv
from app.services.form_mapper import map_return_run

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}


def _run(
    year: int = 2024,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    box1: str = "0",
    box2: str = "0",
    box5: str = "0",
    box6: str = "0",
    nec: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=year,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[
                    W2Data(
                        employer_name="Acme",
                        wages=Decimal(box1),
                        federal_withheld=Decimal(box2),
                        medicare_wages=Decimal(box5),
                        medicare_tax=Decimal(box6),
                    )
                ],
                form_1099_necs=(
                    [Form1099NECData(payer_name="Client", nonemployee_compensation=Decimal(nec))]
                    if nec
                    else []
                ),
            )
        ],
    )
    engine = CalculationEngine(FED[year], inp)
    return engine, engine.run()


def test_surtax_base_is_box_5_not_box_1() -> None:
    """$230k Box 1 with $250k Box 5 (401(k) deferral): surtax on Box 5."""
    e, _ = _run(box1="230000", box5="250000", box6="4075")
    assert e.resolved["fed.2024.addl_medicare.wage_excess"] == Decimal("50000.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("450")


def test_part_iv_withholding_credit() -> None:
    """Box 6 $4,075 − 1.45% × $250k = $450 credited as withholding."""
    e, run = _run(box1="230000", box2="40000", box5="250000", box6="4075")
    assert e.resolved["fed.2024.addl_medicare.regular_withholding"] == Decimal("3625.00")
    assert e.resolved["fed.2024.addl_medicare.withholding"] == Decimal("450.00")
    assert e.resolved["fed.2024.total_withholding"] == Decimal("40450.00")
    pkt = map_return_run(run)
    assert pkt.form_1040.line_25d == Decimal("40450.00")
    assert pkt.consistency_errors == []


def test_blank_box_5_falls_back_to_box_1() -> None:
    """Box 5 left blank: Box 1 stands in per W-2 (pre-M29 behavior)."""
    e, _ = _run(box1="250000")
    assert e.resolved["fed.2024.addl_medicare.wage_excess"] == Decimal("50000.00")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("450")
    assert e.resolved["fed.2024.addl_medicare.withholding"] == Decimal("0.00")


def test_under_withheld_box_6_never_goes_negative() -> None:
    e, _ = _run(box1="100000", box5="100000", box6="1000")
    assert e.resolved["fed.2024.addl_medicare.withholding"] == Decimal("0.00")


def test_mfj_employer_overwithholding_refunds() -> None:
    """Employers withhold the surtax above $200k regardless of filing
    status; an MFJ couple under the $250k threshold gets it back."""
    e, run = _run(filing_status=FilingStatus.MFJ, box1="220000", box5="220000", box6="3370")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("0")
    assert e.resolved["fed.2024.addl_medicare.withholding"] == Decimal("180.00")
    assert run.output.total_withholding == Decimal("180.00")


def test_se_threshold_reduced_by_box_5() -> None:
    """Form 8959 line 12 uses Medicare wages: $170k Box 5 leaves a $30k
    SE threshold, so $62,350 of the $92,350 SE earnings is surtaxed."""
    e, _ = _run(box1="150000", box5="170000", nec="100000")
    assert e.resolved["fed.2024.addl_medicare.se_threshold"] == Decimal("30000.00")
    assert e.resolved["fed.2024.addl_medicare.se_excess"] == Decimal("62350.00")


@pytest.mark.parametrize("year", [2023, 2025])
def test_wiring_across_years(year: int) -> None:
    e, _ = _run(year=year, box1="230000", box5="250000", box6="4075")
    assert e.resolved[f"fed.{year}.addl_medicare.final"] == Decimal("450")
    assert e.resolved[f"fed.{year}.addl_medicare.withholding"] == Decimal("450.00")


def test_form_parsing_round_trips_box_5_and_6() -> None:
    fd = FormData(
        [
            ("p_w2_0_employer", "Acme"),
            ("p_w2_0_wages", "230000"),
            ("p_w2_0_medicare_wages", "250000"),
            ("p_w2_0_medicare_withheld", "4075"),
        ]
    )
    w2s = parse_w2s(fd, "p_w2")
    assert w2s[0].medicare_wages == Decimal("250000.00")
    assert w2s[0].medicare_tax == Decimal("4075.00")


def test_csv_import_accepts_medicare_columns() -> None:
    csv_text = (
        "employer_name,wages,federal_withheld,medicare_wages,medicare_tax\n"
        "Acme,230000,40000,250000,4075\n"
    )
    records, errors = import_csv(csv_text, "W2")
    assert errors == []
    w2 = records[0]
    assert isinstance(w2, W2Data)
    assert w2.medicare_wages == Decimal("250000.00")
    assert w2.medicare_tax == Decimal("4075.00")
