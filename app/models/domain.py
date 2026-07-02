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

"""Core domain models for Tax Copilot.

Security/QA notes:
- Use `default_factory=list` for all list fields to avoid shared mutable defaults.
- Keep models pure (no DB / IO side effects) to preserve auditability.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


class FilingStatus(StrEnum):
    SINGLE = "single"
    MFJ = "mfj"
    MFS = "mfs"
    HOH = "hoh"
    QSS = "qss"


class TaxpayerRole(StrEnum):
    PRIMARY = "primary"
    SPOUSE = "spouse"


# ─── Input Models ─────────────────────────────────────────────


class W2Data(BaseModel):
    """W-2 form fields relevant to MVP."""

    employer_name: str = ""
    employer_ein: str = ""
    wages: Decimal = Decimal("0")  # Box 1
    federal_withheld: Decimal = Decimal("0")  # Box 2
    social_security_wages: Decimal = Decimal("0")  # Box 3
    social_security_tax: Decimal = Decimal("0")  # Box 4
    medicare_wages: Decimal = Decimal("0")  # Box 5
    medicare_tax: Decimal = Decimal("0")  # Box 6
    tips: Decimal = Decimal("0")  # Box 7
    state: str = ""  # Box 15
    state_wages: Decimal = Decimal("0")  # Box 16
    state_withheld: Decimal = Decimal("0")  # Box 17


class Form1099INTData(BaseModel):
    payer_name: str = ""
    interest_income: Decimal = Decimal("0")  # Box 1
    tax_exempt_interest: Decimal = Decimal("0")  # Box 8
    federal_withheld: Decimal = Decimal("0")


class Form1099DIVData(BaseModel):
    payer_name: str = ""
    ordinary_dividends: Decimal = Decimal("0")  # Box 1a
    qualified_dividends: Decimal = Decimal("0")  # Box 1b
    federal_withheld: Decimal = Decimal("0")


class Form1099BData(BaseModel):
    description: str = ""
    proceeds: Decimal = Decimal("0")
    cost_basis: Decimal = Decimal("0")
    is_long_term: bool = False
    federal_withheld: Decimal = Decimal("0")

    @property
    def net_gain(self) -> Decimal:
        return self.proceeds - self.cost_basis


class Form1099NECData(BaseModel):
    """1099-NEC nonemployee compensation."""

    payer_name: str = ""
    nonemployee_compensation: Decimal = Decimal("0")  # Box 1
    federal_withheld: Decimal = Decimal("0")  # Box 4


class Form1099SSAData(BaseModel):
    """SSA-1099 Social Security benefits."""

    payer_name: str = ""
    total_benefits: Decimal = Decimal("0")  # Box 5
    federal_withheld: Decimal = Decimal("0")  # Box 6


class AdjustmentsData(BaseModel):
    """Above-the-line deductions (Schedule 1 Part II)."""

    student_loan_interest: Decimal = Decimal("0")
    ira_contributions: Decimal = Decimal("0")
    hsa_contributions: Decimal = Decimal("0")
    educator_expenses: Decimal = Decimal("0")
    self_employment_tax_deduction: Decimal = Decimal("0")


class EducationExpenseData(BaseModel):
    """Qualified education expenses for one AOTC-eligible student (Form 8863 Part III)."""

    student_name: str = ""
    qualified_expenses: Decimal = Decimal("0")


class ItemizedDeductionData(BaseModel):
    """Schedule A itemized deductions."""

    medical_expenses: Decimal = Decimal("0")
    state_local_taxes: Decimal = Decimal("0")
    real_estate_taxes: Decimal = Decimal("0")
    mortgage_interest: Decimal = Decimal("0")
    charitable_cash: Decimal = Decimal("0")
    charitable_noncash: Decimal = Decimal("0")


# ─── Taxpayer ─────────────────────────────────────────────────


class Taxpayer(BaseModel):
    id: str = Field(default_factory=new_id)
    role: TaxpayerRole
    first_name: str = ""
    last_name: str = ""
    is_active_duty_military: bool = False
    domicile_state: str = ""
    w2s: list[W2Data] = Field(default_factory=list)
    form_1099_ints: list[Form1099INTData] = Field(default_factory=list)
    form_1099_divs: list[Form1099DIVData] = Field(default_factory=list)
    form_1099_bs: list[Form1099BData] = Field(default_factory=list)
    form_1099_necs: list[Form1099NECData] = Field(default_factory=list)
    form_1099_ssas: list[Form1099SSAData] = Field(default_factory=list)


# ─── Tax Return Input (snapshot) ──────────────────────────────


class TaxReturnInput(BaseModel):
    """All inputs for a single return calculation."""

    tax_year: int
    filing_status: FilingStatus
    taxpayers: list[Taxpayer] = Field(default_factory=list)
    other_income: Decimal = Decimal("0")
    adjustments: AdjustmentsData = Field(default_factory=AdjustmentsData)
    estimated_tax_payments: Decimal = Decimal("0")
    itemized_deductions: ItemizedDeductionData = Field(default_factory=ItemizedDeductionData)
    qualifying_children: int = 0
    education_students: list[EducationExpenseData] = Field(default_factory=list)
    llc_expenses: Decimal = Decimal("0")

    def total_wages(self) -> Decimal:
        return sum((w.wages for tp in self.taxpayers for w in tp.w2s), Decimal("0"))

    def total_interest(self) -> Decimal:
        return sum(
            (f.interest_income for tp in self.taxpayers for f in tp.form_1099_ints), Decimal("0")
        )

    def total_dividends(self) -> Decimal:
        return sum(
            (f.ordinary_dividends for tp in self.taxpayers for f in tp.form_1099_divs), Decimal("0")
        )

    def total_capital_gains(self) -> Decimal:
        return sum((f.net_gain for tp in self.taxpayers for f in tp.form_1099_bs), Decimal("0"))

    def total_long_term_capital_gains(self) -> Decimal:
        return sum(
            (f.net_gain for tp in self.taxpayers for f in tp.form_1099_bs if f.is_long_term),
            Decimal("0"),
        )

    def total_short_term_capital_gains(self) -> Decimal:
        return sum(
            (f.net_gain for tp in self.taxpayers for f in tp.form_1099_bs if not f.is_long_term),
            Decimal("0"),
        )

    def total_federal_withholding(self) -> Decimal:
        total = Decimal("0")
        for tp in self.taxpayers:
            for w in tp.w2s:
                total += w.federal_withheld
            for i in tp.form_1099_ints:
                total += i.federal_withheld
            for d in tp.form_1099_divs:
                total += d.federal_withheld
            for b in tp.form_1099_bs:
                total += b.federal_withheld
            for n in tp.form_1099_necs:
                total += n.federal_withheld
            for s in tp.form_1099_ssas:
                total += s.federal_withheld
        return total

    def total_self_employment_income(self) -> Decimal:
        return sum(
            (f.nonemployee_compensation for tp in self.taxpayers for f in tp.form_1099_necs),
            Decimal("0"),
        )

    def total_social_security_benefits(self) -> Decimal:
        return sum(
            (f.total_benefits for tp in self.taxpayers for f in tp.form_1099_ssas),
            Decimal("0"),
        )

    def total_adjustments(self) -> Decimal:
        a = self.adjustments
        return (
            a.student_loan_interest
            + a.ira_contributions
            + a.hsa_contributions
            + a.educator_expenses
            + a.self_employment_tax_deduction
        )

    def aotc_expenses_tier1(self) -> Decimal:
        """Sum of per-student AOTC expenses capped at $2,000 (Form 8863 Part III line 28).

        The $2,000/$4,000 per-student tiers are part of the Form 8863 line
        structure (unchanged since 2009); the credit arithmetic itself stays
        in the rule packs.
        """
        return sum(
            (min(s.qualified_expenses, Decimal("2000")) for s in self.education_students),
            Decimal("0"),
        )

    def aotc_expenses_tier2(self) -> Decimal:
        """Sum of per-student AOTC expenses capped at $4,000 (Form 8863 Part III line 27)."""
        return sum(
            (min(s.qualified_expenses, Decimal("4000")) for s in self.education_students),
            Decimal("0"),
        )

    def total_qualified_dividends(self) -> Decimal:
        return sum(
            (f.qualified_dividends for tp in self.taxpayers for f in tp.form_1099_divs),
            Decimal("0"),
        )

    def total_tax_exempt_interest(self) -> Decimal:
        return sum(
            (f.tax_exempt_interest for tp in self.taxpayers for f in tp.form_1099_ints),
            Decimal("0"),
        )


# ─── Trace / Audit Models ────────────────────────────────────


class TraceNode(BaseModel):
    """One step in the calculation trace."""

    node_id: str
    rule_id: str
    rule_pack_version: str
    description: str
    inputs: dict[str, Any]
    intermediates: list[dict[str, Any]] = Field(default_factory=list)
    result: dict[str, Any]
    explanation: str
    form_line: str = ""


class ReturnOutput(BaseModel):
    """Final computed values."""

    gross_income: Decimal
    agi: Decimal
    standard_deduction: Decimal
    taxable_income: Decimal
    federal_tax: Decimal
    total_withholding: Decimal
    refund_or_owed: Decimal  # positive = refund, negative = owed
    adjustments_total: Decimal = Decimal("0")
    estimated_tax_payments: Decimal = Decimal("0")
    total_payments: Decimal = Decimal("0")
    itemized_deductions: Decimal = Decimal("0")
    deduction_applied: Decimal = Decimal("0")
    child_tax_credit: Decimal = Decimal("0")
    total_credits: Decimal = Decimal("0")
    tax_before_credits: Decimal = Decimal("0")
    self_employment_tax: Decimal = Decimal("0")
    earned_income_credit: Decimal = Decimal("0")
    education_credits: Decimal = Decimal("0")


class StateReturnOutput(BaseModel):
    state: str
    state_agi: Decimal = Decimal("0")
    state_standard_deduction: Decimal = Decimal("0")
    state_personal_exemption: Decimal = Decimal("0")
    state_taxable_income: Decimal = Decimal("0")
    state_tax: Decimal = Decimal("0")
    state_withholding: Decimal = Decimal("0")
    state_refund_or_owed: Decimal = Decimal("0")


class ScenarioRun(BaseModel):
    scenario_name: str
    filing_status: FilingStatus
    total_tax: Decimal
    refund_or_owed: Decimal


class ScenarioComparison(BaseModel):
    scenario_a: ScenarioRun
    scenario_b: ScenarioRun
    diffs: list[dict[str, Any]] = Field(default_factory=list)
    recommendation: str
    savings: Decimal


class ReturnRun(BaseModel):
    """Immutable snapshot of a complete calculation run."""

    id: str = Field(default_factory=new_id)
    tax_year: int
    filing_status: FilingStatus
    scenario_name: str = "baseline"
    rule_pack_version: str
    rule_pack_checksum: str
    input_snapshot: TaxReturnInput
    output: ReturnOutput
    state_outputs: list[StateReturnOutput] = Field(default_factory=list)
    trace: list[TraceNode] = Field(default_factory=list)
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds")
    )
    tags: str = ""
    notes: str = ""
    integrity_hash: str = ""
    previous_hash: str = ""
