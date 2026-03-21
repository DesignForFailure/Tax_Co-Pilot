# Itemized Deductions & Child Tax Credit Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add itemized deductions (with standard-vs-itemized election), the child tax credit with phaseout, and update the engine, UI, and tests so returns are meaningfully more complete.

**Architecture:** Extend the rules-as-data YAML with 15 new rules covering Schedule A itemized deductions, a deduction election (`max(standard, itemized)`), CTC calculation with phaseout, and post-credit tax. The engine resolves new input fields, evaluates the new rules in topological order, and populates enhanced `ReturnOutput` fields. Backward compatible: zero inputs for itemized deductions and children produce identical results to today.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, Jinja2, PyYAML, Decimal, pytest

**EITC Note:** The Earned Income Tax Credit is deferred to a follow-up milestone. It requires multi-dimensional lookups (filing_status × num_children) that the current rule engine doesn't support. CTC + itemized deductions alone make this milestone substantial and valuable.

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/domain.py` | Modify | Add `ItemizedDeductionData`, `qualifying_children` on `TaxReturnInput`, new fields on `ReturnOutput` |
| `rule_packs/federal/2024/federal_2024_rules.yaml` | Modify | Add itemized deduction rules, CTC rules, `deductions.applied`, `tax.after_credits`; update `taxable_income` and `refund_or_owed` refs |
| `app/engine/calculator.py` | Modify | Resolve new inputs; update output construction with new fields |
| `tests/test_itemized_credits.py` | Create | Golden tests for itemized deductions and CTC |
| `main.py` | Modify | Parse new form fields into `ItemizedDeductionData` and `qualifying_children` |
| `app/templates/pages/calculate.html` | Modify | Add Itemized Deductions card and Dependents section |
| `app/templates/pages/dashboard.html` | Modify | Show deduction type, credits, tax before/after credits |
| `app/models/forms.py` | Modify | Add `ScheduleALines`, update `Form1040Lines` |
| `app/services/form_mapper.py` | Modify | Map new trace entries to form lines |
| `rule_packs/federal/2023/federal_2023_rules.yaml` | Modify | Add corresponding 2023 rules (same structure, same constants) |
| `tests/test_golden2.py` | Modify | Update trace completeness expected set |
| `tests/test_multi_year.py` | Modify | Update 2023 trace completeness expected set |
| `README.md` | Modify | Add `tests/test_itemized_credits.py` to tree |
| `CHANGELOG.md` | Modify | Add M8 entries |
| `.agent_tools/05_session_log.md` | Modify | Append session entry |

---

## Chunk 1: Domain Models

### Task 1: Add ItemizedDeductionData and update TaxReturnInput and ReturnOutput

**Files:**
- Modify: `app/models/domain.py:113-153` (after AdjustmentsData, before Taxpayer)
- Modify: `app/models/domain.py:240-252` (ReturnOutput)

- [ ] **Step 1: Add ItemizedDeductionData model**

After `AdjustmentsData` (line 122) and before the Taxpayer section comment (line 124), add:

```python
class ItemizedDeductionData(BaseModel):
    """Schedule A itemized deductions."""

    medical_expenses: Decimal = Decimal("0")
    state_local_taxes: Decimal = Decimal("0")
    real_estate_taxes: Decimal = Decimal("0")
    mortgage_interest: Decimal = Decimal("0")
    charitable_cash: Decimal = Decimal("0")
    charitable_noncash: Decimal = Decimal("0")
```

- [ ] **Step 2: Add fields to TaxReturnInput**

In `TaxReturnInput` (after `estimated_tax_payments` at line 153), add:

```python
    itemized_deductions: ItemizedDeductionData = Field(default_factory=ItemizedDeductionData)
    qualifying_children: int = 0
```

- [ ] **Step 3: Update ReturnOutput**

In `ReturnOutput` (lines 240-252), add new fields after `total_payments`:

```python
    itemized_deductions: Decimal = Decimal("0")
    deduction_applied: Decimal = Decimal("0")  # max(standard, itemized)
    child_tax_credit: Decimal = Decimal("0")
    total_credits: Decimal = Decimal("0")
    tax_before_credits: Decimal = Decimal("0")
```

- [ ] **Step 4: Run type check**

Run: `mypy app/models/domain.py`
Expected: PASS (no errors)

---

## Chunk 2: 2024 Itemized Deduction Rules

### Task 2: Add itemized deduction rules and deduction election to 2024 YAML

**Files:**
- Modify: `rule_packs/federal/2024/federal_2024_rules.yaml`

- [ ] **Step 1: Add itemized deduction constants**

In the `constants:` section, after `adjustment_limits:`, add:

```yaml
  itemized_limits:
    salt_cap:
      single: "10000"
      mfj: "10000"
      mfs: "5000"
      hoh: "10000"
      qss: "10000"
