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

"""Capital-loss carryover golden tests (Milestone 30).

Hand-verified against Schedule D: prior-year short/long-term carryovers
enter the netting as lines 6 and 14, flow through the IRC §1211(b)
loss limit and the QDCGT preferential-rate base, and the informational
carryover-to-next-year follows the Capital Loss Carryover Worksheet's
short-term-first ordering. The worksheet's negative-taxable-income
adjustment (less loss "used" when income is already negative) is
unmodeled and documented on the rule.
"""

from decimal import Decimal
from pathlib import Path

from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.route_helpers.form_parsing import parse_tax_input_from_form

FED = RulePack.load(Path("rule_packs/federal/2024"))


def _lot(amount: str, long_term: bool) -> Form1099BData:
    value = Decimal(amount)
    return Form1099BData(
        description="lot",
        proceeds=value if value > 0 else Decimal("0"),
        cost_basis=Decimal("0") if value > 0 else -value,
        is_long_term=long_term,
    )


def _run(
    st: str | None = None,
    lt: str | None = None,
    st_co: str = "0",
    lt_co: str = "0",
    filing_status: FilingStatus = FilingStatus.SINGLE,
) -> tuple[CalculationEngine, ReturnRun]:
    lots = []
    if st:
        lots.append(_lot(st, long_term=False))
    if lt:
        lots.append(_lot(lt, long_term=True))
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal("50000"))],
                form_1099_bs=lots,
            )
        ],
        short_term_loss_carryover=Decimal(st_co),
        long_term_loss_carryover=Decimal(lt_co),
    )
    engine = CalculationEngine(FED, inp)
    return engine, engine.run()


def test_lt_carryover_nets_against_current_gain() -> None:
    """$10k LT gain − $4k carryover: $6k preferential, nothing carries."""
    e, _ = _run(lt="10000", lt_co="4000")
    assert e.resolved["fed.2024.income.long_term_net"] == Decimal("6000.00")
    assert e.resolved["fed.2024.income.net_capital_gain"] == Decimal("6000.00")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("6000.00")
    assert e.resolved["fed.2024.carryover.next_total"] == Decimal("0.00")


def test_st_carryover_through_the_limit_to_next_year() -> None:
    """$1k ST gain − $5k carryover = −$4k: −$3k allowed, $1k ST carries."""
    e, run = _run(st="1000", st_co="5000")
    assert e.resolved["fed.2024.income.short_term_net"] == Decimal("-4000.00")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000.00")
    assert e.resolved["fed.2024.carryover.next_short"] == Decimal("1000.00")
    assert e.resolved["fed.2024.carryover.next_long"] == Decimal("0.00")
    assert run.output.capital_loss_carryover_next == Decimal("1000.00")


def test_carryover_with_no_current_year_sales() -> None:
    """A $10k LT carryover alone: −$3k against wages, $7k LT carries."""
    e, _ = _run(lt_co="10000")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000.00")
    assert e.resolved["fed.2024.carryover.next_short"] == Decimal("0.00")
    assert e.resolved["fed.2024.carryover.next_long"] == Decimal("7000.00")


def test_st_carryover_reduces_preferential_gain() -> None:
    """$20k LT gain with a $5k ST carryover: only $15k gets LTCG rates."""
    e, _ = _run(lt="20000", st_co="5000")
    assert e.resolved["fed.2024.income.net_capital_gain"] == Decimal("15000.00")


def test_worksheet_orders_short_term_losses_first() -> None:
    """ST −$10k, LT +$4k: the $3k limit absorbs ST after LT netting,
    leaving $3k of ST (10 − 4 − 3) and no LT to carry."""
    e, _ = _run(st="-10000", lt="4000")
    assert e.resolved["fed.2024.carryover.used"] == Decimal("3000.00")
    assert e.resolved["fed.2024.carryover.next_short"] == Decimal("3000.00")
    assert e.resolved["fed.2024.carryover.next_long"] == Decimal("0.00")


def test_mixed_losses_split_st_first() -> None:
    """ST −$2k + LT −$5k: the limit takes all ST plus $1k LT → $4k LT carries."""
    e, _ = _run(st="-2000", lt="-5000")
    assert e.resolved["fed.2024.carryover.next_short"] == Decimal("0.00")
    assert e.resolved["fed.2024.carryover.next_long"] == Decimal("4000.00")


def test_mfs_limit_absorbs_only_1500() -> None:
    e, _ = _run(st_co="5000", filing_status=FilingStatus.MFS)
    assert e.resolved["fed.2024.carryover.used"] == Decimal("1500.00")
    assert e.resolved["fed.2024.carryover.next_short"] == Decimal("3500.00")


def test_no_carryover_leaves_gains_unchanged() -> None:
    e, _ = _run(st="2000", lt="3000")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("5000.00")
    assert e.resolved["fed.2024.carryover.next_total"] == Decimal("0.00")


def test_form_parsing_round_trips_carryovers() -> None:
    fd = FormData(
        [
            ("tax_year", "2024"),
            ("filing_status", "single"),
            ("p_first", "A"),
            ("p_last", "B"),
            ("p_w2_0_employer", "Acme"),
            ("p_w2_0_wages", "50000"),
            ("st_loss_carryover", "1200"),
            ("lt_loss_carryover", "3400"),
        ]
    )
    inp = parse_tax_input_from_form(fd, [2024])
    assert inp.short_term_loss_carryover == Decimal("1200.00")
    assert inp.long_term_loss_carryover == Decimal("3400.00")
