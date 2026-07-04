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

"""CSV import helpers (MVP).

Parses user-supplied CSV into domain models.

Security/QA notes:
- Uses Python's csv module (no eval).
- Returns structured errors instead of throwing on first failure.
- Enforces predictable numeric formats and reasonable bounds.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel

from app.log import get_logger
from app.models.domain import Form1099BData, Form1099DIVData, Form1099INTData, W2Data

logger = get_logger(__name__)

# Column names each record type must provide. Without this check, a file
# with mismatched headers (wrong type selected, Excel-renamed columns)
# imports rows of silent $0 amounts instead of failing.
_REQUIRED_HEADERS: dict[str, set[str]] = {
    "W2": {"employer_name", "wages"},
    "1099-B": {"description", "proceeds", "cost_basis"},
    "1099B": {"description", "proceeds", "cost_basis"},
    "1099-INT": {"payer_name", "interest_income"},
    "1099INT": {"payer_name", "interest_income"},
    "1099-DIV": {"payer_name", "ordinary_dividends"},
    "1099DIV": {"payer_name", "ordinary_dividends"},
}


def _money(
    s: str,
    *,
    allow_negative: bool = False,
    max_abs: Decimal = Decimal("1000000000"),
    max_decimals: int = 2,
) -> Decimal:
    """Parse CSV money-like fields safely.

    Mirrors app.route_helpers.form_parsing.parse_money so CSV imports
    behave the same way as browser form submissions.
    """
    raw = (s or "").strip()
    if not raw:
        raw = "0"

    # Normalize dollar signs, commas, unicode minus variants
    raw = raw.lstrip("$").strip()
    raw = raw.replace(",", "")
    raw = raw.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")

    if "e" in raw.lower() or raw.startswith("+"):
        raise ValueError(f"Invalid money: {s!r}")

    try:
        d = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid money: {s!r}") from exc

    if not d.is_finite():
        raise ValueError("Money must be finite")

    if not allow_negative and d < 0:
        raise ValueError("Money must be non-negative")

    if abs(d) > max_abs:
        raise ValueError("Money is too large")

    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp < -max_decimals:
        raise ValueError(f"Money has more than {max_decimals} decimals")

    quant = Decimal("1") if max_decimals == 0 else (Decimal(10) ** (-max_decimals))
    return d.quantize(quant)


def import_csv(csv_text: str, record_type: str) -> tuple[list[BaseModel], list[str]]:
    """Import CSV text.

    Returns: (records, errors)
    - records: list[BaseModel]
    - errors: list[str]
    """
    record_type = (record_type or "").strip().upper()
    errors: list[str] = []
    records: list[BaseModel] = []

    required = _REQUIRED_HEADERS.get(record_type)
    if required is None:
        return records, [f"Unsupported record_type: {record_type}"]

    # Strip UTF-8 BOM (Excel default CSV export on Windows)
    reader = csv.DictReader(io.StringIO((csv_text or "").lstrip("\ufeff")))
    headers = {(h or "").strip() for h in (reader.fieldnames or [])}
    missing = sorted(required - headers)
    if missing:
        return records, [
            f"Missing required column(s) for {record_type}: {', '.join(missing)}. "
            f"Found columns: {', '.join(sorted(headers)) or '(none)'}"
        ]

    def _rows() -> Iterator[tuple[int, dict[str, Any]]]:
        # csv.Error escapes from the iterator itself (e.g. a field beyond
        # the csv module's field_size_limit), outside the per-row handler.
        it = enumerate(reader, start=2)  # header is line 1
        while True:
            try:
                yield next(it)
            except StopIteration:
                return
            except csv.Error as exc:
                errors.append(f"CSV structure error (malformed or oversized field): {exc}")
                return

    for idx, row in _rows():
        try:
            if record_type == "W2":
                records.append(
                    W2Data(
                        employer_name=(row.get("employer_name") or "").strip(),
                        wages=_money(row.get("wages", "0"), allow_negative=False),
                        federal_withheld=_money(
                            row.get("federal_withheld", "0"), allow_negative=False
                        ),
                        medicare_wages=_money(
                            row.get("medicare_wages", "0"), allow_negative=False
                        ),
                        medicare_tax=_money(row.get("medicare_tax", "0"), allow_negative=False),
                        state=(row.get("state") or "").strip(),
                        state_withheld=_money(row.get("state_withheld", "0"), allow_negative=False),
                        state_wages=_money(
                            row.get("state_wages", row.get("wages", "0")), allow_negative=False
                        ),
                    )
                )
            elif record_type in {"1099-B", "1099B"}:
                is_long = (row.get("is_long_term") or "").strip().lower() in {
                    "true",
                    "1",
                    "yes",
                    "y",
                }
                records.append(
                    Form1099BData(
                        description=(row.get("description") or "").strip(),
                        proceeds=_money(row.get("proceeds", "0"), allow_negative=False),
                        cost_basis=_money(row.get("cost_basis", "0"), allow_negative=False),
                        is_long_term=is_long,
                    )
                )
            elif record_type in {"1099-INT", "1099INT"}:
                records.append(
                    Form1099INTData(
                        payer_name=(row.get("payer_name") or "").strip(),
                        interest_income=_money(
                            row.get("interest_income", "0"), allow_negative=False
                        ),
                        federal_withheld=_money(
                            row.get("federal_withheld", "0"), allow_negative=False
                        ),
                    )
                )
            elif record_type in {"1099-DIV", "1099DIV"}:
                records.append(
                    Form1099DIVData(
                        payer_name=(row.get("payer_name") or "").strip(),
                        ordinary_dividends=_money(
                            row.get("ordinary_dividends", "0"), allow_negative=False
                        ),
                        qualified_dividends=_money(
                            row.get("qualified_dividends", "0"), allow_negative=False
                        ),
                        federal_withheld=_money(
                            row.get("federal_withheld", "0"), allow_negative=False
                        ),
                    )
                )
            else:
                raise ValueError(f"Unsupported record_type: {record_type}")
        except Exception as e:
            logger.debug("CSV import: line %d rejected: %s", idx, e)
            errors.append(f"Line {idx}: {e}")

    return records, errors
