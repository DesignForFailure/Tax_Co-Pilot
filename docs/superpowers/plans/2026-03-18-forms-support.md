# Forms Support Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Map calculated outputs to IRS form-oriented workflows, add export-ready form structures, improve input capture coverage, and introduce consistency checks between calculated outputs and form mappings.

**Architecture:** A new `app/models/forms.py` defines Pydantic models mirroring IRS Form 1040 and Schedule 1 line items. A new `app/services/form_mapper.py` reads the `form_line` annotation stored on each `TraceNode` and maps resolved values into form models. Informational-only lines (tax-exempt interest, qualified dividends, total SS benefits) are derived from the `input_snapshot`. Consistency checks validate that form-line relationships hold (e.g., Line 11 = Line 9 - Line 10). Estimated tax payments are added as a new calculation-impacting input, creating new rules for total payments and updating refund/owed. The calculate form gets new sections for adjustments, estimated payments, and other income.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, Jinja2, PyYAML, Decimal, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `app/models/domain.py` | Modify | Add `form_line` to TraceNode, `estimated_tax_payments` to TaxReturnInput, `tax_exempt_interest` to Form1099INTData, new helper methods, new ReturnOutput fields |
| `app/models/forms.py` | Create | Form1040Lines, Schedule1Lines, FormPacket Pydantic models |
| `app/engine/calculator.py` | Modify | Resolve new inputs, set `form_line` on trace nodes, update ReturnOutput population |
| `rule_packs/federal/2024/federal_2024_rules.yaml` | Modify | Add estimated_payments, total_payments rules; update refund_or_owed |
| `app/services/form_mapper.py` | Create | Map ReturnRun → FormPacket, consistency checks |
| `main.py` | Modify | Parse adjustments/estimated payments from form; add /runs/{id}/forms and /runs/{id}/export/forms routes |
| `app/templates/pages/calculate.html` | Modify | Add adjustments section, estimated payments, other income |
| `app/templates/pages/forms_view.html` | Create | IRS form-oriented view of calculation results |
| `app/templates/pages/dashboard.html` | Modify | Add "View Forms" button |
| `tests/test_forms.py` | Create | Form mapping, consistency checks, route integration tests |
| `tests/test_golden.py` | Modify | Update `test_trace_contains_all_rules` expected set |
| `tests/test_golden2.py` | Modify | Update `test_trace_completeness` expected set |
| `README.md` | Modify | Add new files to tree |
| `CHANGELOG.md` | Modify | Record milestone 3 changes |

---

## Chunk 1: Domain Model Extensions

### Task 1: Add form_line to TraceNode

**Files:**
- Modify: `app/models/domain.py:215-223`
- Test: `tests/test_forms.py` (create)

- [ ] **Step 1: Write failing test for form_line on TraceNode**

Create `tests/test_forms.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for Milestone 3: Forms Support.

Covers: form_line on TraceNode, form data models, form mapper,
consistency checks, estimated tax payments, and form routes.
"""

from decimal import Decimal

from app.models.domain import TraceNode


def test_trace_node_has_form_line() -> None:
    node = TraceNode(
        node_id="test",
        rule_id="test.rule",
        rule_pack_version="1.0.0",
        description="Test",
        inputs={},
        result={"value": "100"},
        explanation="test",
        form_line="1040 Line 1a",
    )
    assert node.form_line == "1040 Line 1a"


def test_trace_node_form_line_defaults_empty() -> None:
    node = TraceNode(
        node_id="test",
        rule_id="test.rule",
        rule_pack_version="1.0.0",
        description="Test",
        inputs={},
        result={"value": "100"},
        explanation="test",
    )
    assert node.form_line == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_forms.py::test_trace_node_has_form_line -v`
Expected: FAIL — TraceNode does not accept `form_line`

- [ ] **Step 3: Add form_line field to TraceNode**

In `app/models/domain.py`, add to TraceNode class (after `explanation`):

```python
    form_line: str = ""
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/domain.py tests/test_forms.py
git commit -m "feat(forms): add form_line field to TraceNode"
```

---

### Task 2: Add estimated_tax_payments and helpers to domain models

**Files:**
- Modify: `app/models/domain.py:72-76` (Form1099INTData), `app/models/domain.py:144-207` (TaxReturnInput)
- Test: `tests/test_forms.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_forms.py`:

