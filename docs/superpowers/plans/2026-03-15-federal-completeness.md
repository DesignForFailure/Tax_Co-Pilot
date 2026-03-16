# Federal Completeness Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the federal tax engine with new income categories (1099-NEC, SSA, other income), above-the-line AGI adjustments, capital loss limitation, edge-case hardening, and richer trace explanations with IRS form line references.

**Architecture:** Rules-as-data in YAML, evaluated by the deterministic CalculationEngine. New income types and adjustments are added as domain models, resolved inputs, and YAML rules. The engine's existing `sum`, `formula`, `lookup`, and `bracket_table` rule types handle everything — no new rule types needed. Explanation improvements live in the engine's trace-generation code, keyed off an optional `form_line` field in each rule.

**Tech Stack:** Python 3.12+, Pydantic v2, PyYAML, Decimal math, pytest

**Spec:** `docs/superpowers/specs/2026-03-15-federal-completeness-design.md`

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/domain.py` | Modify | Add Form1099NECData, Form1099SSAData, AdjustmentsData; extend Taxpayer, TaxReturnInput, ReturnOutput |
| `rule_packs/federal/2024/federal_2024_rules.yaml` | Modify | Add constants, ~12 new rules, update 2 existing rules, add form_line fields |
| `app/engine/calculator.py` | Modify | Extend _resolve_inputs(), update explanation generation, populate adjustments_total |
| `tests/test_golden_m1.py` | Create | ~18 new test vectors for all new income/adjustment/edge-case scenarios |
| `tests/test_golden.py` | Modify | Update test_trace_contains_all_rules expected set |
| `tests/test_golden2.py` | Modify | Update test_trace_completeness expected set |
| `app/engine/rule_loader.py` | No change needed | `form_line` passes through automatically (raw dict storage) |

---

## Chunk 1: Domain Models and Input Resolution

### Task 1: Add new domain models

**Files:**
- Modify: `app/models/domain.py:72-111` (add models after Form1099BData, extend Taxpayer)

- [ ] **Step 1: Write failing test for new models**

Create `tests/test_golden_m1.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Golden tests for Federal Completeness milestone.

Covers: new income categories (1099-NEC, SSA, other income),
above-the-line adjustments, capital loss limitation, edge cases,
and explainability improvements.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099NECData,
    Form1099SSAData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))


def test_new_models_exist() -> None:
    """Verify new domain models can be instantiated with defaults."""
    nec = Form1099NECData()
    assert nec.nonemployee_compensation == Decimal("0")
    assert nec.federal_withheld == Decimal("0")

    ssa = Form1099SSAData()
    assert ssa.total_benefits == Decimal("0")
    assert ssa.federal_withheld == Decimal("0")

    adj = AdjustmentsData()
    assert adj.student_loan_interest == Decimal("0")
    assert adj.hsa_contributions == Decimal("0")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_m1.py::test_new_models_exist -v`
Expected: FAIL — ImportError for Form1099NECData, Form1099SSAData, AdjustmentsData

- [ ] **Step 3: Add Form1099NECData and Form1099SSAData to domain.py**

In `app/models/domain.py`, after the `Form1099BData` class (line ~95), add:

```python
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
```

- [ ] **Step 4: Add AdjustmentsData to domain.py**

After the new 1099 models, add:

```python
class AdjustmentsData(BaseModel):
    """Above-the-line deductions (Schedule 1 Part II)."""

    student_loan_interest: Decimal = Decimal("0")
    ira_contributions: Decimal = Decimal("0")
    hsa_contributions: Decimal = Decimal("0")
    educator_expenses: Decimal = Decimal("0")
    self_employment_tax_deduction: Decimal = Decimal("0")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_golden_m1.py::test_new_models_exist -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/models/domain.py tests/test_golden_m1.py
git commit -m "feat: add Form1099NECData, Form1099SSAData, AdjustmentsData models"
```

### Task 2: Extend Taxpayer and TaxReturnInput

**Files:**
- Modify: `app/models/domain.py:100-150` (Taxpayer and TaxReturnInput classes)

- [ ] **Step 1: Write failing test for extended models**

Add to `tests/test_golden_m1.py`:

```python
def test_taxpayer_has_new_form_lists() -> None:
    """Taxpayer model should have 1099-NEC and SSA lists."""
    tp = Taxpayer(
        role=TaxpayerRole.PRIMARY,
        form_1099_necs=[Form1099NECData(nonemployee_compensation=Decimal("5000"))],
        form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
    )
    assert len(tp.form_1099_necs) == 1
    assert len(tp.form_1099_ssas) == 1


