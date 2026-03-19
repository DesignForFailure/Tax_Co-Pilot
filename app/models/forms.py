# SPDX-License-Identifier: GPL-3.0-or-later
"""IRS form data models for mapping engine outputs to form-oriented views.

Each model represents an IRS form with fields named by line number.
Values are populated by the form mapper service from ReturnRun trace data.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field


class Form1040Lines(BaseModel):
    """IRS Form 1040 — U.S. Individual Income Tax Return (2024)."""

    # Income
    line_1a: Decimal = Decimal("0")   # Wages, salaries, tips (W-2 Box 1)
    line_2a: Decimal = Decimal("0")   # Tax-exempt interest
    line_2b: Decimal = Decimal("0")   # Taxable interest
    line_3a: Decimal = Decimal("0")   # Qualified dividends
    line_3b: Decimal = Decimal("0")   # Ordinary dividends
    line_6a: Decimal = Decimal("0")   # Social Security benefits (total)
    line_6b: Decimal = Decimal("0")   # Taxable Social Security benefits
    line_7: Decimal = Decimal("0")    # Capital gain or (loss)
    line_8: Decimal = Decimal("0")    # Other income from Schedule 1, line 10
    line_9: Decimal = Decimal("0")    # Total income

    # Adjustments
    line_10: Decimal = Decimal("0")   # Adjustments from Schedule 1, line 26
    line_11: Decimal = Decimal("0")   # Adjusted gross income

    # Deductions
    line_13: Decimal = Decimal("0")   # Standard deduction or itemized deductions
    line_15: Decimal = Decimal("0")   # Taxable income

    # Tax
    line_16: Decimal = Decimal("0")   # Tax

    # Payments
    line_25d: Decimal = Decimal("0")  # Federal income tax withheld
    line_26: Decimal = Decimal("0")   # Estimated tax payments
    line_33: Decimal = Decimal("0")   # Total payments

    # Refund or Amount Owed
    line_34: Decimal = Decimal("0")   # Overpaid (refund)
    line_37: Decimal = Decimal("0")   # Amount owed


class Schedule1Lines(BaseModel):
    """Schedule 1 — Additional Income and Adjustments to Income (2024)."""

    # Part I: Additional Income
    line_3: Decimal = Decimal("0")    # Business income or (loss) — 1099-NEC
    line_8: Decimal = Decimal("0")    # Other income
    line_10: Decimal = Decimal("0")   # Total additional income

    # Part II: Adjustments to Income
    line_11: Decimal = Decimal("0")   # Educator expenses
    line_13: Decimal = Decimal("0")   # HSA deduction
    line_15: Decimal = Decimal("0")   # Deductible part of SE tax
    line_20: Decimal = Decimal("0")   # IRA deduction
    line_21: Decimal = Decimal("0")   # Student loan interest deduction
    line_26: Decimal = Decimal("0")   # Total adjustments to income


class FormPacket(BaseModel):
    """Complete set of form data for a tax return."""

    tax_year: int
    filing_status: str
    form_1040: Form1040Lines
    schedule_1: Schedule1Lines
    consistency_errors: list[str] = Field(default_factory=list)
