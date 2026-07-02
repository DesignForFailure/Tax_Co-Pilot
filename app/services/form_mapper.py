# SPDX-License-Identifier: AGPL-3.0-or-later
"""Map ReturnRun trace data to IRS form-oriented models.

Reads the form_line annotation on each TraceNode and populates
Form1040Lines and Schedule1Lines. Informational-only values
(tax-exempt interest, qualified dividends, total SS benefits)
are derived from the input snapshot.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.domain import ReturnRun
from app.models.forms import Form1040Lines, FormPacket, Schedule1Lines, ScheduleALines

# Maps form_line annotation strings to (form_name, field_name) targets.
_FORM_LINE_MAP: dict[str, tuple[str, str]] = {
    "1040 Line 1a": ("form_1040", "line_1a"),
    "1040 Line 2b": ("form_1040", "line_2b"),
    "1040 Line 3b": ("form_1040", "line_3b"),
    "1040 Line 6b": ("form_1040", "line_6b"),
    "1040 Line 7": ("form_1040", "line_7"),
    "1040 Line 9": ("form_1040", "line_9"),
    "1040 Line 11": ("form_1040", "line_11"),
    "1040 Line 13": ("form_1040", "line_13"),
    "1040 Line 15": ("form_1040", "line_15"),
    "1040 Line 16": ("form_1040", "line_16"),
    "1040 Line 25d": ("form_1040", "line_25d"),
    "1040 Line 26": ("form_1040", "line_26"),
    "1040 Line 27": ("form_1040", "line_27"),
    "1040 Line 33": ("form_1040", "line_33"),
    "Schedule 1 Line 3": ("schedule_1", "line_3"),
    "Schedule 1 Line 8": ("schedule_1", "line_8"),
    "Schedule 1 Line 11": ("schedule_1", "line_11"),
    "Schedule 1 Line 13": ("schedule_1", "line_13"),
    "Schedule 1 Line 15": ("schedule_1", "line_15"),
    "Schedule 1 Line 20": ("schedule_1", "line_20"),
    "Schedule 1 Line 21": ("schedule_1", "line_21"),
    "Schedule 1 Line 26": ("schedule_1", "line_26"),
    "1040 Line 12": ("form_1040", "line_12"),
    "1040 Line 19": ("form_1040", "line_19"),
    "1040 Line 21": ("form_1040", "line_21"),
    "1040 Line 22": ("form_1040", "line_22"),
    "1040 Line 23": ("form_1040", "line_23"),
    "1040 Line 24": ("form_1040", "line_24"),
    "Schedule A Line 4": ("schedule_a", "line_4"),
    "Schedule A Line 7": ("schedule_a", "line_7"),
    "Schedule A Line 10": ("schedule_a", "line_10"),
    "Schedule A Line 14": ("schedule_a", "line_14"),
    "Schedule A Line 17": ("schedule_a", "line_17"),
}


def map_return_run(run: ReturnRun) -> FormPacket:
    """Map a ReturnRun to a FormPacket of IRS form line items."""
    form_1040 = Form1040Lines()
    schedule_1 = Schedule1Lines()
    schedule_a = ScheduleALines()
    forms: dict[str, Form1040Lines | Schedule1Lines | ScheduleALines] = {
        "form_1040": form_1040,
        "schedule_1": schedule_1,
        "schedule_a": schedule_a,
    }

    for trace in run.trace:
        if not trace.form_line:
            continue
        raw_val = trace.result.get("value")
        value = Decimal(str(raw_val)) if raw_val is not None else Decimal("0")
        target = _FORM_LINE_MAP.get(trace.form_line)
        if target:
            form_name, field_name = target
            setattr(forms[form_name], field_name, value)

    # Derived: Schedule 1 Line 10 = sum of Part I additional income
    schedule_1.line_10 = schedule_1.line_3 + schedule_1.line_8

    # Derived: 1040 Line 8 = Schedule 1 Line 10 (additional income)
    form_1040.line_8 = schedule_1.line_10

    # Derived: 1040 Line 10 = Schedule 1 Line 26 (adjustments)
    form_1040.line_10 = schedule_1.line_26

    # Informational lines from input snapshot
    snap = run.input_snapshot
    form_1040.line_2a = sum(
        (f.tax_exempt_interest for tp in snap.taxpayers for f in tp.form_1099_ints),
        Decimal("0"),
    )
    form_1040.line_3a = sum(
        (f.qualified_dividends for tp in snap.taxpayers for f in tp.form_1099_divs),
        Decimal("0"),
    )
    form_1040.line_6a = sum(
        (f.total_benefits for tp in snap.taxpayers for f in tp.form_1099_ssas),
        Decimal("0"),
    )

    # Refund (Line 34) vs Amount Owed (Line 37)
    # Line 24 (total tax incl. SE tax) wins when present; otherwise use
    # post-credit tax whenever credits are present, including scenarios where
    # credits reduce line_22 to zero.
    if form_1040.line_24 > 0:
        tax_amount = form_1040.line_24
    else:
        tax_amount = form_1040.line_22 if form_1040.line_21 > 0 else form_1040.line_16
    if form_1040.line_33 > tax_amount:
        form_1040.line_34 = form_1040.line_33 - tax_amount
        form_1040.line_37 = Decimal("0")
    else:
        form_1040.line_34 = Decimal("0")
        form_1040.line_37 = tax_amount - form_1040.line_33

    errors = _check_consistency(form_1040, schedule_1)

    return FormPacket(
        tax_year=run.tax_year,
        filing_status=run.filing_status.value,
        form_1040=form_1040,
        schedule_1=schedule_1,
        schedule_a=schedule_a,
        consistency_errors=errors,
    )


def _check_consistency(f: Form1040Lines, s: Schedule1Lines) -> list[str]:
    """Validate IRS form line relationships.

    Returns a list of human-readable error strings (empty if consistent).
    """
    errors: list[str] = []

    if f.line_11 > f.line_9:
        errors.append(
            f"Line 11 (AGI={f.line_11}) exceeds Line 9 (total income={f.line_9})"
        )

    if f.line_15 > f.line_11:
        errors.append(
            f"Line 15 (taxable={f.line_15}) exceeds Line 11 (AGI={f.line_11})"
        )

    expected_payments = f.line_25d + f.line_26 + f.line_27
    if f.line_33 != expected_payments:
        errors.append(
            f"Line 33 (total payments={f.line_33}) != "
            f"Line 25d ({f.line_25d}) + Line 26 ({f.line_26}) + Line 27 ({f.line_27})"
        )

    if f.line_22 > f.line_16:
        errors.append(
            f"Line 22 (tax after credits={f.line_22}) exceeds "
            f"Line 16 (tax before credits={f.line_16})"
        )

    if f.line_34 > 0 and f.line_37 > 0:
        errors.append("Both Line 34 (refund) and Line 37 (owed) are positive")

    expected_s1_10 = s.line_3 + s.line_8
    if s.line_10 != expected_s1_10:
        errors.append(
            f"Schedule 1 Line 10 ({s.line_10}) != Line 3 ({s.line_3}) + Line 8 ({s.line_8})"
        )

    return errors