```python
from app.models.domain import (
    FilingStatus,
    Form1099DIVData,
    Form1099INTData,
    Form1099SSAData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)


def test_tax_exempt_interest_field() -> None:
    f = Form1099INTData(
        payer_name="Muni Bank",
        interest_income=Decimal("500"),
        tax_exempt_interest=Decimal("200"),
    )
    assert f.tax_exempt_interest == Decimal("200")


def test_estimated_tax_payments_field() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        estimated_tax_payments=Decimal("5000"),
    )
    assert inp.estimated_tax_payments == Decimal("5000")


def test_estimated_tax_payments_defaults_zero() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
    )
    assert inp.estimated_tax_payments == Decimal("0")


def test_total_qualified_dividends() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_divs=[
                    Form1099DIVData(ordinary_dividends=Decimal("1000"), qualified_dividends=Decimal("800")),
                    Form1099DIVData(ordinary_dividends=Decimal("500"), qualified_dividends=Decimal("300")),
                ],
            )
        ],
    )
    assert inp.total_qualified_dividends() == Decimal("1100")


def test_total_tax_exempt_interest() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_ints=[
                    Form1099INTData(interest_income=Decimal("500"), tax_exempt_interest=Decimal("200")),
                    Form1099INTData(interest_income=Decimal("300"), tax_exempt_interest=Decimal("100")),
                ],
            )
        ],
    )
    assert inp.total_tax_exempt_interest() == Decimal("300")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_forms.py::test_tax_exempt_interest_field -v`
Expected: FAIL

- [ ] **Step 3: Implement domain model changes**

In `app/models/domain.py`:

1. Add to `Form1099INTData` (after `federal_withheld`):
```python
    tax_exempt_interest: Decimal = Decimal("0")  # Box 8
```

2. Add to `TaxReturnInput` (after `adjustments` field):
```python
    estimated_tax_payments: Decimal = Decimal("0")
```

3. Add methods to `TaxReturnInput` (after `total_adjustments`):
```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/domain.py tests/test_forms.py
git commit -m "feat(forms): add estimated_tax_payments, tax_exempt_interest, qualified_dividends helpers"
```

---

### Task 3: Create form data models

**Files:**
- Create: `app/models/forms.py`
- Test: `tests/test_forms.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_forms.py`:

```python
from app.models.forms import Form1040Lines, FormPacket, Schedule1Lines


def test_form_1040_lines_defaults() -> None:
    f = Form1040Lines()
    assert f.line_1a == Decimal("0")
    assert f.line_9 == Decimal("0")
    assert f.line_34 == Decimal("0")


def test_schedule_1_lines_defaults() -> None:
    s = Schedule1Lines()
    assert s.line_3 == Decimal("0")
    assert s.line_26 == Decimal("0")


def test_form_packet_construction() -> None:
    pkt = FormPacket(
        tax_year=2024,
        filing_status="mfj",
        form_1040=Form1040Lines(line_1a=Decimal("85000")),
        schedule_1=Schedule1Lines(),
    )
    assert pkt.form_1040.line_1a == Decimal("85000")
    assert pkt.consistency_errors == []


def test_form_packet_serializes_to_json() -> None:
    pkt = FormPacket(
        tax_year=2024,
        filing_status="single",
        form_1040=Form1040Lines(),
        schedule_1=Schedule1Lines(),
    )
    data = pkt.model_dump()
    assert data["tax_year"] == 2024
    assert "line_1a" in data["form_1040"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_forms.py::test_form_1040_lines_defaults -v`
Expected: FAIL — module `app.models.forms` not found

- [ ] **Step 3: Create `app/models/forms.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/models/forms.py tests/test_forms.py
git commit -m "feat(forms): create Form1040Lines, Schedule1Lines, FormPacket models"
```

---

## Chunk 2: Engine and Rule Updates

### Task 4: Add estimated_payments and total_payments rules

**Files:**
- Modify: `rule_packs/federal/2024/federal_2024_rules.yaml`

- [ ] **Step 1: Add rules to YAML**

Insert before the existing `fed.2024.refund_or_owed` rule (after `fed.2024.total_withholding`):

```yaml
  - id: "fed.2024.estimated_payments"
    description: "Estimated tax payments made during the year"
    form_line: "1040 Line 26"
    type: "sum"
    inputs:
      items: { ref: "input.estimated_payments" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2024.total_payments"
    description: "Total payments (withholding + estimated)"
    form_line: "1040 Line 33"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2024.total_withholding" }
        - { ref: "fed.2024.estimated_payments" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2
```

Update `fed.2024.refund_or_owed` to use `total_payments`:

```yaml
  - id: "fed.2024.refund_or_owed"
    description: "Refund (positive) or amount owed (negative)"
    form_line: "1040 Line 34/37"
    type: "formula"
    expression: "payments - tax"
    inputs:
      payments: { ref: "fed.2024.total_payments" }
      tax: { ref: "fed.2024.tax.brackets" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

- [ ] **Step 2: Verify rule pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/federal/2024')); print(f'Loaded {len(p.rules)} rules')"`
Expected: Loaded 31 rules (was 29)

- [ ] **Step 3: Commit**

```bash
git add rule_packs/federal/2024/federal_2024_rules.yaml
git commit -m "feat(forms): add estimated_payments and total_payments rules"
```

---

### Task 5: Update calculator — resolve inputs and set form_line

**Files:**
- Modify: `app/engine/calculator.py:196-219` (_resolve_inputs), `app/engine/calculator.py:272-459` (eval methods)

- [ ] **Step 1: Write failing test for estimated payments**

Append to `tests/test_forms.py`:

```python
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack

FED = RulePack.load(Path("rule_packs/federal/2024"))


def test_estimated_payments_reduces_owed() -> None:
    """With $50k wages, $6k withheld, $2k estimated → refund increases by $2k."""
    base = TaxReturnInput(
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
    run_base = CalculationEngine(FED, base).run()

    with_est = base.model_copy(update={"estimated_tax_payments": Decimal("2000")})
    run_est = CalculationEngine(FED, with_est).run()

    assert run_est.output.estimated_tax_payments == Decimal("2000.00")
    assert run_est.output.total_payments == Decimal("8000.00")
    assert run_est.output.refund_or_owed == run_base.output.refund_or_owed + 2000


def test_trace_nodes_have_form_line() -> None:
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
    wages_trace = next(t for t in run.trace if t.rule_id == "fed.2024.gross_income.wages")
    assert wages_trace.form_line == "1040 Line 1a"
    agi_trace = next(t for t in run.trace if t.rule_id == "fed.2024.agi.total")
    assert agi_trace.form_line == "1040 Line 11"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_forms.py::test_estimated_payments_reduces_owed -v`
Expected: FAIL — `estimated_tax_payments` not in ReturnOutput or `input.estimated_payments` not resolved

- [ ] **Step 3: Update _resolve_inputs in calculator.py**

Add to `_resolve_inputs()` (after the adjustments block):

```python
        self.resolved["input.estimated_payments"] = self.inputs.estimated_tax_payments
```

- [ ] **Step 4: Set form_line on TraceNode in all eval methods**

In `_eval_sum`, `_eval_formula`, `_eval_lookup`, and `_eval_bracket_table`, add `form_line=rule.get("form_line", ""),` to each `TraceNode(...)` constructor call. For each method, add it as a keyword argument alongside the existing fields.

Example for `_eval_sum` (the others follow the same pattern):
```python
        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"items": [str(v) for v in values]},
                intermediates=[],
                result={...},
                explanation=...,
                form_line=rule.get("form_line", ""),
            )
        )
```

- [ ] **Step 5: Update ReturnOutput and calculator.run()**

In `app/models/domain.py`, add to `ReturnOutput` (after `adjustments_total`):
```python
    estimated_tax_payments: Decimal = Decimal("0")
    total_payments: Decimal = Decimal("0")
```

In `app/engine/calculator.py`, update `run()` method's `ReturnOutput(...)` constructor:
```python
        output = ReturnOutput(
            gross_income=self.resolved.get("fed.2024.gross_income.total", Decimal("0")),
            agi=self.resolved.get("fed.2024.agi.total", Decimal("0")),
            standard_deduction=self.resolved.get("fed.2024.standard_deduction", Decimal("0")),
            taxable_income=self.resolved.get("fed.2024.taxable_income", Decimal("0")),
            federal_tax=self.resolved.get("fed.2024.tax.brackets", Decimal("0")),
            total_withholding=self.resolved.get("fed.2024.total_withholding", Decimal("0")),
            refund_or_owed=self.resolved.get("fed.2024.refund_or_owed", Decimal("0")),
            adjustments_total=self.resolved.get("fed.2024.adjustments.total", Decimal("0")),
            estimated_tax_payments=self.resolved.get("fed.2024.estimated_payments", Decimal("0")),
            total_payments=self.resolved.get("fed.2024.total_payments", Decimal("0")),
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add app/models/domain.py app/engine/calculator.py tests/test_forms.py
git commit -m "feat(forms): resolve estimated payments, set form_line on traces, update ReturnOutput"
```

---

### Task 6: Update existing trace tests for new rules

**Files:**
- Modify: `tests/test_golden.py:197-228`
- Modify: `tests/test_golden2.py:106-137`

- [ ] **Step 1: Add new rule IDs to expected sets**

In both `test_trace_contains_all_rules` (test_golden.py) and `test_trace_completeness` (test_golden2.py), add to the `expected` set:

```python
        "fed.2024.estimated_payments",
        "fed.2024.total_payments",
```

- [ ] **Step 2: Run golden tests to verify they pass**

Run: `python -m pytest tests/test_golden.py tests/test_golden2.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_golden.py tests/test_golden2.py
git commit -m "test(forms): update trace completeness tests for estimated_payments/total_payments rules"
```

---

## Chunk 3: Form Mapper Service