def test_tax_return_input_new_helpers() -> None:
    """TaxReturnInput should have SE income, SS benefits, other income, and adjustments helpers."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        other_income=Decimal("1000"),
        adjustments=AdjustmentsData(student_loan_interest=Decimal("2500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_necs=[Form1099NECData(nonemployee_compensation=Decimal("5000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    assert inp.total_self_employment_income() == Decimal("5000")
    assert inp.total_social_security_benefits() == Decimal("18000")
    assert inp.other_income == Decimal("1000")
    assert inp.total_adjustments() == Decimal("2500")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_m1.py::test_taxpayer_has_new_form_lists tests/test_golden_m1.py::test_tax_return_input_new_helpers -v`
Expected: FAIL — missing attributes

- [ ] **Step 3: Extend Taxpayer with new form lists**

In the `Taxpayer` class, add after `form_1099_bs`:

```python
    form_1099_necs: list[Form1099NECData] = Field(default_factory=list)
    form_1099_ssas: list[Form1099SSAData] = Field(default_factory=list)
```

- [ ] **Step 4: Extend TaxReturnInput**

Add `other_income` and `adjustments` fields and new helper methods:

```python
class TaxReturnInput(BaseModel):
    """All inputs for a single return calculation."""

    tax_year: int
    filing_status: FilingStatus
    taxpayers: list[Taxpayer] = Field(default_factory=list)
    other_income: Decimal = Decimal("0")
    adjustments: AdjustmentsData = Field(default_factory=AdjustmentsData)

    # ... existing methods unchanged ...

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
```

Update `total_federal_withholding()` to include NEC and SSA:

```python
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
```

- [ ] **Step 5: Add adjustments_total to ReturnOutput**

In the `ReturnOutput` class, add:

```python
    adjustments_total: Decimal = Decimal("0")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_golden_m1.py -v`
Expected: All 3 tests PASS

- [ ] **Step 7: Run full test suite for backward compatibility**

Run: `pytest`
Expected: All existing tests PASS (new default fields don't break anything)

- [ ] **Step 8: Commit**

```bash
git add app/models/domain.py tests/test_golden_m1.py
git commit -m "feat: extend Taxpayer and TaxReturnInput with NEC, SSA, adjustments"
```

### Task 3: Extend _resolve_inputs() in calculator.py

**Files:**
- Modify: `app/engine/calculator.py:191-196`

- [ ] **Step 1: Write failing test for new input resolution**

Add to `tests/test_golden_m1.py`:

```python
def test_se_income_resolves() -> None:
    """Self-employment income from 1099-NEC should be included in gross income."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_necs=[
                    Form1099NECData(
                        payer_name="Client A",
                        nonemployee_compensation=Decimal("50000"),
                        federal_withheld=Decimal("0"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # SE income should appear in gross income
    assert run.output.gross_income == Decimal("50000.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_m1.py::test_se_income_resolves -v`
Expected: FAIL — gross_income is 0 because SE income isn't resolved

- [ ] **Step 3: Add new input resolutions and update run()**

In `calculator.py` `_resolve_inputs()`, add after the existing lines:

```python
    self.resolved["input.1099nec.compensation"] = self.inputs.total_self_employment_income()
    self.resolved["input.ssa.total_benefits"] = self.inputs.total_social_security_benefits()
    self.resolved["input.other_income"] = self.inputs.other_income
    self.resolved["input.adjustments.student_loan_interest"] = (
        self.inputs.adjustments.student_loan_interest
    )
    self.resolved["input.adjustments.ira_contributions"] = (
        self.inputs.adjustments.ira_contributions
    )
    self.resolved["input.adjustments.hsa_contributions"] = (
        self.inputs.adjustments.hsa_contributions
    )
    self.resolved["input.adjustments.educator_expenses"] = (
        self.inputs.adjustments.educator_expenses
    )
    self.resolved["input.adjustments.self_employment_tax_deduction"] = (
        self.inputs.adjustments.self_employment_tax_deduction
    )
```

In `run()`, update the `output = ReturnOutput(...)` call to include:

```python
    adjustments_total=self.resolved.get("fed.2024.adjustments.total", Decimal("0")),
```

**NOTE:** The test will still fail after this step because the YAML rules don't reference the new inputs yet. That's expected — Task 4 adds the rules.

- [ ] **Step 4: Run full existing test suite**

Run: `pytest tests/test_golden.py tests/test_golden2.py -v`
Expected: All existing tests PASS (new resolutions don't affect existing rules)

- [ ] **Step 5: Commit**

```bash
git add app/engine/calculator.py
git commit -m "feat: resolve NEC, SSA, other income, and adjustment inputs in engine"
```

---

## Chunk 2: YAML Rules — Income Categories

### Task 4: Add new income rules to YAML

**Files:**
- Modify: `rule_packs/federal/2024/federal_2024_rules.yaml`

- [ ] **Step 1: Add SS taxability constants**

In the `constants:` section, add after `standard_deduction`:

```yaml
  ss_taxability:
    base_threshold:
      single: "25000"
      mfj: "32000"
      mfs: "0"
      hoh: "25000"
      qss: "32000"
    upper_threshold:
      single: "34000"
      mfj: "44000"
      mfs: "0"
      hoh: "34000"
      qss: "44000"
```

- [ ] **Step 2: Add adjustment limit constants**

```yaml
  adjustment_limits:
    student_loan_interest_max: "2500"
    educator_expenses_max: "300"
    ira_limit: "7000"
    hsa_limit:
      single: "4150"
      mfj: "8300"
      mfs: "4150"
      hoh: "4150"
      qss: "8300"
```

- [ ] **Step 3: Add self-employment income rule**

After the existing `fed.2024.gross_income.capital_gains` rule, add:

```yaml
  - id: "fed.2024.gross_income.self_employment"
    description: "Total self-employment income (1099-NEC Box 1)"
    form_line: "Schedule 1 Line 3"
    type: "sum"
    inputs:
      items: { ref: "input.1099nec.compensation" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 4: Add capital gains limited rule**

```yaml
  - id: "fed.2024.gross_income.capital_gains_limited"
    description: "Net capital gains after loss limitation (-$3,000 max loss)"
    form_line: "1040 Line 7"
    type: "formula"
    expression: "max(gains, neg_limit)"
    inputs:
      gains: { ref: "fed.2024.gross_income.capital_gains" }
      neg_limit: { literal: "-3000" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 5: Add other income rule**

```yaml
  - id: "fed.2024.gross_income.other"
    description: "Other income (Line 8 catch-all)"
    form_line: "Schedule 1 Line 8"
    type: "formula"
    expression: "other"
    inputs:
      other: { ref: "input.other_income" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 6: Add SS leaf rules (half-benefits, thresholds, max-taxable)**

Add these leaf rules first — they have no intra-pack dependencies:

```yaml
  - id: "fed.2024.gross_income.ss_half_benefits"
    description: "50% of total Social Security benefits"
    form_line: "SS Worksheet Line 2"
    type: "formula"
    expression: "benefits * half"
    inputs:
      benefits: { ref: "input.ssa.total_benefits" }
      half: { literal: "0.5" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.gross_income.ss_base_threshold"
    description: "SS taxability base threshold by filing status"
    form_line: "SS Worksheet"
    type: "lookup"
    table: "constants.ss_taxability.base_threshold"
    key: { ref: "input.filing_status" }

  - id: "fed.2024.gross_income.ss_upper_threshold"
    description: "SS taxability upper threshold by filing status"
    form_line: "SS Worksheet"
    type: "lookup"
    table: "constants.ss_taxability.upper_threshold"
    key: { ref: "input.filing_status" }

  - id: "fed.2024.gross_income.ss_max_taxable"
    description: "85% of total SS benefits (maximum taxable amount)"
    form_line: "SS Worksheet Line 4"
    type: "formula"
    expression: "benefits * rate"
    inputs:
      benefits: { ref: "input.ssa.total_benefits" }
      rate: { literal: "0.85" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 7: Add SS provisional income rule**

This references the leaf rules from Step 6:

```yaml
  - id: "fed.2024.gross_income.ss_provisional"
    description: "Provisional income for SS taxability (non-SS income + 50% benefits)"
    form_line: "SS Worksheet Line 6"
    type: "formula"
    expression: "wages + interest + dividends + gains + se + other + half_ss"
    inputs:
      wages: { ref: "fed.2024.gross_income.wages" }
      interest: { ref: "fed.2024.gross_income.interest" }
      dividends: { ref: "fed.2024.gross_income.dividends" }
      gains: { ref: "fed.2024.gross_income.capital_gains_limited" }
      se: { ref: "fed.2024.gross_income.self_employment" }
      other: { ref: "fed.2024.gross_income.other" }
      half_ss: { ref: "fed.2024.gross_income.ss_half_benefits" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 8: Add SS lower/upper calc rules**

These reference provisional income and thresholds from prior steps:

```yaml
  - id: "fed.2024.gross_income.ss_lower_calc"
    description: "SS taxability lower-tier amount (50% of provisional above base)"
    form_line: "SS Worksheet Line 10"
    type: "formula"
    expression: "max(min((prov - base) * rate, (upper - base) * rate), zero)"
    inputs:
      prov: { ref: "fed.2024.gross_income.ss_provisional" }
      base: { ref: "fed.2024.gross_income.ss_base_threshold" }
      upper: { ref: "fed.2024.gross_income.ss_upper_threshold" }
      rate: { literal: "0.50" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.gross_income.ss_upper_calc"
    description: "SS taxability upper-tier amount (85% of provisional above upper threshold)"
    form_line: "SS Worksheet Line 14"
    type: "formula"
    expression: "max((prov - upper) * rate, zero)"
    inputs:
      prov: { ref: "fed.2024.gross_income.ss_provisional" }
      upper: { ref: "fed.2024.gross_income.ss_upper_threshold" }
      rate: { literal: "0.85" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 9: Add final SS taxable benefits rule**

References ss_max_taxable, ss_lower_calc, ss_upper_calc from prior steps:

```yaml
  - id: "fed.2024.gross_income.social_security"
    description: "Taxable Social Security benefits"
    form_line: "1040 Line 6b"
    type: "formula"
    expression: "min(max_taxable, lower + upper)"
    inputs:
      max_taxable: { ref: "fed.2024.gross_income.ss_max_taxable" }
      lower: { ref: "fed.2024.gross_income.ss_lower_calc" }
      upper: { ref: "fed.2024.gross_income.ss_upper_calc" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 10: Update gross income total rule**

Replace the existing `fed.2024.gross_income.total` with:

```yaml
  - id: "fed.2024.gross_income.total"
    description: "Total income (all sources)"
    form_line: "1040 Line 9"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2024.gross_income.wages" }
        - { ref: "fed.2024.gross_income.interest" }
        - { ref: "fed.2024.gross_income.dividends" }
        - { ref: "fed.2024.gross_income.capital_gains_limited" }
        - { ref: "fed.2024.gross_income.self_employment" }
        - { ref: "fed.2024.gross_income.social_security" }
        - { ref: "fed.2024.gross_income.other" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 11: Run the SE income test**

Run: `pytest tests/test_golden_m1.py::test_se_income_resolves -v`
Expected: PASS (SE income now flows through gross_income.total)

- [ ] **Step 12: Run full test suite**

Run: `pytest`
Expected: All pass EXCEPT `test_trace_contains_all_rules` and `test_trace_completeness` (new rule IDs in trace)

- [ ] **Step 13: Commit**

```bash
git add rule_packs/federal/2024/federal_2024_rules.yaml
git commit -m "feat: add SE income, SS benefits, other income, capital loss rules to YAML"
```

---

## Chunk 3: YAML Rules — Adjustments and AGI

### Task 5: Add adjustment rules and update AGI

**Files:**
- Modify: `rule_packs/federal/2024/federal_2024_rules.yaml`

- [ ] **Step 1: Write failing test for adjustments**

Add to `tests/test_golden_m1.py`:

```python
def test_student_loan_adjustment_capped() -> None:
    """Student loan interest capped at $2,500."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(student_loan_interest=Decimal("5000")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # AGI should be 60000 - 2500 = 57500 (capped at 2500, not 5000)
    assert run.output.agi == Decimal("57500.00")
    assert run.output.adjustments_total == Decimal("2500.00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_m1.py::test_student_loan_adjustment_capped -v`
Expected: FAIL — AGI still equals gross income

- [ ] **Step 3: Add HSA limit lookup rule**

```yaml
  - id: "fed.2024.adjustments.hsa_limit"
    description: "HSA contribution limit by filing status"
    form_line: "Form 8889"
    type: "lookup"
    table: "constants.adjustment_limits.hsa_limit"
    key: { ref: "input.filing_status" }
```

- [ ] **Step 4: Add individual adjustment rules**

```yaml
  - id: "fed.2024.adjustments.student_loan"
    description: "Student loan interest deduction (capped at $2,500)"
    form_line: "Schedule 1 Line 21"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.student_loan_interest" }
      cap: { literal: "2500" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.adjustments.educator"
    description: "Educator expenses deduction (capped at $300)"
    form_line: "Schedule 1 Line 11"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.educator_expenses" }
      cap: { literal: "300" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.adjustments.hsa"
    description: "HSA deduction (capped by filing status)"
    form_line: "Schedule 1 Line 13"
    type: "formula"
    expression: "min(input, limit)"
    inputs:
      input: { ref: "input.adjustments.hsa_contributions" }
      limit: { ref: "fed.2024.adjustments.hsa_limit" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.adjustments.ira"
    description: "IRA deduction (capped at $7,000)"
    form_line: "Schedule 1 Line 20"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.ira_contributions" }
      cap: { literal: "7000" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.adjustments.se_tax"
    description: "Self-employment tax deduction (user provides deductible half)"
    form_line: "Schedule 1 Line 15"
    type: "formula"
    expression: "input"
    inputs:
      input: { ref: "input.adjustments.self_employment_tax_deduction" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 5: Add adjustments total rule**

```yaml
  - id: "fed.2024.adjustments.total"
    description: "Total above-the-line adjustments"
    form_line: "Schedule 1 Line 26"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2024.adjustments.student_loan" }
        - { ref: "fed.2024.adjustments.educator" }
        - { ref: "fed.2024.adjustments.hsa" }
        - { ref: "fed.2024.adjustments.ira" }
        - { ref: "fed.2024.adjustments.se_tax" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 6: Update AGI rule**

Replace the existing `fed.2024.agi.total`:

```yaml
  - id: "fed.2024.agi.total"
    description: "Adjusted gross income (gross income minus adjustments)"
    form_line: "1040 Line 11"
    type: "formula"
    expression: "max(gross - adj, zero)"
    inputs:
      gross: { ref: "fed.2024.gross_income.total" }
      adj: { ref: "fed.2024.adjustments.total" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

- [ ] **Step 7: Add form_line to existing rules**

Add `form_line` to the existing rules that don't have it yet:

- `fed.2024.gross_income.wages`: `form_line: "1040 Line 1a"`
- `fed.2024.gross_income.interest`: `form_line: "1040 Line 2b"`
- `fed.2024.gross_income.dividends`: `form_line: "1040 Line 3b"`
- `fed.2024.gross_income.capital_gains`: `form_line: "Schedule D"`
- `fed.2024.standard_deduction`: `form_line: "1040 Line 13"`
- `fed.2024.taxable_income`: `form_line: "1040 Line 15"`
- `fed.2024.tax.brackets`: `form_line: "1040 Line 16"`
- `fed.2024.total_withholding`: `form_line: "1040 Line 25d"`
- `fed.2024.refund_or_owed`: `form_line: "1040 Line 34/37"`

- [ ] **Step 8: Run adjustment test**

Run: `pytest tests/test_golden_m1.py::test_student_loan_adjustment_capped -v`
Expected: PASS

- [ ] **Step 9: Run full existing test suite**

Run: `pytest tests/test_golden.py tests/test_golden2.py -v`
Expected: All pass except trace completeness tests (new rule IDs)

- [ ] **Step 10: Commit**

```bash
git add rule_packs/federal/2024/federal_2024_rules.yaml tests/test_golden_m1.py
git commit -m "feat: add adjustment rules, update AGI formula, add form_line refs"
```

---

## Chunk 4: Explainability Improvements

### Task 6: Upgrade explanation generation in calculator.py

**Files:**
- Modify: `app/engine/calculator.py:249-426` (all four evaluator methods)

- [ ] **Step 1: Write test for form line in explanation**

Add to `tests/test_golden_m1.py`:

```python
def test_trace_explanations_include_form_line() -> None:
    """Trace explanations should include IRS form line references."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    wages_trace = next(t for t in run.trace if t.rule_id == "fed.2024.gross_income.wages")
    assert "1040 Line 1a" in wages_trace.explanation

    deduction_trace = next(t for t in run.trace if t.rule_id == "fed.2024.standard_deduction")
    assert "1040 Line 13" in deduction_trace.explanation

    tax_trace = next(t for t in run.trace if t.rule_id == "fed.2024.tax.brackets")
    assert "1040 Line 16" in tax_trace.explanation
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_golden_m1.py::test_trace_explanations_include_form_line -v`
Expected: FAIL — explanations don't contain form line refs yet

- [ ] **Step 3: Update _eval_sum explanation**

In `calculator.py` `_eval_sum()`, replace the explanation line:

```python
        form_line = rule.get("form_line", "")
        line_prefix = f"{form_line}: " if form_line else ""
        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"items": [str(v) for v in values]},
                intermediates=[],
                result={
                    "value": str(result),
                    "units": "USD",
                    "rounding": rounding,
                    "precision": precision,
                },
                explanation=f"{line_prefix}{len(values)} item(s) totaling {_format_usd(result)}",
            )
        )
```

- [ ] **Step 4: Update _eval_formula explanation**

In `_eval_formula()`, replace the trace append:

```python
        form_line = rule.get("form_line", "")
        line_prefix = f"{form_line}: " if form_line else ""
        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={k: str(v) for k, v in inputs.items()},
                intermediates=[{"expression": expr}],
                result={
                    "value": str(result),
                    "units": "USD",
                    "rounding": rounding,
                    "precision": precision,
                },
                explanation=f"{line_prefix}{self._explain_formula(expr, inputs, result)}",
            )
        )
```

- [ ] **Step 5: Update _eval_lookup explanation**

In `_eval_lookup()`, replace the trace append:

```python
        form_line = rule.get("form_line", "")
        line_prefix = f"{form_line}: " if form_line else ""
        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"table": table_path, "key": key},
                intermediates=[],
                result={"value": str(value), "units": "USD"},
                explanation=f"{line_prefix}{key} → {_format_usd(value)}",
            )
        )
```

- [ ] **Step 6: Update _eval_bracket_table explanation**

In `_eval_bracket_table()`, replace the explanation construction:

```python
        form_line = rule.get("form_line", "")
        line_prefix = f"{form_line}: " if form_line else ""
        explanation = (
            f"{line_prefix}Tax on {_format_usd(income)} ({fs_key.upper()}): "
            + (" + ".join(parts) if parts else "$0.00")
            + f" = {_format_usd(result)}"
        )
```

- [ ] **Step 7: Run explanation test**

Run: `pytest tests/test_golden_m1.py::test_trace_explanations_include_form_line -v`
Expected: PASS

- [ ] **Step 8: Run full test suite**

Run: `pytest`
Expected: All pass except trace completeness tests (expected IDs outdated)

- [ ] **Step 9: Commit**

```bash
git add app/engine/calculator.py
git commit -m "feat: add form line references to trace explanations"
```

---

## Chunk 5: Update Trace Tests and Add Edge-Case Vectors

### Task 7: Update existing trace completeness tests

**Files:**
- Modify: `tests/test_golden.py:196-210`
- Modify: `tests/test_golden2.py:106-119`

- [ ] **Step 1: Compute the full expected rule ID set**

The new complete set of rule IDs in the federal pack:

```python
expected = {
    "fed.2024.gross_income.wages",
    "fed.2024.gross_income.interest",
    "fed.2024.gross_income.dividends",
    "fed.2024.gross_income.capital_gains",
    "fed.2024.gross_income.capital_gains_limited",
    "fed.2024.gross_income.self_employment",
    "fed.2024.gross_income.other",
    "fed.2024.gross_income.ss_half_benefits",
    "fed.2024.gross_income.ss_provisional",
    "fed.2024.gross_income.ss_base_threshold",
    "fed.2024.gross_income.ss_upper_threshold",
    "fed.2024.gross_income.ss_lower_calc",
    "fed.2024.gross_income.ss_upper_calc",
    "fed.2024.gross_income.ss_max_taxable",
    "fed.2024.gross_income.social_security",
    "fed.2024.gross_income.total",
    "fed.2024.adjustments.hsa_limit",
    "fed.2024.adjustments.student_loan",
    "fed.2024.adjustments.educator",
    "fed.2024.adjustments.hsa",
    "fed.2024.adjustments.ira",
    "fed.2024.adjustments.se_tax",
    "fed.2024.adjustments.total",
    "fed.2024.agi.total",
    "fed.2024.standard_deduction",
    "fed.2024.taxable_income",
    "fed.2024.tax.brackets",
    "fed.2024.total_withholding",
    "fed.2024.refund_or_owed",
}
```

- [ ] **Step 2: Update test_golden.py**

Replace the `expected` set in `test_trace_contains_all_rules` with the full set above.

- [ ] **Step 3: Update test_golden2.py**

Replace the `expected` set in `test_trace_completeness` with the same full set.

- [ ] **Step 4: Run both trace tests**

Run: `pytest tests/test_golden.py::test_trace_contains_all_rules tests/test_golden2.py::test_trace_completeness -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `pytest`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add tests/test_golden.py tests/test_golden2.py
git commit -m "fix: update trace completeness tests for new federal rule IDs"
```

### Task 8: Add comprehensive edge-case test vectors

**Files:**
- Modify: `tests/test_golden_m1.py`

- [ ] **Step 1: Add zero adjustments backward compatibility test**

```python
def test_zero_adjustments_backward_compatible() -> None:
    """With no adjustments, AGI should equal gross income (backward compatible)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == run.output.gross_income
    assert run.output.adjustments_total == Decimal("0")
```

- [ ] **Step 2: Add educator expense cap test**

```python
def test_educator_expense_capped_at_300() -> None:
    """Educator expenses capped at $300."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(educator_expenses=Decimal("500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="School", wages=Decimal("45000"), federal_withheld=Decimal("5000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("44700.00")  # 45000 - 300
```

- [ ] **Step 3: Add HSA limit by filing status test**

```python
def test_hsa_limit_varies_by_filing_status() -> None:
    """HSA limit is $4,150 for single, $8,300 for MFJ."""
    for fs, expected_limit in [
        (FilingStatus.SINGLE, Decimal("4150")),
        (FilingStatus.MFJ, Decimal("8300")),
    ]:
        inp = TaxReturnInput(
            tax_year=2024,
            filing_status=fs,
            adjustments=AdjustmentsData(hsa_contributions=Decimal("10000")),
            taxpayers=[
                Taxpayer(
                    role=TaxpayerRole.PRIMARY,
                    w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
                )
            ],
        )
        run = CalculationEngine(FED, inp).run()
        assert run.output.agi == Decimal("80000") - expected_limit
```

- [ ] **Step 4: Add capital loss limitation tests**

```python
from app.models.domain import Form1099BData


def test_capital_loss_limited_to_neg_3000() -> None:
    """Net capital losses are limited to -$3,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Big loss", proceeds=Decimal("1000"), cost_basis=Decimal("20000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Loss is -19000 but limited to -3000; gross = 60000 + (-3000) = 57000
    assert run.output.gross_income == Decimal("57000.00")


def test_capital_loss_at_exactly_neg_3000() -> None:
    """Exactly -$3,000 loss should pass through unchanged."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Small loss", proceeds=Decimal("2000"), cost_basis=Decimal("5000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("57000.00")


def test_capital_gain_not_affected_by_loss_limit() -> None:
    """Positive capital gains should not be affected by the loss limit rule."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
                form_1099_bs=[
                    Form1099BData(description="Gain", proceeds=Decimal("10000"), cost_basis=Decimal("3000"))
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("67000.00")
```

- [ ] **Step 5: Add SS benefits taxability tests**

```python
def test_ss_benefits_below_threshold_not_taxed() -> None:
    """SS benefits not taxed when provisional income is below base threshold.

    Provisional = $0 other income + 50% of $12,000 = $6,000, below $25k single threshold.
    Taxable SS = $0, so gross income = $0 (only the taxable portion enters gross income).
    Any SSA withholding would still produce a refund — this is correct IRS behavior.
    """
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("0.00")
    assert run.output.federal_tax == Decimal("0")
    assert run.output.refund_or_owed >= Decimal("0")


def test_ss_benefits_partially_taxed() -> None:
    """SS benefits partially taxed between base and upper thresholds."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("20000"), federal_withheld=Decimal("2000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Provisional = 20000 + 9000 = 29000
    # lower_calc = min((29000-25000)*0.50, (34000-25000)*0.50) = min(2000, 4500) = 2000
    # upper_calc = max((29000-34000)*0.85, 0) = 0
    # taxable SS = min(18000*0.85, 2000+0) = min(15300, 2000) = 2000
    assert run.output.gross_income == Decimal("22000.00")  # 20000 + 2000


def test_ss_benefits_max_85_percent_taxed() -> None:
    """High-income: up to 85% of SS benefits are taxable."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("24000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Provisional = 80000 + 12000 = 92000
    # lower_calc = min((92000-25000)*0.50, (34000-25000)*0.50) = min(33500, 4500) = 4500
    # upper_calc = max((92000-34000)*0.85, 0) = 49300
    # taxable SS = min(24000*0.85, 4500+49300) = min(20400, 53800) = 20400
    assert run.output.gross_income == Decimal("100400.00")  # 80000 + 20400
```

- [ ] **Step 6: Add bracket boundary test**

```python
@pytest.mark.parametrize(
    "fs,std_ded,first_bracket_top,expected_tax",
    [
        (FilingStatus.SINGLE, Decimal("14600"), Decimal("11600"), Decimal("1160")),
        (FilingStatus.MFJ, Decimal("29200"), Decimal("23200"), Decimal("2320")),
        (FilingStatus.MFS, Decimal("14600"), Decimal("11600"), Decimal("1160")),
        (FilingStatus.HOH, Decimal("21900"), Decimal("16550"), Decimal("1655")),
        (FilingStatus.QSS, Decimal("29200"), Decimal("23200"), Decimal("2320")),
    ],
)
def test_bracket_boundary_exact(
    fs: FilingStatus, std_ded: Decimal, first_bracket_top: Decimal, expected_tax: Decimal
) -> None:
    """Income at exact first bracket boundary for each filing status."""
    wages = first_bracket_top + std_ded
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=fs,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=wages, federal_withheld=expected_tax)],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == first_bracket_top
    assert run.output.federal_tax == expected_tax
```

- [ ] **Step 7: Add zero income across all filing statuses test**

```python
import pytest


@pytest.mark.parametrize("fs", list(FilingStatus))
def test_zero_income_all_filing_statuses(fs: FilingStatus) -> None:
    """Zero income should produce zero tax for all filing statuses."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=fs,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="None", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")
```

- [ ] **Step 8: Add mixed income household test**

```python
def test_mixed_income_household() -> None:
    """Full household: W-2 + 1099-NEC + 1099-INT + 1099-DIV + 1099-B + SSA + other + adjustments."""
    from app.models.domain import Form1099DIVData, Form1099INTData

    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        other_income=Decimal("500"),
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="Army", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
                form_1099_necs=[Form1099NECData(payer_name="Client", nonemployee_compensation=Decimal("10000"))],
                form_1099_ints=[Form1099INTData(payer_name="Bank", interest_income=Decimal("500"))],
                form_1099_divs=[Form1099DIVData(payer_name="Broker", ordinary_dividends=Decimal("1200"))],
                form_1099_bs=[Form1099BData(description="Stock", proceeds=Decimal("5000"), cost_basis=Decimal("3000"))],
                form_1099_ssas=[Form1099SSAData(total_benefits=Decimal("18000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()

    # Verify all income types flow through
    assert run.output.gross_income > Decimal("85000")
    # AGI should be reduced by adjustments (2500 + 300 = 2800)
    assert run.output.adjustments_total == Decimal("2800.00")
    assert run.output.agi == run.output.gross_income - Decimal("2800.00")
    # Should produce a valid tax result
    assert run.output.federal_tax > Decimal("0")
```

- [ ] **Step 9: Add IRA cap test**

```python
def test_ira_capped_at_7000() -> None:
    """IRA contributions capped at $7,000."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(ira_contributions=Decimal("10000")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("53000.00")  # 60000 - 7000
```

- [ ] **Step 10: Add SE tax deduction test**

```python
def test_se_tax_deduction_passthrough() -> None:
    """SE tax deduction is a pass-through (user provides the deductible half)."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(self_employment_tax_deduction=Decimal("3500")),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.agi == Decimal("56500.00")  # 60000 - 3500
```

- [ ] **Step 11: Add negative AGI (adjustments > gross) test**

```python
def test_agi_floors_at_zero() -> None:
    """AGI cannot go negative — max(gross - adj, 0) floors at zero."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(
            ira_contributions=Decimal("7000"),
            hsa_contributions=Decimal("4150"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("5000"), federal_withheld=Decimal("500"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # gross = 5000, adjustments = 7000 + 4150 = 11150, but AGI = max(5000 - 11150, 0) = 0
    assert run.output.agi == Decimal("0.00")
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")
```

- [ ] **Step 12: Add multiple adjustments stacking test**

```python
def test_multiple_adjustments_stack() -> None:
    """Multiple adjustments should all reduce AGI."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
            ira_contributions=Decimal("7000"),
            hsa_contributions=Decimal("4150"),
        ),
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    # Total adjustments: 2500 + 300 + 7000 + 4150 = 13950
    assert run.output.adjustments_total == Decimal("13950.00")
    assert run.output.agi == Decimal("66050.00")  # 80000 - 13950
```

- [ ] **Step 13: Run all new tests**

Run: `pytest tests/test_golden_m1.py -v`
Expected: ALL PASS

- [ ] **Step 14: Run full test suite**

Run: `ruff check . && mypy . && pytest`
Expected: ALL PASS

- [ ] **Step 15: Commit**

```bash
git add tests/test_golden_m1.py
git commit -m "test: add comprehensive edge-case vectors for federal completeness"
```

---

## Chunk 6: Final Verification

### Task 9: Full verification and cleanup

- [ ] **Step 1: Run definition-of-done checks**

```bash
ruff check .
mypy .
pytest -v
```

All three must pass with zero errors.

- [ ] **Step 2: Verify backward compatibility**

Run specifically:

```bash
pytest tests/test_golden.py tests/test_golden2.py tests/test_milestone6_routes.py -v
```

All existing milestone tests must pass unchanged (except trace ID sets updated in Task 7).

- [ ] **Step 3: Verify new test coverage**

```bash
pytest tests/test_golden_m1.py -v --tb=short
```

Should show ~18 tests passing.

- [ ] **Step 4: Final commit with all changes**

Only if there are any remaining uncommitted fixes:

```bash
git add -A
git commit -m "chore: final cleanup for Federal Completeness milestone"
```
