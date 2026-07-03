# SPDX-License-Identifier: AGPL-3.0-or-later
"""Form parsing helpers shared by route and rule-editor handlers."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from starlette.datastructures import FormData

from app.models.domain import (
    AdjustmentsData,
    EducationExpenseData,
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Form1099INTData,
    Form1099NECData,
    ItemizedDeductionData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

MAX_TEXT = 200
MAX_INDEXED_ENTRIES = 50
MAX_IMPORT_BYTES = 10 * 1024 * 1024
MAX_RESTORE_BYTES = 100 * 1024 * 1024
MAX_IMPORT_ENTRIES = 1000
MAX_NOTES = 2000
IDX_RE = re.compile(r"^(\w+?)_(\d+)_(\w+)$")


def parse_money(
    raw: str,
    *,
    default: str = "0",
    allow_negative: bool = False,
    max_abs: Decimal = Decimal("1000000000"),
    max_decimals: int = 2,
) -> Decimal:
    """Parse a user-entered currency value to Decimal."""
    value = (raw or "").strip()
    if not value:
        value = default

    value = value.lstrip("$").strip()
    value = value.replace(",", "")
    value = value.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")

    if "e" in value.lower() or value.startswith("+"):
        raise ValueError(f"Invalid money value: {raw!r}")

    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid money value: {raw!r}") from exc

    if not amount.is_finite():
        raise ValueError("Money value must be finite")

    if not allow_negative and amount < 0:
        raise ValueError("Money value must be non-negative")

    if abs(amount) > max_abs:
        raise ValueError("Money value is too large")

    exponent = amount.as_tuple().exponent
    if isinstance(exponent, int) and exponent < -max_decimals:
        raise ValueError(f"Money value has more than {max_decimals} decimal places")

    quant = Decimal("1") if max_decimals == 0 else (Decimal(10) ** (-max_decimals))
    return amount.quantize(quant)


def sanitize_filename(raw: str) -> str:
    """Strip non-alphanumeric characters for safe Content-Disposition usage."""
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw)


def form_str(fd: Mapping[str, object], key: str, default: str = "") -> str:
    """Extract a trimmed string from form data bounded to MAX_TEXT."""
    raw = str(fd.get(key, default) or default).strip()
    if len(raw) > MAX_TEXT:
        raise ValueError(f"{key} exceeds {MAX_TEXT} characters")
    return raw


def form_money(fd: Mapping[str, object], key: str, default: str = "0") -> Decimal:
    """Extract and parse a money field from a form mapping."""
    return parse_money(str(fd.get(key, default) or default), allow_negative=False)


def parse_rule_form(fd: FormData) -> dict[str, Any]:
    """Parse the rule editor form into a rule dictionary."""
    rule_id = form_str(fd, "rule_id")
    rule_type = form_str(fd, "rule_type")
    description = form_str(fd, "description")
    form_line = form_str(fd, "form_line")

    rule: dict[str, Any] = {
        "id": rule_id,
        "type": rule_type,
        "description": description,
    }
    if form_line:
        rule["form_line"] = form_line

    if rule_type == "sum":
        items_ref = form_str(fd, "sum_items_ref")
        rule["inputs"] = {"items": {"ref": items_ref}}

    elif rule_type == "formula":
        rule["expression"] = form_str(fd, "expression")
        inputs: dict[str, Any] = {}
        idx = 0
        while True:
            name = str(fd.get(f"input_name_{idx}", "") or "").strip()
            if not name:
                break
            input_type = str(fd.get(f"input_type_{idx}", "ref") or "ref").strip()
            input_value = str(fd.get(f"input_value_{idx}", "") or "").strip()
            if input_type == "literal":
                inputs[name] = {"literal": input_value}
            else:
                inputs[name] = {"ref": input_value}
            idx += 1
        rule["inputs"] = inputs

    elif rule_type == "lookup":
        rule["table"] = form_str(fd, "lookup_table")
        rule["key"] = {"ref": form_str(fd, "lookup_key_ref")}

    elif rule_type == "bracket_table":
        rule["input"] = {"ref": form_str(fd, "bracket_input_ref")}
        rule["key"] = {"ref": form_str(fd, "bracket_key_ref")}
        tables: dict[str, list[dict[str, str | None]]] = {}
        for status in ("single", "mfj", "mfs", "hoh", "qss"):
            brackets: list[dict[str, str | None]] = []
            row = 0
            while True:
                lower = str(fd.get(f"bracket_{status}_{row}_lower", "") or "").strip()
                if not lower and row > 0:
                    break
                if not lower:
                    row += 1
                    continue
                upper = str(fd.get(f"bracket_{status}_{row}_upper", "") or "").strip() or None
                rate = str(fd.get(f"bracket_{status}_{row}_rate", "") or "").strip()
                brackets.append({"lower": lower, "upper": upper, "rate": rate})
                row += 1
            if brackets:
                tables[status] = brackets
        if tables:
            rule["tables"] = tables

    elif rule_type == "matrix_lookup":
        # The type-adaptive editor has no form section for nested matrix
        # tables; without this guard, saving would silently rewrite the rule
        # with a different shape. Edit the pack YAML directly instead.
        raise ValueError(
            "matrix_lookup rules cannot be edited in the web editor yet; "
            "edit the pack YAML and re-import it"
        )

    return rule


def collect_indices(fd: FormData, prefix: str) -> list[int]:
    """Find integer indices for keys matching ``{prefix}_{N}_*``."""
    indices: set[int] = set()
    prefix_under = prefix + "_"
    for key in fd:
        if key.startswith(prefix_under):
            match = IDX_RE.fullmatch(key)
            if match and match.group(1) == prefix:
                idx = int(match.group(2))
                if idx < MAX_INDEXED_ENTRIES:
                    indices.add(idx)
    return sorted(indices)


def parse_w2s(fd: FormData, prefix: str) -> list[W2Data]:
    """Parse W-2 rows from indexed form fields."""
    w2s: list[W2Data] = []
    for idx in collect_indices(fd, prefix):
        base = f"{prefix}_{idx}"
        wages = form_money(fd, f"{base}_wages")
        withheld = form_money(fd, f"{base}_federal_withheld")
        employer = form_str(fd, f"{base}_employer")
        state = form_str(fd, f"{base}_state").upper()
        state_wages = form_money(fd, f"{base}_state_wages")
        state_withheld = form_money(fd, f"{base}_state_withheld")
        if (
            wages == 0
            and withheld == 0
            and state_wages == 0
            and state_withheld == 0
            and not employer
            and not state
        ):
            continue
        w2s.append(
            W2Data(
                employer_name=employer,
                wages=wages,
                federal_withheld=withheld,
                state=state,
                state_wages=state_wages,
                state_withheld=state_withheld,
            )
        )
    return w2s


def parse_1099ints(fd: FormData, prefix: str) -> list[Form1099INTData]:
    """Parse 1099-INT rows from indexed form fields."""
    items: list[Form1099INTData] = []
    for idx in collect_indices(fd, prefix):
        base = f"{prefix}_{idx}"
        interest = form_money(fd, f"{base}_interest")
        payer = form_str(fd, f"{base}_payer")
        federal_withheld = form_money(fd, f"{base}_federal_withheld")
        if interest == 0 and federal_withheld == 0 and not payer:
            continue
        items.append(
            Form1099INTData(
                payer_name=payer,
                interest_income=interest,
                federal_withheld=federal_withheld,
            )
        )
    return items


def parse_1099divs(fd: FormData, prefix: str) -> list[Form1099DIVData]:
    """Parse 1099-DIV rows from indexed form fields."""
    items: list[Form1099DIVData] = []
    for idx in collect_indices(fd, prefix):
        base = f"{prefix}_{idx}"
        ordinary = form_money(fd, f"{base}_ordinary")
        qualified = form_money(fd, f"{base}_qualified")
        federal_withheld = form_money(fd, f"{base}_federal_withheld")
        payer = form_str(fd, f"{base}_payer")
        if ordinary == 0 and qualified == 0 and federal_withheld == 0 and not payer:
            continue
        items.append(
            Form1099DIVData(
                payer_name=payer,
                ordinary_dividends=ordinary,
                qualified_dividends=qualified,
                federal_withheld=federal_withheld,
            )
        )
    return items


def parse_1099bs(fd: FormData, prefix: str) -> list[Form1099BData]:
    """Parse 1099-B rows from indexed form fields."""
    items: list[Form1099BData] = []
    for idx in collect_indices(fd, prefix):
        base = f"{prefix}_{idx}"
        proceeds = form_money(fd, f"{base}_proceeds")
        cost_basis = form_money(fd, f"{base}_basis")
        federal_withheld = form_money(fd, f"{base}_federal_withheld")
        description = form_str(fd, f"{base}_desc")
        if proceeds == 0 and cost_basis == 0 and federal_withheld == 0 and not description:
            continue
        items.append(
            Form1099BData(
                description=description or "Capital gain",
                proceeds=proceeds,
                cost_basis=cost_basis,
                is_long_term=str(fd.get(f"{base}_long_term", "")) == "1",
                federal_withheld=federal_withheld,
            )
        )
    return items


def parse_1099necs(fd: FormData, prefix: str) -> list[Form1099NECData]:
    """Parse 1099-NEC rows from indexed form fields."""
    items: list[Form1099NECData] = []
    for idx in collect_indices(fd, prefix):
        base = f"{prefix}_{idx}"
        compensation = form_money(fd, f"{base}_compensation")
        payer = form_str(fd, f"{base}_payer")
        federal_withheld = form_money(fd, f"{base}_federal_withheld")
        if compensation == 0 and federal_withheld == 0 and not payer:
            continue
        items.append(
            Form1099NECData(
                payer_name=payer,
                nonemployee_compensation=compensation,
                federal_withheld=federal_withheld,
            )
        )
    return items


def parse_education_students(fd: FormData) -> list[EducationExpenseData]:
    """Parse per-student AOTC expense rows from indexed form fields."""
    items: list[EducationExpenseData] = []
    for idx in collect_indices(fd, "edu"):
        base = f"edu_{idx}"
        expenses = form_money(fd, f"{base}_expenses")
        student = form_str(fd, f"{base}_student")
        if expenses == 0 and not student:
            continue
        items.append(
            EducationExpenseData(student_name=student, qualified_expenses=expenses)
        )
    return items


def parse_taxpayer(fd: FormData, prefix: str, role: TaxpayerRole) -> Taxpayer:
    """Build a taxpayer from indexed form fields under the given prefix."""
    first_name = form_str(fd, f"{prefix}_first")
    last_name = form_str(fd, f"{prefix}_last")

    if role == TaxpayerRole.PRIMARY:
        if not first_name:
            raise ValueError("first name is required")
        if not last_name:
            raise ValueError("last name is required")

    return Taxpayer(
        role=role,
        first_name=first_name,
        last_name=last_name,
        w2s=parse_w2s(fd, f"{prefix}_w2"),
        form_1099_ints=parse_1099ints(fd, f"{prefix}_1099int"),
        form_1099_divs=parse_1099divs(fd, f"{prefix}_1099div"),
        form_1099_bs=parse_1099bs(fd, f"{prefix}_1099b"),
        form_1099_necs=parse_1099necs(fd, f"{prefix}_1099nec"),
    )


def taxpayer_has_form_data(taxpayer: Taxpayer) -> bool:
    """Return True when a taxpayer contains names or parsed income records."""
    return bool(
        taxpayer.first_name
        or taxpayer.last_name
        or taxpayer.w2s
        or taxpayer.form_1099_ints
        or taxpayer.form_1099_divs
        or taxpayer.form_1099_bs
        or taxpayer.form_1099_necs
    )


def parse_tax_input_from_form(fd: FormData, available_years: Sequence[int]) -> TaxReturnInput:
    """Convert raw multi-part form data into a validated TaxReturnInput."""
    raw_year = str(fd.get("tax_year", "2024") or "2024").strip()
    if not raw_year.isdigit():
        raise ValueError(f"Unsupported tax year: {raw_year!r}")
    tax_year = int(raw_year)
    if tax_year not in available_years:
        raise ValueError(f"Unsupported tax year: {tax_year}")
    filing_status = FilingStatus(str(fd.get("filing_status", "mfj") or "mfj"))

    primary = parse_taxpayer(fd, "p", TaxpayerRole.PRIMARY)
    taxpayers: list[Taxpayer] = [primary]

    spouse = parse_taxpayer(fd, "s", TaxpayerRole.SPOUSE)
    has_spouse_data = taxpayer_has_form_data(spouse)

    if filing_status == FilingStatus.MFJ:
        if has_spouse_data:
            taxpayers.append(spouse)
    elif has_spouse_data:
        # The spouse section stays in the DOM when the status dropdown
        # changes; silently dropping its income/withholding would save a
        # confidently wrong run.
        if filing_status == FilingStatus.MFS:
            raise ValueError("MFS is per-person; submit each spouse as a separate run")
        raise ValueError(
            f"Spouse information was submitted but filing status is "
            f"{filing_status.value}; clear the spouse section or choose MFJ"
        )

    adjustments = AdjustmentsData(
        student_loan_interest=form_money(fd, "adj_student_loan"),
        educator_expenses=form_money(fd, "adj_educator"),
        hsa_contributions=form_money(fd, "adj_hsa"),
        ira_contributions=form_money(fd, "adj_ira"),
        self_employment_tax_deduction=form_money(fd, "adj_se_tax"),
    )

    itemized = ItemizedDeductionData(
        medical_expenses=form_money(fd, "item_medical"),
        state_local_taxes=form_money(fd, "item_state_taxes"),
        real_estate_taxes=form_money(fd, "item_property_taxes"),
        mortgage_interest=form_money(fd, "item_mortgage"),
        charitable_cash=form_money(fd, "item_charitable_cash"),
        charitable_noncash=form_money(fd, "item_charitable_noncash"),
    )

    raw_children = str(fd.get("qualifying_children", "0")).strip()
    if not raw_children:
        qualifying_children = 0
    elif raw_children.isdigit():
        qualifying_children = min(int(raw_children), 20)
    else:
        # Silently coercing "-1" or "2.0" to 0 wiped the child tax credit
        # without feedback.
        raise ValueError("Qualifying children must be a whole number of 0 or more")

    raw_care_persons = str(fd.get("care_persons", "0")).strip()
    if not raw_care_persons:
        care_persons = 0
    elif raw_care_persons.isdigit():
        care_persons = min(int(raw_care_persons), 20)
    else:
        raise ValueError("Care qualifying persons must be a whole number of 0 or more")

    return TaxReturnInput(
        tax_year=tax_year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        adjustments=adjustments,
        estimated_tax_payments=form_money(fd, "estimated_payments"),
        other_income=form_money(fd, "other_income"),
        itemized_deductions=itemized,
        qualifying_children=qualifying_children,
        education_students=parse_education_students(fd),
        llc_expenses=form_money(fd, "llc_expenses"),
        dependent_care_expenses=form_money(fd, "care_expenses"),
        dependent_care_qualifying_persons=care_persons,
        nyc_full_year_resident=str(fd.get("nyc_resident", "")) == "1",
        yonkers_full_year_resident=str(fd.get("yonkers_resident", "")) == "1",
        ca_renter=str(fd.get("ca_renter", "")) == "1",
    )
