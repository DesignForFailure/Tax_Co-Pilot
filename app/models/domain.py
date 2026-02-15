"""Core domain models for Tax Copilot.

Security/QA notes:
- Use `default_factory=list` for all list fields to avoid shared mutable defaults.
- Keep models pure (no DB / IO side effects) to preserve auditability.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


class FilingStatus(str, Enum):
    SINGLE = "single"
    MFJ = "mfj"
    MFS = "mfs"
    HOH = "hoh"
    QSS = "qss"


class TaxpayerRole(str, Enum):
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


# ─── Tax Return Input (snapshot) ──────────────────────────────


class TaxReturnInput(BaseModel):
    """All inputs for a single return calculation."""

    tax_year: int
    filing_status: FilingStatus
    taxpayers: list[Taxpayer] = Field(default_factory=list)

    def total_wages(self) -> Decimal:
        return sum((w.wages for tp in self.taxpayers for w in tp.w2s), Decimal("0"))

    def total_interest(self) -> Decimal:
        return sum((f.interest_income for tp in self.taxpayers for f in tp.form_1099_ints), Decimal("0"))

    def total_dividends(self) -> Decimal:
        return sum((f.ordinary_dividends for tp in self.taxpayers for f in tp.form_1099_divs), Decimal("0"))

    def total_capital_gains(self) -> Decimal:
        return sum((f.net_gain for tp in self.taxpayers for f in tp.form_1099_bs), Decimal("0"))

    def total_federal_withholding(self) -> Decimal:
        total = Decimal("0")
        for tp in self.taxpayers:
            for w in tp.w2s:
                total += w.federal_withheld
            for f in tp.form_1099_ints:
                total += f.federal_withheld
            for f in tp.form_1099_divs:
                total += f.federal_withheld
            for f in tp.form_1099_bs:
                total += f.federal_withheld
        return total


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


class ReturnOutput(BaseModel):
    """Final computed values."""

    gross_income: Decimal
    agi: Decimal
    standard_deduction: Decimal
    taxable_income: Decimal
    federal_tax: Decimal
    total_withholding: Decimal
    refund_or_owed: Decimal  # positive = refund, negative = owed


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
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )