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

"""Golden tests for the federal 2024 pack corrections.

Each scenario is hand-verified against the governing worksheet:
- Pub 915 Worksheet 1 (SS taxability: 50%-of-benefits cap, tax-exempt
  interest in provisional income, adjustments subtracted)
- IRC 1211(b) (MFS capital loss limit)
- Form 8812 (CTC phaseout rounds AGI excess UP to the next $1,000)
- Schedule A (noncash charitable capped at 30% of AGI)
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099BData,
    Form1099INTData,
    Form1099SSAData,
    ItemizedDeductionData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


def _taxpayer(**kwargs) -> Taxpayer:  # type: ignore[no-untyped-def]
    return Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B", **kwargs)


def test_ss_lower_tier_capped_at_half_of_benefits() -> None:
    """Single, $30k wages, $4k SS. Provisional $32,000.

    Lower tier = min((32000-25000)*0.5=3500, (34000-25000)*0.5=4500,
    0.5*4000=2000) = 2000. Upper tier 0. Taxable SS = min(3400, 2000) = 2000.
    The old rule (no benefits cap) yielded 3400.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            _taxpayer(
                w2s=[W2Data(employer_name="X", wages=Decimal("30000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("4000"))],
            )
        ],
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    assert engine.resolved["fed.2024.gross_income.social_security"] == Decimal("2000.00")


def test_tax_exempt_interest_raises_provisional_income() -> None:
    """Single, $20k wages, $30k SS, $10k muni interest.

    Provisional = 20000 + 10000 + 15000 = 45000 (> $34,000 upper).
    Lower = min(10000, 4500, 15000) = 4500; upper = (45000-34000)*0.85 = 9350.
    Taxable SS = min(25500, 13850) = 13850. Without tax-exempt interest the
    provisional was 35000 and taxable SS only 5350.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            _taxpayer(
                w2s=[W2Data(employer_name="X", wages=Decimal("20000"))],
                form_1099_ints=[
                    Form1099INTData(
                        interest_income=Decimal("0"),
                        tax_exempt_interest=Decimal("10000"),
                    )
                ],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("30000"))],
            )
        ],
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    assert engine.resolved["fed.2024.gross_income.ss_provisional"] == Decimal("45000.00")
    assert engine.resolved["fed.2024.gross_income.social_security"] == Decimal("13850.00")


def test_adjustments_reduce_provisional_income() -> None:
    """IRA contributions reduce provisional income (Pub 915 WS1 line 8)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            _taxpayer(
                w2s=[W2Data(employer_name="X", wages=Decimal("40000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("10000"))],
            )
        ],
        adjustments=AdjustmentsData(ira_contributions=Decimal("5000")),
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    # 40000 + 5000 (half SS) - 5000 (IRA) = 40000
    assert engine.resolved["fed.2024.gross_income.ss_provisional"] == Decimal("40000.00")


def test_mfs_capital_loss_limited_to_1500() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFS,
        taxpayers=[
            _taxpayer(
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"))],
                form_1099_bs=[
                    Form1099BData(
                        description="loss",
                        proceeds=Decimal("1000"),
                        cost_basis=Decimal("6000"),
                    )
                ],
            )
        ],
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    assert engine.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-1500.00")


def test_single_capital_loss_still_limited_to_3000() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            _taxpayer(
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"))],
                form_1099_bs=[
                    Form1099BData(
                        description="loss",
                        proceeds=Decimal("1000"),
                        cost_basis=Decimal("6000"),
                    )
                ],
            )
        ],
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    assert engine.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000.00")


def test_ctc_phaseout_rounds_excess_up_to_next_thousand() -> None:
    """Single, AGI $200,100, 1 child.

    Form 8812: excess $100 rounds UP to $1,000 -> $50 reduction.
    CTC = 2000 - 50 = 1950. The old smooth formula gave 2000 - 5 = 1995.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[_taxpayer(w2s=[W2Data(employer_name="X", wages=Decimal("200100"))])],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.child_tax_credit == Decimal("1950")


def test_ctc_phaseout_exact_thousand_unchanged() -> None:
    """AGI exactly $20,000 over: 20 units x $50 = $1,000 (same as before)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[_taxpayer(w2s=[W2Data(employer_name="X", wages=Decimal("220000"))])],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.child_tax_credit == Decimal("1000")


def test_noncash_charitable_capped_at_30_percent_agi() -> None:
    """Wages $100,000, noncash gifts $50,000 -> capped at $30,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[_taxpayer(w2s=[W2Data(employer_name="X", wages=Decimal("100000"))])],
        itemized_deductions=ItemizedDeductionData(
            charitable_noncash=Decimal("50000"),
        ),
    )
    engine = CalculationEngine(FED, inp)
    engine.run()
    assert engine.resolved["fed.2024.itemized.charitable"] == Decimal("30000.00")
