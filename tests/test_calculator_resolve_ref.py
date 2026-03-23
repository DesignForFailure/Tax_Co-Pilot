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

"""Tests for CalculationEngine._resolve_ref error reporting on bad references."""

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


def test_unary_negation_in_expression() -> None:
    """Engine handles unary minus in formula expressions."""
    engine = CalculationEngine.__new__(CalculationEngine)
    variables = {"x": Decimal("100"), "y": Decimal("50")}

    assert engine._safe_eval("-x", variables) == Decimal("-100")
    assert engine._safe_eval("-x + y", variables) == Decimal("-50")
    assert engine._safe_eval("+x", variables) == Decimal("100")
