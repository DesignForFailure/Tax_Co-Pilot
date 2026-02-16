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
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel

from app.models.domain import Form1099BData, W2Data


def _money(
    s: str,
    *,
    allow_negative: bool = False,
    max_abs: Decimal = Decimal("1000000000"),
    max_decimals: int = 2,
) -> Decimal:
    """Parse CSV money-like fields safely.

    Mirrors app.main._parse_money constraints so CSV imports behave the same way.
    """
    raw = (s or "").strip()
    if not raw:
        raw = "0"

    raw = raw.replace(",", "")

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

    reader = csv.DictReader(io.StringIO(csv_text or ""))
    for idx, row in enumerate(reader, start=2):  # header is line 1
        try:
            if record_type == "W2":
                records.append(
                    W2Data(
                        employer_name=(row.get("employer_name") or "").strip(),
                        wages=_money(row.get("wages", "0"), allow_negative=False),
                        federal_withheld=_money(
                            row.get("federal_withheld", "0"), allow_negative=False
                        ),
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
            else:
                raise ValueError(f"Unsupported record_type: {record_type}")
        except Exception as e:
            errors.append(f"Line {idx}: {e}")

    return records, errors