### Task 7: Create form mapper with mapping logic

**Files:**
- Create: `app/services/form_mapper.py`
- Test: `tests/test_forms.py`

- [ ] **Step 1: Write failing test for form mapping**

Append to `tests/test_forms.py`:

```python
from app.services.form_mapper import map_return_run


def test_map_return_run_basic() -> None:
    """Map a simple W-2 scenario to form lines."""
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
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.tax_year == 2024
    assert pkt.filing_status == "mfj"
    assert pkt.form_1040.line_1a == Decimal("85000.00")
    assert pkt.form_1040.line_9 == Decimal("85000.00")
    assert pkt.form_1040.line_11 == Decimal("85000.00")
    assert pkt.form_1040.line_13 == Decimal("29200")
    assert pkt.form_1040.line_15 == Decimal("55800")
    assert pkt.form_1040.line_16 == Decimal("6232")
    assert pkt.form_1040.line_25d == Decimal("12000.00")
    assert pkt.form_1040.line_33 == Decimal("12000.00")
    assert pkt.form_1040.line_34 == Decimal("5768")
    assert pkt.form_1040.line_37 == Decimal("0")


def test_map_return_run_informational_lines() -> None:
    """Qualified dividends and tax-exempt interest appear on form."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
                form_1099_ints=[
                    Form1099INTData(interest_income=Decimal("500"), tax_exempt_interest=Decimal("200")),
                ],
                form_1099_divs=[
                    Form1099DIVData(ordinary_dividends=Decimal("1000"), qualified_dividends=Decimal("800")),
                ],
                form_1099_ssas=[
                    Form1099SSAData(total_benefits=Decimal("18000")),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.form_1040.line_2a == Decimal("200")
    assert pkt.form_1040.line_3a == Decimal("800")
    assert pkt.form_1040.line_6a == Decimal("18000")


def test_map_return_run_schedule1() -> None:
    """Schedule 1 lines are populated for adjustments."""
    from app.models.domain import AdjustmentsData

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
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
        ),
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.schedule_1.line_21 == Decimal("2500.00")
    assert pkt.schedule_1.line_11 == Decimal("300.00")
    assert pkt.schedule_1.line_26 == Decimal("2800.00")
    assert pkt.form_1040.line_10 == Decimal("2800.00")


def test_map_return_run_amount_owed() -> None:
    """When tax > payments, line_37 shows amount owed."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("5000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    # Tax should exceed withholding → line_37 > 0, line_34 == 0
    assert pkt.form_1040.line_37 > 0
    assert pkt.form_1040.line_34 == Decimal("0")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_forms.py::test_map_return_run_basic -v`
Expected: FAIL — `form_mapper` module not found

- [ ] **Step 3: Create `app/services/form_mapper.py`**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Map ReturnRun trace data to IRS form-oriented models.

