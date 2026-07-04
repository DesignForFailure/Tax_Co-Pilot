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

"""Net Investment Income Tax golden tests (Milestone 22).

Hand-verified against Form 8960 / IRC §1411: 3.8% of the smaller of net
investment income or the MAGI excess over the statutory thresholds
($200k single/HoH, $250k MFJ/QSS, $125k MFS), with capital losses
reducing (but never negating) investment income.
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
    Form1099INTData,
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
    filing_status: FilingStatus,
    wages: str,
    interest: str | None = None,
    dividends: str | None = None,
    capital_loss: str | None = None,
    nec: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=pack.tax_year,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))],
                form_1099_ints=(
                    [Form1099INTData(payer_name="Bank", interest_income=Decimal(interest))]
                    if interest
                    else []
                ),
                form_1099_divs=(
                    [Form1099DIVData(payer_name="Fund", ordinary_dividends=Decimal(dividends))]
                    if dividends
                    else []
                ),
                form_1099_bs=(
                    [
                        Form1099BData(
                            description="loss",
                            proceeds=Decimal("0"),
                            cost_basis=Decimal(capital_loss),
                        )
                    ]
                    if capital_loss
                    else []
                ),
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


def test_niit_when_nii_is_the_smaller_amount() -> None:
    """Single, $250k wages + $30k interest: excess $80k > NII $30k → $1,140."""
    e, run = _run(FED_2024, FilingStatus.SINGLE, "250000", interest="30000")
    assert e.resolved["fed.2024.niit.investment_income"] == Decimal("30000.00")
    assert e.resolved["fed.2024.niit.magi_excess"] == Decimal("80000.00")
    assert e.resolved["fed.2024.niit.final"] == Decimal("1140")
    assert run.output.net_investment_income_tax == Decimal("1140")


def test_niit_when_magi_excess_is_the_smaller_amount() -> None:
    """Single, $190k wages + $30k interest: excess $20k < NII $30k → $760."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "190000", interest="30000")
    assert e.resolved["fed.2024.niit.final"] == Decimal("760")


def test_no_niit_below_threshold() -> None:
    e, run = _run(FED_2024, FilingStatus.SINGLE, "150000", interest="30000")
    assert e.resolved["fed.2024.niit.final"] == Decimal("0")
    assert run.output.net_investment_income_tax == Decimal("0")


def test_mfj_threshold_250k() -> None:
    """MFJ, $240k wages + $20k dividends: AGI $260k → excess $10k → $380."""
    e, _ = _run(FED_2024, FilingStatus.MFJ, "240000", dividends="20000")
    assert e.resolved["fed.2024.niit.threshold"] == Decimal("250000")
    assert e.resolved["fed.2024.niit.final"] == Decimal("380")


def test_mfs_threshold_125k() -> None:
    """MFS, $130k wages + $10k interest: AGI $140k → excess $15k, NII $10k → $380."""
    e, _ = _run(FED_2024, FilingStatus.MFS, "130000", interest="10000")
    assert e.resolved["fed.2024.niit.threshold"] == Decimal("125000")
    assert e.resolved["fed.2024.niit.final"] == Decimal("380")


def test_capital_loss_reduces_investment_income() -> None:
    """The capped −$3,000 loss offsets interest inside NII: $10k − $3k = $7k."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "300000", interest="10000", capital_loss="5000")
    assert e.resolved["fed.2024.niit.investment_income"] == Decimal("7000.00")
    assert e.resolved["fed.2024.niit.final"] == Decimal("266")


def test_investment_income_floors_at_zero() -> None:
    """A pure capital loss can never produce negative NIIT."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "300000", capital_loss="5000")
    assert e.resolved["fed.2024.niit.investment_income"] == Decimal("0.00")
    assert e.resolved["fed.2024.niit.final"] == Decimal("0")


def test_wage_income_alone_never_triggers_niit() -> None:
    """High wages with no investment income: excess is huge, NII is zero."""
    e, _ = _run(FED_2024, FilingStatus.SINGLE, "500000")
    assert e.resolved["fed.2024.niit.final"] == Decimal("0")


def test_niit_composes_with_se_tax_on_line_23() -> None:
    """Schedule 2 aggregates SE tax + NIIT into 1040 line 23."""
    e, run = _run(
        FED_2024, FilingStatus.SINGLE, "250000", interest="30000", nec="50000"
    )
    se = e.resolved["fed.2024.se.total"]
    niit = e.resolved["fed.2024.niit.final"]
    # This household also owes Additional Medicare Tax since M27.
    medicare = e.resolved["fed.2024.addl_medicare.final"]
    assert e.resolved["fed.2024.tax.other_taxes"] == se + niit + medicare
    pkt = map_return_run(run)
    assert pkt.form_1040.line_23 == se + niit + medicare
    assert pkt.consistency_errors == []


def test_refund_settles_against_liability_including_niit() -> None:
    e, run = _run(FED_2024, FilingStatus.SINGLE, "250000", interest="30000")
    liability = e.resolved["fed.2024.tax.total_liability"]
    # $1,140 NIIT plus the $450 Additional Medicare Tax added in M27.
    assert liability == e.resolved["fed.2024.tax.after_credits"] + Decimal("1590")
    assert run.output.refund_or_owed == -liability


@pytest.mark.parametrize("pack", [FED_2023, FED_2025])
def test_thresholds_are_statutory_across_years(pack: RulePack) -> None:
    """IRC §1411 thresholds are not inflation-indexed."""
    yr = pack.tax_year
    e, _ = _run(pack, FilingStatus.SINGLE, "250000", interest="30000")
    assert e.resolved[f"fed.{yr}.niit.threshold"] == Decimal("200000")
    assert e.resolved[f"fed.{yr}.niit.final"] == Decimal("1140")
