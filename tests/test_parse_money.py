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

# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for _parse_money monetary input boundary."""

from decimal import Decimal

import pytest

from main import _parse_money


class TestValidInputs:
    def test_integer(self) -> None:
        assert _parse_money("75000") == Decimal("75000.00")

    def test_with_decimals(self) -> None:
        assert _parse_money("75000.50") == Decimal("75000.50")

    def test_zero(self) -> None:
        assert _parse_money("0") == Decimal("0.00")

    def test_with_commas(self) -> None:
        assert _parse_money("1,234,567.89") == Decimal("1234567.89")

    def test_empty_uses_default(self) -> None:
        assert _parse_money("") == Decimal("0.00")

    def test_just_below_billion(self) -> None:
        assert _parse_money("999999999") == Decimal("999999999.00")


class TestRejectedInputs:
    def test_scientific_notation(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("1e9")

    def test_too_many_decimals(self) -> None:
        with pytest.raises(ValueError, match="decimal places"):
            _parse_money("12.345")

    def test_over_billion(self) -> None:
        with pytest.raises(ValueError, match="too large"):
            _parse_money("1500000000")

    def test_leading_plus(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("+100")

    def test_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("abc")

    def test_multiple_dots(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("12.34.56")

    def test_negative_disallowed_by_default(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            _parse_money("-500")

    def test_negative_allowed_when_opted_in(self) -> None:
        assert _parse_money("-500", allow_negative=True) == Decimal("-500.00")