```

- [ ] **Step 2: Add itemized deduction rules**

Insert these rules AFTER `fed.2024.standard_deduction` (line 316) and BEFORE `fed.2024.taxable_income` (line 318):

```yaml
  - id: "fed.2024.itemized.salt_cap"
    description: "SALT deduction cap by filing status"
    form_line: "Schedule A"
    type: "lookup"
    table: "constants.itemized_limits.salt_cap"
    key: { ref: "input.filing_status" }

  - id: "fed.2024.itemized.salt_total"
    description: "State/local taxes + property taxes, capped at SALT limit"
    form_line: "Schedule A Line 7"
    type: "formula"
    expression: "min(state_taxes + property_taxes, cap)"
    inputs:
      state_taxes: { ref: "input.itemized.state_local_taxes" }
      property_taxes: { ref: "input.itemized.real_estate_taxes" }
      cap: { ref: "fed.2024.itemized.salt_cap" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.medical_floor"
    description: "7.5% of AGI floor for medical deduction"
    form_line: "Schedule A Line 3"
    type: "formula"
    expression: "agi * rate"
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      rate: { literal: "0.075" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.medical"
    description: "Medical deduction (expenses above 7.5% AGI floor)"
    form_line: "Schedule A Line 4"
    type: "formula"
    expression: "max(expenses - floor, zero)"
    inputs:
      expenses: { ref: "input.itemized.medical_expenses" }
      floor: { ref: "fed.2024.itemized.medical_floor" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.mortgage_interest"
    description: "Home mortgage interest deduction"
    form_line: "Schedule A Line 10"
    type: "formula"
    expression: "input"
    inputs:
      input: { ref: "input.itemized.mortgage_interest" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.charitable_agi_cap"
    description: "60% of AGI cap for cash charitable contributions"
    form_line: "Schedule A"
    type: "formula"
    expression: "agi * rate"
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      rate: { literal: "0.60" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.charitable"
    description: "Charitable contributions (cash capped at 60% AGI + noncash)"
    form_line: "Schedule A Line 14"
    type: "formula"
    expression: "min(cash, agi_cap) + noncash"
    inputs:
      cash: { ref: "input.itemized.charitable_cash" }
      noncash: { ref: "input.itemized.charitable_noncash" }
      agi_cap: { ref: "fed.2024.itemized.charitable_agi_cap" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.itemized.total"
    description: "Total itemized deductions (Schedule A Line 17)"
    form_line: "Schedule A Line 17"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2024.itemized.medical" }
        - { ref: "fed.2024.itemized.salt_total" }
        - { ref: "fed.2024.itemized.mortgage_interest" }
        - { ref: "fed.2024.itemized.charitable" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.deductions.applied"
    description: "Greater of standard or itemized deduction"
    form_line: "1040 Line 12"
    type: "formula"
    expression: "max(standard, itemized)"
    inputs:
      standard: { ref: "fed.2024.standard_deduction" }
      itemized: { ref: "fed.2024.itemized.total" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 3: Update taxable_income to use applied deduction**

Change `fed.2024.taxable_income` (line 318-327):

**From:**
```yaml
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      deduction: { ref: "fed.2024.standard_deduction" }
```

**To:**
```yaml
    description: "Taxable income = max(AGI - applied deduction, 0)"
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      deduction: { ref: "fed.2024.deductions.applied" }
```

- [ ] **Step 4: Verify the rule pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/federal/2024')); print(f'{len(p.rules)} rules')"`
Expected: `40 rules` (was 31, added 9 itemized rules)

---

## Chunk 3: Child Tax Credit and Post-Credit Tax Rules

### Task 3: Add CTC rules and tax.after_credits to 2024 YAML

**Files:**
- Modify: `rule_packs/federal/2024/federal_2024_rules.yaml`

- [ ] **Step 1: Add CTC constants**

In `constants:`, after `itemized_limits:`, add:

```yaml
  ctc_phaseout_threshold:
    single: "200000"
    mfj: "400000"
    mfs: "200000"
    hoh: "200000"
    qss: "400000"
```

- [ ] **Step 2: Add CTC rules**

Insert AFTER `fed.2024.tax.brackets` and BEFORE `fed.2024.total_withholding`:

```yaml
  - id: "fed.2024.credits.ctc.base"
    description: "Child tax credit base amount ($2,000 per qualifying child)"
    form_line: "1040 Line 19"
    type: "formula"
    expression: "children * credit"
    inputs:
      children: { ref: "input.qualifying_children" }
      credit: { literal: "2000" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "fed.2024.credits.ctc.threshold"
    description: "CTC phaseout AGI threshold by filing status"
    form_line: "CTC Worksheet"
    type: "lookup"
    table: "constants.ctc_phaseout_threshold"
    key: { ref: "input.filing_status" }

  - id: "fed.2024.credits.ctc.phaseout"
    description: "CTC phaseout reduction ($50 per $1,000 of AGI over threshold)"
    form_line: "CTC Worksheet"
    type: "formula"
    expression: "max((agi - threshold) * rate, zero)"
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      threshold: { ref: "fed.2024.credits.ctc.threshold" }
      rate: { literal: "0.05" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "fed.2024.credits.ctc.final"
    description: "Child tax credit after phaseout"
    form_line: "1040 Line 19"
    type: "formula"
    expression: "max(base - phaseout, zero)"
    inputs:
      base: { ref: "fed.2024.credits.ctc.base" }
      phaseout: { ref: "fed.2024.credits.ctc.phaseout" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "fed.2024.credits.total"
    description: "Total nonrefundable credits"
    form_line: "1040 Line 21"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2024.credits.ctc.final" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "fed.2024.tax.after_credits"
    description: "Federal tax after credits (cannot go below zero)"
    form_line: "1040 Line 22"
    type: "formula"
    expression: "max(tax - credits, zero)"
    inputs:
      tax: { ref: "fed.2024.tax.brackets" }
      credits: { ref: "fed.2024.credits.total" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

- [ ] **Step 3: Update refund_or_owed to use post-credit tax**

Change `fed.2024.refund_or_owed`:

**From:**
```yaml
    inputs:
      payments: { ref: "fed.2024.total_payments" }
      tax: { ref: "fed.2024.tax.brackets" }
```

**To:**
```yaml
    inputs:
      payments: { ref: "fed.2024.total_payments" }
      tax: { ref: "fed.2024.tax.after_credits" }
```

- [ ] **Step 4: Verify the rule pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/federal/2024')); print(f'{len(p.rules)} rules')"`
Expected: `46 rules` (31 original + 9 itemized + 6 CTC/credits)

---

## Chunk 4: Engine Updates

### Task 4: Update calculator input resolution and output construction

**Files:**
- Modify: `app/engine/calculator.py:199-223` (_resolve_inputs)
- Modify: `app/engine/calculator.py:109-121` (output construction in run())

- [ ] **Step 1: Add input resolution for itemized deductions and qualifying children**

In `_resolve_inputs()`, after the `input.estimated_payments` line (line 223), add:

```python
        # Itemized deduction inputs
        self.resolved["input.itemized.medical_expenses"] = (
            self.inputs.itemized_deductions.medical_expenses
        )
        self.resolved["input.itemized.state_local_taxes"] = (
            self.inputs.itemized_deductions.state_local_taxes
        )
        self.resolved["input.itemized.real_estate_taxes"] = (
            self.inputs.itemized_deductions.real_estate_taxes
        )
        self.resolved["input.itemized.mortgage_interest"] = (
            self.inputs.itemized_deductions.mortgage_interest
        )
        self.resolved["input.itemized.charitable_cash"] = (
            self.inputs.itemized_deductions.charitable_cash
        )
        self.resolved["input.itemized.charitable_noncash"] = (
            self.inputs.itemized_deductions.charitable_noncash
        )
        # Credit inputs
        self.resolved["input.qualifying_children"] = Decimal(
            self.inputs.qualifying_children
        )
```

- [ ] **Step 2: Update output construction in run()**

In `run()`, update the ReturnOutput construction to include the new fields:

```python
        yr = self.rp.tax_year
        output = ReturnOutput(
            gross_income=self.resolved.get(f"fed.{yr}.gross_income.total", Decimal("0")),
            agi=self.resolved.get(f"fed.{yr}.agi.total", Decimal("0")),
            standard_deduction=self.resolved.get(f"fed.{yr}.standard_deduction", Decimal("0")),
            taxable_income=self.resolved.get(f"fed.{yr}.taxable_income", Decimal("0")),
            federal_tax=self.resolved.get(f"fed.{yr}.tax.after_credits", Decimal("0")),
            total_withholding=self.resolved.get(f"fed.{yr}.total_withholding", Decimal("0")),
            refund_or_owed=self.resolved.get(f"fed.{yr}.refund_or_owed", Decimal("0")),
            adjustments_total=self.resolved.get(f"fed.{yr}.adjustments.total", Decimal("0")),
            estimated_tax_payments=self.resolved.get(f"fed.{yr}.estimated_payments", Decimal("0")),
            total_payments=self.resolved.get(f"fed.{yr}.total_payments", Decimal("0")),
            itemized_deductions=self.resolved.get(f"fed.{yr}.itemized.total", Decimal("0")),
            deduction_applied=self.resolved.get(f"fed.{yr}.deductions.applied", Decimal("0")),
            child_tax_credit=self.resolved.get(f"fed.{yr}.credits.ctc.final", Decimal("0")),
            total_credits=self.resolved.get(f"fed.{yr}.credits.total", Decimal("0")),
            tax_before_credits=self.resolved.get(f"fed.{yr}.tax.brackets", Decimal("0")),
        )
```

Note: `federal_tax` now comes from `tax.after_credits` instead of `tax.brackets`. With 0 children (default), `tax.after_credits = max(brackets - 0, 0) = brackets`, so existing behavior is preserved.

- [ ] **Step 3: Run type check**

Run: `mypy app/engine/calculator.py`
Expected: PASS

- [ ] **Step 4: Run existing golden tests for backward compatibility**

Run: `python -m pytest tests/test_golden.py tests/test_golden2.py -v -k "not trace_completeness"`
Expected: All PASS (dollar-value assertions unchanged because default inputs produce 0 credits and 0 itemized)

---

## Chunk 5: Golden Tests

### Task 5: Write golden tests for itemized deductions and CTC

**Files:**
- Create: `tests/test_itemized_credits.py`

- [ ] **Step 1: Create the test file**

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for Milestone 8: Itemized Deductions and Child Tax Credit.

Covers: itemized vs standard deduction election, SALT cap, medical
7.5% AGI floor, charitable 60% AGI cap, child tax credit with phaseout.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    ItemizedDeductionData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


# ─── Itemized deduction tests ─────────────────────────────────


def test_itemized_wins_over_standard() -> None:
    """Single filer, $100k wages, large itemized deductions.

    AGI: $100,000. Standard deduction: $14,600.
    Medical: $12,000 - 7.5% × $100k = $12,000 - $7,500 = $4,500.
    SALT: $8,000 (under $10k cap).
    Mortgage: $6,000.
    Charitable cash: $3,000 (under 60% AGI cap).
    Total itemized: $4,500 + $8,000 + $6,000 + $3,000 = $21,500.
    Applied deduction: max($14,600, $21,500) = $21,500.
    Taxable: $100,000 - $21,500 = $78,500.
    Tax: $1,160 + $4,266 + $6,897 = $12,323.
    Refund: $15,000 - $12,323 = $2,677.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("12000"),
            state_local_taxes=Decimal("8000"),
            mortgage_interest=Decimal("6000"),
            charitable_cash=Decimal("3000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.standard_deduction == Decimal("14600")
    assert run.output.itemized_deductions == Decimal("21500")
    assert run.output.deduction_applied == Decimal("21500")
    assert run.output.taxable_income == Decimal("78500")
    assert run.output.tax_before_credits == Decimal("12323")
    assert run.output.federal_tax == Decimal("12323")  # no credits
    assert run.output.refund_or_owed == Decimal("2677")


def test_standard_wins_over_itemized() -> None:
    """MFJ, $85k wages, small itemized deductions.

    Standard deduction: $29,200. Itemized: $9,000.
    Applied: max($29,200, $9,000) = $29,200.
    Same as existing MFJ golden test values.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("5000"),
            mortgage_interest=Decimal("3000"),
            charitable_cash=Decimal("1000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.standard_deduction == Decimal("29200")
    assert run.output.itemized_deductions == Decimal("9000")
    assert run.output.deduction_applied == Decimal("29200")


def test_salt_cap_enforced() -> None:
    """SALT cap at $10,000: state taxes $8k + property taxes $6k = $14k → capped to $10k."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("120000"), federal_withheld=Decimal("20000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("8000"),
            real_estate_taxes=Decimal("6000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    # SALT should be capped at $10,000
    salt_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.salt_total")
    assert Decimal(salt_trace.result["value"]) == Decimal("10000")


def test_salt_cap_mfs_5000() -> None:
    """MFS filers get $5,000 SALT cap instead of $10,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFS,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            state_local_taxes=Decimal("4000"),
            real_estate_taxes=Decimal("3000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    salt_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.salt_total")
    assert Decimal(salt_trace.result["value"]) == Decimal("5000")


def test_medical_floor_below_threshold() -> None:
    """Medical expenses below 7.5% AGI floor produce $0 deduction."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("5000"),  # below 7.5% × $100k = $7,500
        ),
    )
    run = CalculationEngine(FED, inp).run()

    med_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.medical")
    assert Decimal(med_trace.result["value"]) == Decimal("0")


def test_charitable_agi_cap() -> None:
    """Cash charitable capped at 60% of AGI."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            charitable_cash=Decimal("40000"),  # 60% of $50k = $30k cap
            charitable_noncash=Decimal("1000"),
        ),
    )
    run = CalculationEngine(FED, inp).run()

    char_trace = next(t for t in run.trace if t.rule_id == "fed.2024.itemized.charitable")
    assert Decimal(char_trace.result["value"]) == Decimal("31000")  # min(40k, 30k) + 1k


# ─── Child Tax Credit tests ───────────────────────────────────


def test_ctc_basic() -> None:
    """MFJ, $85k wages, 2 children. CTC: $4,000, no phaseout.

    Tax before credits: $6,232. CTC: $4,000. Tax after: $2,232.
    Withholding: $12,000. Refund: $12,000 - $2,232 = $9,768.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
        qualifying_children=2,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("4000")
    assert run.output.tax_before_credits == Decimal("6232")
    assert run.output.federal_tax == Decimal("2232")
    assert run.output.refund_or_owed == Decimal("9768")


def test_ctc_phaseout_single() -> None:
    """Single, $220k wages, 1 child. CTC phases out.

    AGI: $220,000. Threshold: $200,000. Excess: $20,000.
    Phaseout: $20,000 × 0.05 = $1,000. CTC: max($2,000 - $1,000, 0) = $1,000.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("220000"), federal_withheld=Decimal("40000"))],
            )
        ],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("1000")


def test_ctc_fully_phased_out() -> None:
    """Single, $300k wages, 1 child. CTC fully phased out.

    AGI: $300,000. Threshold: $200,000. Excess: $100,000.
    Phaseout: $100,000 × 0.05 = $5,000. CTC: max($2,000 - $5,000, 0) = $0.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("300000"), federal_withheld=Decimal("60000"))],
            )
        ],
        qualifying_children=1,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("0")


def test_ctc_zero_children() -> None:
    """No children means no CTC — backward compatible."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.child_tax_credit == Decimal("0")
    assert run.output.total_credits == Decimal("0")
    # federal_tax = tax_before_credits when no credits
    assert run.output.federal_tax == run.output.tax_before_credits


def test_ctc_cannot_exceed_tax() -> None:
    """CTC is nonrefundable — cannot reduce tax below zero.

    MFJ, $30k wages, 3 children. CTC base: $6,000.
    Tax before credits: low. CTC capped by tax amount.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("30000"), federal_withheld=Decimal("2000"))],
            )
        ],
        qualifying_children=3,
    )
    run = CalculationEngine(FED, inp).run()

    # Tax after credits cannot go below 0
    assert run.output.federal_tax >= 0
    assert run.output.federal_tax == Decimal("0") or run.output.federal_tax < run.output.tax_before_credits


# ─── Combined test ─────────────────────────────────────────────


def test_itemized_plus_ctc() -> None:
    """Itemized deductions AND child tax credit combined.

    MFJ, $200k wages, 2 children, large itemized.
    Medical: $25k - 7.5% × $200k = $25k - $15k = $10k.
    SALT: $10k (at cap). Mortgage: $15k. Charitable: $5k.
    Itemized: $10k + $10k + $15k + $5k = $40k.
    Standard: $29,200. Applied: $40,000.
    Taxable: $200,000 - $40,000 = $160,000.
    Tax: $2,320 + $8,532 + $14,454 = $25,306.
    CTC: 2 × $2,000 = $4,000 (no phaseout, MFJ threshold $400k).
    Tax after credits: $25,306 - $4,000 = $21,306.
    Withholding: $35,000. Refund: $35,000 - $21,306 = $13,694.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("200000"), federal_withheld=Decimal("35000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            medical_expenses=Decimal("25000"),
            state_local_taxes=Decimal("8000"),
            real_estate_taxes=Decimal("4000"),
            mortgage_interest=Decimal("15000"),
            charitable_cash=Decimal("5000"),
        ),
        qualifying_children=2,
    )
    run = CalculationEngine(FED, inp).run()

    assert run.output.itemized_deductions == Decimal("40000")
    assert run.output.deduction_applied == Decimal("40000")
    assert run.output.taxable_income == Decimal("160000")
    assert run.output.tax_before_credits == Decimal("25306")
    assert run.output.child_tax_credit == Decimal("4000")
    assert run.output.federal_tax == Decimal("21306")
    assert run.output.refund_or_owed == Decimal("13694")
```

- [ ] **Step 2: Run the tests**

Run: `python -m pytest tests/test_itemized_credits.py -v`
Expected: All 12 tests PASS

---

## Chunk 6: Update Trace Completeness Tests

### Task 6: Update existing trace completeness tests for new rule IDs

**Files:**
- Modify: `tests/test_golden2.py:106-138`
- Modify: `tests/test_multi_year.py` (2023 trace completeness)

- [ ] **Step 1: Update 2024 trace completeness in test_golden2.py**

Add these 15 new rule IDs to the `expected` set in `test_trace_completeness()`:

```python
        "fed.2024.itemized.salt_cap",
        "fed.2024.itemized.salt_total",
        "fed.2024.itemized.medical_floor",
        "fed.2024.itemized.medical",
        "fed.2024.itemized.mortgage_interest",
        "fed.2024.itemized.charitable_agi_cap",
        "fed.2024.itemized.charitable",
        "fed.2024.itemized.total",
        "fed.2024.deductions.applied",
        "fed.2024.credits.ctc.base",
        "fed.2024.credits.ctc.threshold",
        "fed.2024.credits.ctc.phaseout",
        "fed.2024.credits.ctc.final",
        "fed.2024.credits.total",
        "fed.2024.tax.after_credits",
```

- [ ] **Step 2: Run test_golden2 to verify**

Run: `python -m pytest tests/test_golden2.py -v`
Expected: All PASS

---

## Chunk 7: 2023 Rule Pack Update

### Task 7: Add corresponding itemized deduction and CTC rules to 2023 pack

**Files:**
- Modify: `rule_packs/federal/2023/federal_2023_rules.yaml`

The 2023 constants for SALT cap ($10k/$5k MFS), medical floor (7.5%), charitable AGI cap (60%), and CTC ($2k/child, $200k/$400k threshold) are the same as 2024. Only the rule ID namespace (`fed.2023.*`) and internal references differ.

- [ ] **Step 1: Add constants**

In `constants:`, add:

```yaml
  itemized_limits:
    salt_cap:
      single: "10000"
      mfj: "10000"
      mfs: "5000"
      hoh: "10000"
      qss: "10000"

  ctc_phaseout_threshold:
    single: "200000"
    mfj: "400000"
    mfs: "200000"
    hoh: "200000"
    qss: "400000"
```

- [ ] **Step 2: Add all 15 new rules (same structure as 2024, with `fed.2023.*` IDs and refs)**

Insert the same 9 itemized rules + 6 CTC/credit rules as Task 2 and Task 3, but with all `fed.2024` replaced by `fed.2023`.

- [ ] **Step 3: Update fed.2023.taxable_income**

Change deduction ref from `fed.2023.standard_deduction` to `fed.2023.deductions.applied`.

- [ ] **Step 4: Update fed.2023.refund_or_owed**

Change tax ref from `fed.2023.tax.brackets` to `fed.2023.tax.after_credits`.

- [ ] **Step 5: Verify 2023 pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/federal/2023')); print(f'{len(p.rules)} rules')"`
Expected: `46 rules`

- [ ] **Step 6: Update rule count assertions in test_multi_year.py**

Update `test_2023_pack_loads_correct_year` and `test_2024_pack_loads_correct_year` assertions from `len(...rules) == 31` to `len(...rules) == 46`.

- [ ] **Step 7: Update 2023 trace completeness in test_multi_year.py**

Add the 15 new `fed.2023.*` rule IDs to the `expected` set in `test_2023_trace_completeness()`.

- [ ] **Step 8: Run multi-year tests**

Run: `python -m pytest tests/test_multi_year.py -v`
Expected: All PASS

---

## Chunk 8: UI and Form Parsing

### Task 8: Add form sections and parsing for itemized deductions and dependents

**Files:**
- Modify: `app/templates/pages/calculate.html`
- Modify: `main.py` (_parse_tax_input_from_form)
- Modify: `app/templates/pages/dashboard.html`

- [ ] **Step 1: Add Itemized Deductions card to calculate.html**

After the "Above-the-Line Deductions" card and before the "Estimated Tax Payments" card, add:

```html
    {# ─── Itemized Deductions (Schedule A) ───────────────────── #}
    <div class="card">
        <h2>Itemized Deductions (Schedule A)</h2>
        <p class="text-dim text-sm" style="margin-bottom:12px;">Leave blank to use the standard deduction. The higher of standard or itemized will be applied automatically.</p>
        <div class="form-row">
            <div><label>Medical/Dental Expenses</label><input type="text" name="item_medical" placeholder="0"></div>
            <div><label>State &amp; Local Income Taxes</label><input type="text" name="item_state_taxes" placeholder="0"></div>
        </div>
        <div class="form-row">
            <div><label>Real Estate Taxes</label><input type="text" name="item_property_taxes" placeholder="0"></div>
            <div><label>Home Mortgage Interest</label><input type="text" name="item_mortgage" placeholder="0"></div>
        </div>
        <div class="form-row">
            <div><label>Charitable (Cash)</label><input type="text" name="item_charitable_cash" placeholder="0"></div>
            <div><label>Charitable (Non-Cash)</label><input type="text" name="item_charitable_noncash" placeholder="0"></div>
        </div>
    </div>

    {# ─── Dependents ─────────────────────────────────────────── #}
    <div class="card">
        <h2>Dependents</h2>
        <div class="form-row">
            <div><label>Qualifying Children (for Child Tax Credit)</label><input type="number" name="qualifying_children" value="0" min="0" max="20"></div>
        </div>
    </div>
```

- [ ] **Step 2: Update _parse_tax_input_from_form in main.py**

After the `adjustments = AdjustmentsData(...)` block (line ~498), add:

```python
    itemized = ItemizedDeductionData(
        medical_expenses=_form_money(fd, "item_medical"),
        state_local_taxes=_form_money(fd, "item_state_taxes"),
        real_estate_taxes=_form_money(fd, "item_property_taxes"),
        mortgage_interest=_form_money(fd, "item_mortgage"),
        charitable_cash=_form_money(fd, "item_charitable_cash"),
        charitable_noncash=_form_money(fd, "item_charitable_noncash"),
    )

    raw_children = str(fd.get("qualifying_children", "0")).strip()
    qualifying_children = min(int(raw_children), 20) if raw_children.isdigit() else 0
```

Update the `return TaxReturnInput(...)` call to include:

```python
        itemized_deductions=itemized,
        qualifying_children=qualifying_children,
```

Add `ItemizedDeductionData` to the imports from `app.models.domain`.

- [ ] **Step 3: Update dashboard.html to display new fields**

In the output summary section of `dashboard.html`, add rows for:
- Deduction Applied (standard vs itemized label)
- Tax Before Credits
- Child Tax Credit
- Total Credits
- Tax After Credits (federal_tax)

- [ ] **Step 4: Run route tests**

Run: `python -m pytest tests/test_milestone6_routes.py tests/test_forms.py -v`
Expected: All PASS

---

## Chunk 9: Form Mapping Updates

### Task 9: Update form models and mapper for Schedule A and new 1040 lines

**Files:**
- Modify: `app/models/forms.py`
- Modify: `app/services/form_mapper.py`

- [ ] **Step 1: Add ScheduleALines to forms.py**

After `Schedule1Lines`, add:

```python
class ScheduleALines(BaseModel):
    """Schedule A — Itemized Deductions."""

    line_1: Decimal = Decimal("0")    # Medical expenses
    line_4: Decimal = Decimal("0")    # Medical deduction (after floor)
    line_7: Decimal = Decimal("0")    # SALT total (after cap)
    line_10: Decimal = Decimal("0")   # Mortgage interest
    line_14: Decimal = Decimal("0")   # Charitable contributions
    line_17: Decimal = Decimal("0")   # Total itemized deductions
```

Add `schedule_a: ScheduleALines = Field(default_factory=ScheduleALines)` to `FormPacket`.

- [ ] **Step 2: Add new lines to Form1040Lines**

Add fields:
```python
    line_12: Decimal = Decimal("0")   # Applied deduction (standard or itemized)
    line_19: Decimal = Decimal("0")   # Child tax credit
    line_21: Decimal = Decimal("0")   # Total credits
    line_22: Decimal = Decimal("0")   # Tax after credits
```

- [ ] **Step 3: Update form_mapper.py _FORM_LINE_MAP and map_return_run**

Add mappings for the new form_line annotations:
```python
    "Schedule A Line 3": ("schedule_a", "line_4"),   # medical_floor → not a form field, skip
    "Schedule A Line 4": ("schedule_a", "line_4"),
    "Schedule A Line 7": ("schedule_a", "line_7"),
    "Schedule A Line 10": ("schedule_a", "line_10"),
    "Schedule A Line 14": ("schedule_a", "line_14"),
    "Schedule A Line 17": ("schedule_a", "line_17"),
    "1040 Line 12": ("form_1040", "line_12"),
    "1040 Line 19": ("form_1040", "line_19"),
    "1040 Line 21": ("form_1040", "line_21"),
    "1040 Line 22": ("form_1040", "line_22"),
    "CTC Worksheet": None,    # internal calc, no form line
    "Schedule A": None,       # generic annotation, no specific line
```

Update `map_return_run`: add `schedule_a = ScheduleALines()` and include it in the `forms` dict (`"schedule_a": schedule_a`). Pass `schedule_a=schedule_a` to `FormPacket(...)`.

Also update the refund/owed calculation to use `line_22` (post-credit tax) when credits apply:
```python
    tax_amount = form_1040.line_22 if form_1040.line_22 > 0 else form_1040.line_16
    # ... use tax_amount instead of form_1040.line_16 for refund/owed
```

- [ ] **Step 4: Run form tests**

Run: `python -m pytest tests/test_forms.py -v`
Expected: All PASS (or update specific assertions if form line counts changed)

---

## Chunk 10: Full Validation and Documentation

### Task 10: Run full quality gates and update docs

- [ ] **Step 1: Run ruff**

Run: `ruff check .`
Expected: All checks passed

- [ ] **Step 2: Run mypy**

Run: `mypy .`
Expected: Success

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass

- [ ] **Step 4: Fix any issues found**

If lint/type/test errors, fix them before proceeding.

- [ ] **Step 5: Update README.md file tree**

Add `tests/test_itemized_credits.py` to the tests section.

- [ ] **Step 6: Update CHANGELOG.md**

Under `## [Unreleased]`, add:

```markdown
### Added
- `ItemizedDeductionData` model for Schedule A inputs (medical, SALT, mortgage, charitable).
- `qualifying_children` field on `TaxReturnInput` for Child Tax Credit.
- 15 new federal rules: itemized deduction calculation (medical 7.5% AGI floor, SALT $10k cap, charitable 60% AGI cap), deduction election (`max(standard, itemized)`), Child Tax Credit with phaseout, post-credit tax.
- New `ReturnOutput` fields: `itemized_deductions`, `deduction_applied`, `child_tax_credit`, `total_credits`, `tax_before_credits`.
- Itemized Deductions (Schedule A) and Dependents sections on the calculate form.
- `ScheduleALines` form model and Schedule A form line mapping.
- 12 golden tests covering itemized deductions, SALT cap, medical floor, charitable cap, CTC basic/phaseout/combined.

### Changed
- `fed.{year}.taxable_income` now uses `deductions.applied` (max of standard/itemized) instead of `standard_deduction`.
- `fed.{year}.refund_or_owed` now uses `tax.after_credits` instead of `tax.brackets`.
- `ReturnOutput.federal_tax` now reflects post-credit tax (unchanged when no credits apply).
- Dashboard shows deduction type, tax before/after credits, and CTC amount.
```

- [ ] **Step 7: Update session log**

Append to `.agent_tools/05_session_log.md`:

```
- [2026-03-21] app/models/domain.py, rule_packs/federal/2024/federal_2024_rules.yaml, rule_packs/federal/2023/federal_2023_rules.yaml, app/engine/calculator.py, main.py, app/templates/pages/calculate.html, app/templates/pages/dashboard.html, app/models/forms.py, app/services/form_mapper.py, tests/test_itemized_credits.py, tests/test_golden2.py, tests/test_multi_year.py, README.md, CHANGELOG.md: Milestone 8 — itemized deductions (Schedule A with SALT cap, medical floor, charitable AGI cap), child tax credit with phaseout, deduction election (max of standard/itemized), post-credit tax, 15 new rules per year, 12 golden tests.
```

- [ ] **Step 8: Commit**

```bash
git add app/models/domain.py app/engine/calculator.py app/models/forms.py app/services/form_mapper.py \
  rule_packs/federal/2024/federal_2024_rules.yaml rule_packs/federal/2023/federal_2023_rules.yaml \
  main.py app/templates/pages/calculate.html app/templates/pages/dashboard.html \
  tests/test_itemized_credits.py tests/test_golden2.py tests/test_multi_year.py \
  README.md CHANGELOG.md .agent_tools/05_session_log.md
git commit -m "feat: implement Milestone 8 — Itemized Deductions and Child Tax Credit"
```
