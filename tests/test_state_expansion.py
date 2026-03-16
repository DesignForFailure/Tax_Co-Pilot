# SPDX-License-Identifier: GPL-3.0-or-later
"""State expansion tests — generalized engine, multi-state, and wiring."""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

BASE = Path(__file__).resolve().parent.parent
FED = RulePack.load(BASE / "rule_packs" / "federal" / "2024")
GA = RulePack.load(BASE / "rule_packs" / "state" / "GA" / "2024")


def _simple_ga_input() -> TaxReturnInput:
    """Single W-2 taxpayer with GA state withholding."""
    return TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Alice",
                last_name="Smith",
                w2s=[
                    W2Data(
                        employer_name="Acme Corp",
                        wages=Decimal("60000"),
                        federal_withheld=Decimal("9000"),
                        state="GA",
                        state_wages=Decimal("60000"),
                        state_withheld=Decimal("3000"),
                    )
                ],
            )
        ],
    )


def test_ga_through_generalized_engine() -> None:
    """GA results are produced through convention-based extraction."""
    inp = _simple_ga_input()
    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()

    assert len(run.state_outputs) == 1
    ga_out = run.state_outputs[0]
    assert ga_out.state == "GA"
    # Convention-based fields should be populated (non-zero for real rules).
    assert ga_out.state_agi > Decimal("0")
    assert ga_out.state_tax > Decimal("0")
    assert ga_out.state_withholding == Decimal("3000")


def test_no_state_packs_returns_empty() -> None:
    """Engine with no state packs produces no state outputs (backward compat)."""
    inp = _simple_ga_input()
    run = CalculationEngine(FED, inp).run()

    assert run.state_outputs == []


def test_state_withholding_attributed_correctly() -> None:
    """Withholding from multiple states is attributed to the correct state."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Bob",
                last_name="Jones",
                w2s=[
                    W2Data(
                        employer_name="GA Employer",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("7000"),
                        state="GA",
                        state_wages=Decimal("50000"),
                        state_withheld=Decimal("2500"),
                    ),
                    W2Data(
                        employer_name="Other Employer",
                        wages=Decimal("30000"),
                        federal_withheld=Decimal("4000"),
                        state="NY",
                        state_wages=Decimal("30000"),
                        state_withheld=Decimal("1800"),
                    ),
                ],
            )
        ],
    )
    # Only GA pack is loaded; NY withholding should not bleed into GA.
    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()

    assert len(run.state_outputs) == 1
    ga_out = run.state_outputs[0]
    assert ga_out.state == "GA"
    # GA withholding should be only the GA W-2 amount.
    assert ga_out.state_withholding == Decimal("2500")


def test_state_pack_discovery() -> None:
    """_load_state_packs finds GA at minimum."""
    from main import _load_state_packs

    packs = _load_state_packs(2024)
    assert "GA" in packs
    assert packs["GA"].jurisdiction == "GA"
