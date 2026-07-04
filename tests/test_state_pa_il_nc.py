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

"""Pennsylvania, Illinois, and North Carolina pack golden tests (M32).

Hand-verified against: the PA-40 flat 3.07% on class income (losses in
one class never offset another; no deductions or exemptions; Social
Security untaxed by construction), the 2024 IL-1040 $2,775 exemption
allowance (FY Bulletin 2024-02; $1,000 senior/blind additions; nothing
above $250k/$500k AGI) at the flat 4.95%, and the 2024 D-400 flat 4.5%
with the $12,750/$25,500/$19,125 standard deduction — plus the M31
apportionment machinery working for the new packs unchanged.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Form1099INTData,
    Form1099SSAData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))
STATE = {s: RulePack.load(Path(f"rule_packs/state/{s}/2024")) for s in ("PA", "IL", "NC", "GA")}


def _run(
    state: str,
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    children: int = 0,
    *,
    p65: bool = False,
    interest: str | None = None,
    capital_loss: str | None = None,
    ss_benefits: str | None = None,
) -> tuple[CalculationEngine, ReturnRun]:
    tp = Taxpayer(
        role=TaxpayerRole.PRIMARY,
        first_name="Golden",
        last_name="Vector",
        w2s=[W2Data(employer_name="Acme", wages=Decimal(wages), state=state)],
        is_65_or_older=p65,
    )
    if interest:
        tp.form_1099_ints.append(
            Form1099INTData(payer_name="Bank", interest_income=Decimal(interest))
        )
    if capital_loss:
        tp.form_1099_bs.append(
            Form1099BData(
                description="lot",
                proceeds=Decimal("0"),
                cost_basis=Decimal(capital_loss),
                is_long_term=True,
            )
        )
    if ss_benefits:
        tp.form_1099_ssas.append(Form1099SSAData(total_benefits=Decimal(ss_benefits)))
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        qualifying_children=children,
        state_of_residence=state,
        taxpayers=[tp],
    )
    engine = CalculationEngine(FED, inp, state_packs={state: STATE[state]})
    return engine, engine.run()


# ─── Pennsylvania ─────────────────────────────────────────────


def test_pa_flat_307_on_wages() -> None:
    e, run = _run("PA", "50000")
    assert e.resolved["pa.2024.tax"] == Decimal("1535")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-1535")


def test_pa_interest_joins_the_base() -> None:
    e, _ = _run("PA", "50000", interest="1000")
    assert e.resolved["pa.2024.tax"] == Decimal("1566")


def test_pa_class_loss_cannot_offset_compensation() -> None:
    """A $5k capital loss floors at zero instead of reducing wages."""
    e, _ = _run("PA", "50000", capital_loss="5000")
    assert e.resolved["pa.2024.agi"] == Decimal("50000.00")
    assert e.resolved["pa.2024.tax"] == Decimal("1535")


# ─── Illinois ─────────────────────────────────────────────────


def test_il_exemption_and_flat_495() -> None:
    """(50,000 − 2,775) × 4.95% = $2,337.64 → $2,338."""
    e, _ = _run("IL", "50000")
    assert e.resolved["il.2024.personal_exemption"] == Decimal("2775")
    assert e.resolved["il.2024.tax"] == Decimal("2338")


def test_il_dependents_and_senior_additions() -> None:
    e, _ = _run("IL", "50000", children=2)
    assert e.resolved["il.2024.personal_exemption"] == Decimal("8325")
    assert e.resolved["il.2024.tax"] == Decimal("2063")
    e, _ = _run("IL", "50000", p65=True)
    assert e.resolved["il.2024.personal_exemption"] == Decimal("3775")


def test_il_exemption_agi_limit_boundary() -> None:
    """Eligible at exactly $250k AGI, disallowed above it."""
    e, _ = _run("IL", "250000")
    assert e.resolved["il.2024.personal_exemption"] == Decimal("2775")
    e, _ = _run("IL", "260000")
    assert e.resolved["il.2024.personal_exemption"] == Decimal("0")


def test_il_never_taxes_social_security() -> None:
    """The federally taxed SS portion is subtracted from the IL base."""
    e, _ = _run("IL", "30000", ss_benefits="20000")
    fed_ss = e.resolved["fed.2024.gross_income.social_security"]
    assert fed_ss > 0
    assert e.resolved["il.2024.agi"] == Decimal("30000.00")


# ─── North Carolina ───────────────────────────────────────────


def test_nc_flat_45_with_standard_deduction() -> None:
    """(50,000 − 12,750) × 4.5% = $1,676.25 → $1,676."""
    e, _ = _run("NC", "50000")
    assert e.resolved["nc.2024.standard_deduction"] == Decimal("12750")
    assert e.resolved["nc.2024.tax"] == Decimal("1676")


def test_nc_mfj_deduction() -> None:
    """MFJ: (80,000 − 25,500) × 4.5% = $2,452.50 → $2,453."""
    e, _ = _run("NC", "80000", FilingStatus.MFJ)
    assert e.resolved["nc.2024.taxable_income"] == Decimal("54500")
    assert e.resolved["nc.2024.tax"] == Decimal("2453")


# ─── M31 machinery works for the new packs ────────────────────


def test_ga_resident_with_pa_wages_apportions_and_credits() -> None:
    """PA nonresident pays 3.07% × 100k × 0.4 = $1,228; GA credits it."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        state_of_residence="GA",
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Multi",
                last_name="State",
                w2s=[
                    W2Data(
                        employer_name="A",
                        wages=Decimal("60000"),
                        state="GA",
                        state_wages=Decimal("60000"),
                    ),
                    W2Data(
                        employer_name="B",
                        wages=Decimal("40000"),
                        state="PA",
                        state_wages=Decimal("40000"),
                    ),
                ],
            )
        ],
    )
    e = CalculationEngine(FED, inp, state_packs={"GA": STATE["GA"], "PA": STATE["PA"]})
    e.run()
    assert e.resolved["pa.2024.tax.full"] == Decimal("3070")
    assert e.resolved["pa.2024.tax"] == Decimal("1228")
    assert e.resolved["ga.2024.credits.other_state"] == Decimal("1228")