Reads the form_line annotation on each TraceNode and populates
Form1040Lines and Schedule1Lines. Informational-only values
(tax-exempt interest, qualified dividends, total SS benefits)
are derived from the input snapshot.
"""

from __future__ import annotations

from decimal import Decimal

from app.models.domain import ReturnRun
from app.models.forms import Form1040Lines, FormPacket, Schedule1Lines

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
    "1040 Line 33": ("form_1040", "line_33"),
    "Schedule 1 Line 3": ("schedule_1", "line_3"),
    "Schedule 1 Line 8": ("schedule_1", "line_8"),
    "Schedule 1 Line 11": ("schedule_1", "line_11"),
    "Schedule 1 Line 13": ("schedule_1", "line_13"),
    "Schedule 1 Line 15": ("schedule_1", "line_15"),
    "Schedule 1 Line 20": ("schedule_1", "line_20"),
    "Schedule 1 Line 21": ("schedule_1", "line_21"),
    "Schedule 1 Line 26": ("schedule_1", "line_26"),
}


def map_return_run(run: ReturnRun) -> FormPacket:
    """Map a ReturnRun to a FormPacket of IRS form line items."""
    form_1040 = Form1040Lines()
    schedule_1 = Schedule1Lines()
    forms = {"form_1040": form_1040, "schedule_1": schedule_1}

    # Map traced values to form lines using form_line annotations
    for trace in run.trace:
        if not trace.form_line:
            continue
        value = Decimal(str(trace.result.get("value", "0")))
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
    if form_1040.line_33 > form_1040.line_16:
        form_1040.line_34 = form_1040.line_33 - form_1040.line_16
        form_1040.line_37 = Decimal("0")
    else:
        form_1040.line_34 = Decimal("0")
        form_1040.line_37 = form_1040.line_16 - form_1040.line_33

    # Consistency checks
    errors = _check_consistency(form_1040, schedule_1)

    return FormPacket(
        tax_year=run.tax_year,
        filing_status=run.filing_status.value,
        form_1040=form_1040,
        schedule_1=schedule_1,
        consistency_errors=errors,
    )


def _check_consistency(f: Form1040Lines, s: Schedule1Lines) -> list[str]:
    """Validate IRS form line relationships.

    Returns a list of human-readable error strings (empty if consistent).
    """
    errors: list[str] = []

    # AGI should not exceed total income
    if f.line_11 > f.line_9:
        errors.append(
            f"Line 11 (AGI={f.line_11}) exceeds Line 9 (total income={f.line_9})"
        )

    # Taxable income should not exceed AGI
    if f.line_15 > f.line_11:
        errors.append(
            f"Line 15 (taxable={f.line_15}) exceeds Line 11 (AGI={f.line_11})"
        )

    # Total payments = withholding + estimated
    expected_payments = f.line_25d + f.line_26
    if f.line_33 != expected_payments:
        errors.append(
            f"Line 33 (total payments={f.line_33}) != "
            f"Line 25d ({f.line_25d}) + Line 26 ({f.line_26})"
        )

    # Refund and owed should be mutually exclusive
    if f.line_34 > 0 and f.line_37 > 0:
        errors.append("Both Line 34 (refund) and Line 37 (owed) are positive")

    # Schedule 1 Line 10 = sum of Part I lines
    expected_s1_10 = s.line_3 + s.line_8
    if s.line_10 != expected_s1_10:
        errors.append(
            f"Schedule 1 Line 10 ({s.line_10}) != Line 3 ({s.line_3}) + Line 8 ({s.line_8})"
        )

    return errors
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/form_mapper.py tests/test_forms.py
git commit -m "feat(forms): create form_mapper service with mapping and consistency checks"
```

---

### Task 8: Test consistency checks

**Files:**
- Test: `tests/test_forms.py`

- [ ] **Step 1: Write consistency check tests**

Append to `tests/test_forms.py`:

```python
def test_consistency_checks_pass_for_valid_run() -> None:
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
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_consistency_checks_pass_zero_income() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_consistency_checks_pass_with_estimated_payments() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("10000"))],
            )
        ],
        estimated_tax_payments=Decimal("5000"),
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []
    assert pkt.form_1040.line_26 == Decimal("5000.00")
    assert pkt.form_1040.line_33 == Decimal("15000.00")
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -k consistency -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_forms.py
git commit -m "test(forms): add consistency check validation tests"
```

---

## Chunk 4: Routes, Templates, and UI

### Task 9: Add adjustments and estimated payments to calculate form

**Files:**
- Modify: `app/templates/pages/calculate.html`
- Modify: `main.py:439-465` (_parse_tax_input_from_form)

- [ ] **Step 1: Write failing route test**

Append to `tests/test_forms.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db
from main import app

CSRF = "test-csrf-token"


@pytest.fixture()
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def test_calculate_with_adjustments(_ensure_db: None) -> None:
    client = _client()
    form = {
        "csrf_token": CSRF,
        "tax_year": "2024",
        "filing_status": "single",
        "p_first": "Test",
        "p_last": "User",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "50000",
        "p_w2_0_federal_withheld": "6000",
        "adj_student_loan": "2500",
        "adj_educator": "300",
        "adj_hsa": "1000",
        "adj_ira": "3000",
        "estimated_payments": "2000",
        "other_income": "500",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303

    from app.services.database import list_return_runs

    runs = list_return_runs()
    assert runs
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_forms.py::test_calculate_with_adjustments -v`
Expected: FAIL — adjustments fields not parsed from form

- [ ] **Step 3: Update `_parse_tax_input_from_form` in main.py**

Update the function to parse adjustments, estimated payments, and other income:

```python
def _parse_tax_input_from_form(fd: FormData) -> TaxReturnInput:
    """Convert raw multi-part form data into a validated ``TaxReturnInput``."""
    tax_year = int(str(fd.get("tax_year", "2024") or "2024"))
    filing_status = FilingStatus(str(fd.get("filing_status", "mfj") or "mfj"))

    primary = _parse_taxpayer(fd, "p", TaxpayerRole.PRIMARY)
    taxpayers: list[Taxpayer] = [primary]

    # Spouse is only expected for MFJ/MFS
    if filing_status in (FilingStatus.MFJ, FilingStatus.MFS):
        s_first = _form_str(fd, "s_first")
        s_last = _form_str(fd, "s_last")
        has_spouse_income = bool(
            _collect_indices(fd, "s_w2")
            or _collect_indices(fd, "s_1099int")
            or _collect_indices(fd, "s_1099div")
            or _collect_indices(fd, "s_1099b")
        )
        if s_first or s_last or has_spouse_income:
            taxpayers.append(_parse_taxpayer(fd, "s", TaxpayerRole.SPOUSE))

    from app.models.domain import AdjustmentsData

    adjustments = AdjustmentsData(
        student_loan_interest=_form_money(fd, "adj_student_loan"),
        educator_expenses=_form_money(fd, "adj_educator"),
        hsa_contributions=_form_money(fd, "adj_hsa"),
        ira_contributions=_form_money(fd, "adj_ira"),
        self_employment_tax_deduction=_form_money(fd, "adj_se_tax"),
    )

    return TaxReturnInput(
        tax_year=tax_year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        adjustments=adjustments,
        estimated_tax_payments=_form_money(fd, "estimated_payments"),
        other_income=_form_money(fd, "other_income"),
    )
```

Also add `AdjustmentsData` to the imports from `app.models.domain` at the top of `main.py`:
```python
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    ...
)
```
(And remove the local import from inside the function.)

- [ ] **Step 4: Add form sections to `calculate.html`**

Add before the submit button, after the spouse section:

```html
    {# ─── Other Income ────────────────────────────────────────── #}
    <div class="card">
        <h2>Other Income</h2>
        <div class="form-row">
            <div><label>Other Income (Schedule 1)</label><input type="text" name="other_income" placeholder="0"></div>
        </div>
    </div>

    {# ─── Above-the-Line Deductions ──────────────────────────── #}
    <div class="card">
        <h2>Above-the-Line Deductions</h2>
        <p class="text-dim text-sm" style="margin-bottom:12px;">These reduce your AGI. Leave blank or 0 if not applicable.</p>
        <div class="form-row">
            <div><label>Student Loan Interest</label><input type="text" name="adj_student_loan" placeholder="0"></div>
            <div><label>Educator Expenses</label><input type="text" name="adj_educator" placeholder="0"></div>
        </div>
        <div class="form-row">
            <div><label>HSA Contributions</label><input type="text" name="adj_hsa" placeholder="0"></div>
            <div><label>IRA Contributions</label><input type="text" name="adj_ira" placeholder="0"></div>
        </div>
        <div class="form-row">
            <div><label>SE Tax Deduction</label><input type="text" name="adj_se_tax" placeholder="0"></div>
        </div>
    </div>

    {# ─── Estimated Payments ─────────────────────────────────── #}
    <div class="card">
        <h2>Estimated Tax Payments</h2>
        <div class="form-row">
            <div><label>Estimated Payments (1040 Line 26)</label><input type="text" name="estimated_payments" placeholder="0"></div>
        </div>
    </div>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py::test_calculate_with_adjustments -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add main.py app/templates/pages/calculate.html tests/test_forms.py
git commit -m "feat(forms): wire adjustments, estimated payments, other income to calculate form"
```

---

### Task 10: Add forms view route and template

**Files:**
- Modify: `main.py`
- Create: `app/templates/pages/forms_view.html`
- Modify: `app/templates/pages/dashboard.html`

- [ ] **Step 1: Write failing test**

Append to `tests/test_forms.py`:

```python
def _create_run(client: TestClient) -> str:
    form = {
        "csrf_token": CSRF,
        "tax_year": "2024",
        "filing_status": "mfj",
        "p_first": "Jane",
        "p_last": "Doe",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "85000",
        "p_w2_0_federal_withheld": "12000",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303
    from app.services.database import list_return_runs

    runs = list_return_runs()
    return str(runs[0]["id"])


def test_forms_view_route(_ensure_db: None) -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/forms")
    assert r.status_code == 200
    assert "Form 1040" in r.text
    assert "Line 1a" in r.text
    assert "85,000" in r.text


def test_forms_view_not_found(_ensure_db: None) -> None:
    client = _client()
    r = client.get("/runs/nonexistent-id/forms")
    assert r.status_code == 404


def test_forms_export_route(_ensure_db: None) -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/export/forms")
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    import json

    data = json.loads(r.content)
    assert "form_1040" in data
    assert "schedule_1" in data
    assert data["form_1040"]["line_1a"] == "85000.00"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_forms.py::test_forms_view_route -v`
Expected: FAIL — route not found (404)

- [ ] **Step 3: Add routes to main.py**

Add after the existing `/runs/{run_id}/export/html` route:

```python
# ─── Form-Oriented View ──────────────────────────────────────


@app.get("/runs/{run_id}/forms", response_class=HTMLResponse)
def view_run_forms(request: Request, run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})

    from app.services.form_mapper import map_return_run

    packet = map_return_run(run)
    return templates.TemplateResponse(
        "pages/forms_view.html", {"request": request, "run": run, "packet": packet}
    )


@app.get("/runs/{run_id}/export/forms")
def export_run_forms(run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})

    from app.services.form_mapper import map_return_run

    packet = map_return_run(run)
    json_bytes = json.dumps(
        json.loads(packet.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="forms_{run_id}.json"'},
    )
```

- [ ] **Step 4: Create `app/templates/pages/forms_view.html`**

```html
{% extends "layouts/base.html" %}
{% block title %}Form View{% endblock %}
{% block content %}

<h1 style="font-size: 24px; margin-bottom: 8px;">IRS Form View — Tax Year {{ packet.tax_year }}</h1>
<p class="text-dim text-sm mb-4">Filing Status: {{ packet.filing_status|upper }}</p>

<div style="display:flex;gap:10px;margin-bottom:16px;">
    <a href="/runs/{{ run.id }}/export/forms" class="btn btn-sm btn-outline">Export Forms JSON</a>
    <a href="/runs/{{ run.id }}" class="btn btn-sm btn-outline">Back to Summary</a>
</div>

{% if packet.consistency_errors %}
<div class="card" style="border-left: 3px solid var(--negative, #e53e3e);">
    <h2>Consistency Warnings</h2>
    {% for err in packet.consistency_errors %}
    <p class="text-dim text-sm">{{ err }}</p>
    {% endfor %}
</div>
{% endif %}

<div class="card">
    <h2>Form 1040 — U.S. Individual Income Tax Return</h2>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="border-bottom:2px solid var(--border);">
                <th style="text-align:left;padding:8px;">Line</th>
                <th style="text-align:left;padding:8px;">Description</th>
                <th style="text-align:right;padding:8px;">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% set lines = [
                ("1a", "Wages, salaries, tips", packet.form_1040.line_1a),
                ("2a", "Tax-exempt interest", packet.form_1040.line_2a),
                ("2b", "Taxable interest", packet.form_1040.line_2b),
                ("3a", "Qualified dividends", packet.form_1040.line_3a),
                ("3b", "Ordinary dividends", packet.form_1040.line_3b),
                ("6a", "Social Security benefits", packet.form_1040.line_6a),
                ("6b", "Taxable Social Security", packet.form_1040.line_6b),
                ("7", "Capital gain or (loss)", packet.form_1040.line_7),
                ("8", "Other income (Schedule 1)", packet.form_1040.line_8),
                ("9", "Total income", packet.form_1040.line_9),
                ("10", "Adjustments (Schedule 1)", packet.form_1040.line_10),
                ("11", "Adjusted gross income", packet.form_1040.line_11),
                ("13", "Standard deduction", packet.form_1040.line_13),
                ("15", "Taxable income", packet.form_1040.line_15),
                ("16", "Tax", packet.form_1040.line_16),
                ("25d", "Federal tax withheld", packet.form_1040.line_25d),
                ("26", "Estimated tax payments", packet.form_1040.line_26),
                ("33", "Total payments", packet.form_1040.line_33),
                ("34", "Overpaid (refund)", packet.form_1040.line_34),
                ("37", "Amount owed", packet.form_1040.line_37),
            ] %}
            {% for num, desc, val in lines %}
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:8px;font-weight:600;">{{ num }}</td>
                <td style="padding:8px;">{{ desc }}</td>
                <td style="padding:8px;text-align:right;font-variant-numeric:tabular-nums;">
                    {% if val >= 0 %}${{ "{:,.0f}".format(val) }}{% else %}-${{ "{:,.0f}".format(val|abs) }}{% endif %}
                </td>
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

{% if packet.schedule_1.line_3 or packet.schedule_1.line_8 or packet.schedule_1.line_26 %}
<div class="card">
    <h2>Schedule 1 — Additional Income and Adjustments</h2>
    <table style="width:100%;border-collapse:collapse;">
        <thead>
            <tr style="border-bottom:2px solid var(--border);">
                <th style="text-align:left;padding:8px;">Line</th>
                <th style="text-align:left;padding:8px;">Description</th>
                <th style="text-align:right;padding:8px;">Amount</th>
            </tr>
        </thead>
        <tbody>
            {% set s1_lines = [
                ("3", "Business income (1099-NEC)", packet.schedule_1.line_3),
                ("8", "Other income", packet.schedule_1.line_8),
                ("10", "Total additional income", packet.schedule_1.line_10),
                ("11", "Educator expenses", packet.schedule_1.line_11),
                ("13", "HSA deduction", packet.schedule_1.line_13),
                ("15", "SE tax deduction", packet.schedule_1.line_15),
                ("20", "IRA deduction", packet.schedule_1.line_20),
                ("21", "Student loan interest", packet.schedule_1.line_21),
                ("26", "Total adjustments", packet.schedule_1.line_26),
            ] %}
            {% for num, desc, val in s1_lines %}
            {% if val %}
            <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:8px;font-weight:600;">{{ num }}</td>
                <td style="padding:8px;">{{ desc }}</td>
                <td style="padding:8px;text-align:right;font-variant-numeric:tabular-nums;">
                    ${{ "{:,.0f}".format(val) }}
                </td>
            </tr>
            {% endif %}
            {% endfor %}
        </tbody>
    </table>
</div>
{% endif %}

{% endblock %}
```

- [ ] **Step 5: Add "View Forms" button to dashboard.html**

In `app/templates/pages/dashboard.html`, add after the export buttons:

```html
    <a href="/runs/{{ run.id }}/forms" class="btn btn-sm btn-outline">View Forms</a>
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add main.py app/templates/pages/forms_view.html app/templates/pages/dashboard.html tests/test_forms.py
git commit -m "feat(forms): add /runs/{id}/forms view and /runs/{id}/export/forms routes"
```

---

## Chunk 5: Final Validation and Documentation

### Task 11: Run full test suite and lint checks

- [ ] **Step 1: Run ruff**

Run: `ruff check .`
Expected: PASS (no new violations)

- [ ] **Step 2: Run mypy**

Run: `mypy .`
Expected: PASS (no new errors)

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass including new test_forms.py

- [ ] **Step 4: Fix any issues found**

If lint/type/test errors, fix them before proceeding.

---

### Task 12: Update README tree and CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update README.md file tree**

Add new files to the tree:
- `app/models/forms.py` (under `app/models/`)
- `app/services/form_mapper.py` (under `app/services/`)
- `app/templates/pages/forms_view.html` (under `app/templates/pages/`)
- `tests/test_forms.py` (under `tests/`)

- [ ] **Step 2: Update CHANGELOG.md**

Add under `## [Unreleased]`:

```markdown
### Added
- Form data models (`Form1040Lines`, `Schedule1Lines`, `FormPacket`) mapping engine outputs to IRS form line items.
- Form mapper service (`app/services/form_mapper.py`) with consistency checks between calculated outputs and form lines.
- `form_line` field on `TraceNode` for structured form-line annotation on every trace entry.
- Estimated tax payments input field and rules (`fed.2024.estimated_payments`, `fed.2024.total_payments`).
- Tax-exempt interest field on `Form1099INTData` and qualified dividends helper on `TaxReturnInput`.
- Above-the-line deductions, estimated payments, and other income sections on the calculate form.
- `/runs/{id}/forms` route: IRS form-oriented view of calculation results.
- `/runs/{id}/export/forms` route: downloadable JSON export of form data.
- "View Forms" button on the dashboard.
- `estimated_tax_payments` and `total_payments` fields on `ReturnOutput`.
- Comprehensive form mapping and consistency check tests.

### Changed
- `fed.2024.refund_or_owed` now uses total payments (withholding + estimated) instead of withholding alone.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: update README tree and CHANGELOG for Milestone 3 Forms Support"
```

---

### Task 13: Session log entry

**Files:**
- Modify: `.agent_tools/05_session_log.md`

- [ ] **Step 1: Append session log entry**

```
- [2026-03-18] app/models/forms.py, app/services/form_mapper.py, app/models/domain.py, app/engine/calculator.py, rule_packs/federal/2024/federal_2024_rules.yaml, main.py, app/templates/pages/calculate.html, app/templates/pages/forms_view.html, app/templates/pages/dashboard.html, tests/test_forms.py, tests/test_golden.py, tests/test_golden2.py, README.md, CHANGELOG.md: Milestone 3 — form data models (Form1040Lines/Schedule1Lines/FormPacket), form mapper with consistency checks, estimated_tax_payments/total_payments rules, form_line on TraceNode, adjustments/estimated payments on calculate form, /runs/{id}/forms view and /export/forms routes.
```

- [ ] **Step 2: Commit**

```bash
git add .agent_tools/05_session_log.md
git commit -m "log: record Milestone 3 session entry"
```

---

## Summary of Deliverables

| Deliverable | Files |
|------------|-------|
| Form data models | `app/models/forms.py` |
| Form mapper + consistency checks | `app/services/form_mapper.py` |
| TraceNode form_line, estimated payments, tax-exempt interest, helpers | `app/models/domain.py` |
| New rules + updated refund_or_owed | `rule_packs/federal/2024/federal_2024_rules.yaml` |
| Resolve inputs + set form_line + populate output | `app/engine/calculator.py` |
| Parse adjustments/estimated/other from form + new routes | `main.py` |
| Adjustments, estimated payments, other income sections | `app/templates/pages/calculate.html` |
| IRS form-oriented view | `app/templates/pages/forms_view.html` |
| View Forms button | `app/templates/pages/dashboard.html` |
| 20+ tests | `tests/test_forms.py` |
| Trace test updates | `tests/test_golden.py`, `tests/test_golden2.py` |
