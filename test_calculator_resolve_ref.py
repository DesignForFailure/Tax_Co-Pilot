from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack, RulePackError
from app.models.domain import FilingStatus, Taxpayer, TaxpayerRole, TaxReturnInput, W2Data

FED = RulePack.load(Path("rule_packs/federal/2024"))


def _engine() -> CalculationEngine:
    inputs = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Ty",
                last_name="Po",
                w2s=[W2Data(employer_name="Acme", wages=Decimal("1"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    engine = CalculationEngine(FED, inputs)
    engine._resolve_inputs()
    return engine


def test_resolve_ref_typoed_input_ref_raises_clear_missing_reference_error() -> None:
    engine = _engine()

    with pytest.raises(RulePackError, match=r"Missing reference: input\.w2\.wage"):
        engine._resolve_ref("input.w2.wage")


def test_resolve_ref_typoed_rule_ref_raises_clear_missing_reference_error() -> None:
    engine = _engine()

    with pytest.raises(RulePackError, match=r"Missing reference: fed\.2024\.taxable_incom"):
        engine._resolve_ref("fed.2024.taxable_incom")
