# State Expansion Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing state engine to production, add no-income-tax state stubs, and establish a repeatable onboarding pattern for new state modules.

**Architecture:** Generalize the hardcoded GA logic in `_run_states()` to convention-based extraction, auto-detect states from W-2 data in the web layer, and render state results on the dashboard.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, PyYAML, Jinja2, pytest

---

## Chunk 1: Engine Generalization and State Pack Wiring

### Task 1: Generalize `_run_states()` in calculator.py

**Files:**
- Modify: `app/engine/calculator.py:135-188`
- Test: `tests/test_state_expansion.py` (new)

- [ ] **Step 1: Write failing tests for generalized state engine**

Create `tests/test_state_expansion.py` with tests that verify:
1. GA works through the generalized engine (same as existing `test_georgia_state_tax_flow` but validates convention-based extraction)
2. A second state (TX) produces $0 tax output
3. Multi-state W-2s (GA + TX) produce both state outputs
4. No state packs = empty state_outputs (backward compat)
5. Withholding is correctly attributed per-state

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""State expansion tests — generalized engine + multi-state support."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

BASE = Path(__file__).resolve().parent.parent
FED = RulePack.load(BASE / "rule_packs" / "federal" / "2024")
GA = RulePack.load(BASE / "rule_packs" / "state" / "GA" / "2024")


def _single_w2_input(
    wages: str = "85000",
    fed_withheld: str = "12000",
    state: str = "GA",
    state_withheld: str = "2000",
    filing_status: FilingStatus = FilingStatus.MFJ,
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="TestCo",
                        wages=Decimal(wages),
                        federal_withheld=Decimal(fed_withheld),
                        state=state,
                        state_withheld=Decimal(state_withheld),
                    )
                ],
            )
        ],
    )


def test_ga_through_generalized_engine() -> None:
    """GA state tax works through convention-based extraction."""
    inp = _single_w2_input()
    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()
    assert len(run.state_outputs) == 1
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    assert ga.state_agi > 0
    assert ga.state_tax > 0
    assert ga.state_withholding == Decimal("2000")


def test_no_state_packs_returns_empty() -> None:
    """Backward compat: no state packs = no state output."""
    inp = _single_w2_input()
    run = CalculationEngine(FED, inp).run()
    assert run.state_outputs == []


def test_state_withholding_attributed_correctly() -> None:
    """State withholding only counts W-2s matching that state."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="GA Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("6000"),
                        state="GA",
                        state_withheld=Decimal("1500"),
                    ),
                    W2Data(
                        employer_name="Other Job",
                        wages=Decimal("30000"),
                        federal_withheld=Decimal("4000"),
                        state="TX",
                        state_withheld=Decimal("0"),
                    ),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()
    ga = run.state_outputs[0]
    assert ga.state_withholding == Decimal("1500")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && pytest tests/test_state_expansion.py -v`
Expected: Some tests fail because _run_states() still has hardcoded GA logic (but GA tests may pass since the hardcoding happens to work for GA).

- [ ] **Step 3: Generalize `_run_states()` in calculator.py**

Replace lines 135-188 with:

```python
def _run_states(self) -> list[StateReturnOutput]:
    outs: list[StateReturnOutput] = []
    if not self.state_packs:
        return outs

    # Resolve withholding for every state in state_packs.
    for state_code in self.state_packs:
        sc = state_code.upper()
        self.resolved[f"input.withholding.state.{sc}"] = sum(
            (
                w.state_withheld
                for tp in self.inputs.taxpayers
                for w in tp.w2s
                if (w.state or "").upper() == sc
            ),
            Decimal("0"),
        )

    for state_code, sp in self.state_packs.items():
        orig_pack = self.rp
        self.rp = sp
        try:
            for rule_id in sp.rule_order:
                self._evaluate_rule(sp.rules[rule_id])

            st = state_code.upper()
            st_lower = state_code.lower()
            yr = sp.tax_year
            outs.append(
                StateReturnOutput(
                    state=st,
                    state_agi=self.resolved.get(
                        f"{st_lower}.{yr}.agi", Decimal("0")
                    ),
                    state_standard_deduction=self.resolved.get(
                        f"{st_lower}.{yr}.standard_deduction", Decimal("0")
                    ),
                    state_personal_exemption=self.resolved.get(
                        f"{st_lower}.{yr}.personal_exemption", Decimal("0")
                    ),
                    state_taxable_income=self.resolved.get(
                        f"{st_lower}.{yr}.taxable_income", Decimal("0")
                    ),
                    state_tax=self.resolved.get(
                        f"{st_lower}.{yr}.tax", Decimal("0")
                    ),
                    state_withholding=self.resolved.get(
                        f"{st_lower}.{yr}.withholding", Decimal("0")
                    ),
                    state_refund_or_owed=self.resolved.get(
                        f"{st_lower}.{yr}.refund_or_owed", Decimal("0")
                    ),
                )
            )
        finally:
            self.rp = orig_pack

    return outs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && pytest tests/test_state_expansion.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run full suite to verify backward compatibility**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && ruff check . && mypy . && pytest`
Expected: All clean, all tests pass

- [ ] **Step 6: Commit**

```bash
git add app/engine/calculator.py tests/test_state_expansion.py
git commit -m "feat: generalize _run_states() for convention-based multi-state support"
```

---

### Task 2: Wire state packs to main.py

**Files:**
- Modify: `main.py:132-133` (add state pack loading), `main.py:459` (pass state packs to engine)
- Test: `tests/test_state_expansion.py` (add route test)

- [ ] **Step 1: Write failing test for state pack auto-detection**

Add to `tests/test_state_expansion.py`:

```python
def test_state_pack_discovery() -> None:
    """_load_state_packs finds GA at minimum."""
    from main import _load_state_packs
    packs = _load_state_packs(2024)
    assert "GA" in packs
    assert packs["GA"].jurisdiction == "GA"
```

- [ ] **Step 2: Add `_load_state_packs()` to main.py and wire into calculate_submit**

After the federal rule_pack loading (line 133), add:

```python
STATE_PACKS_DIR = BASE_DIR / "rule_packs" / "state"

def _load_state_packs(year: int) -> dict[str, RulePack]:
    """Discover and load all state rule packs for the given tax year."""
    packs: dict[str, RulePack] = {}
    if not STATE_PACKS_DIR.exists():
        return packs
    for state_dir in sorted(STATE_PACKS_DIR.iterdir()):
        if not state_dir.is_dir() or state_dir.name.startswith("_"):
            continue
        year_dir = state_dir / str(year)
        if year_dir.exists():
            packs[state_dir.name.upper()] = RulePack.load(year_dir)
    return packs

state_packs = _load_state_packs(2024)
```

In `calculate_submit`, change line 459 from:
```python
run = CalculationEngine(rule_pack, inputs).run()
```
to:
```python
states_needed = {
    w.state.upper()
    for tp in inputs.taxpayers
    for w in tp.w2s
    if w.state
}
active_state_packs = {
    s: state_packs[s] for s in states_needed if s in state_packs
}
run = CalculationEngine(rule_pack, inputs, state_packs=active_state_packs).run()
```

- [ ] **Step 3: Run tests**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_state_expansion.py
git commit -m "feat: wire state pack discovery and auto-detection to calculate route"
```

---

### Task 3: Display state results on dashboard

**Files:**
- Modify: `app/templates/pages/dashboard.html`
- Test: `tests/test_state_expansion.py` (add template rendering test)

- [ ] **Step 1: Add state output section to dashboard.html**

After the federal summary grid (after line 37, before the audit trace card), add:

```html
{% if run.state_outputs %}
{% for st in run.state_outputs %}
<h2 style="font-size: 20px; margin-top: 24px; margin-bottom: 8px;">{{ st.state }} State Return</h2>
<div class="summary-grid">
    {% for label, val in [
        ("State AGI", st.state_agi),
        ("Standard Deduction", st.state_standard_deduction),
        ("Taxable Income", st.state_taxable_income),
        ("State Tax", st.state_tax),
        ("State Withholding", st.state_withholding),
    ] %}
    <div class="summary-item">
        <div class="label">{{ label }}</div>
        <div class="value">${{ "{:,.0f}".format(val) }}</div>
    </div>
    {% endfor %}
    <div class="summary-item">
        <div class="label">{% if st.state_refund_or_owed >= 0 %}Refund{% else %}Owed{% endif %}</div>
        <div class="value {% if st.state_refund_or_owed >= 0 %}positive{% else %}negative{% endif %}">
            {% if st.state_refund_or_owed >= 0 %}
                ${{ "{:,.0f}".format(st.state_refund_or_owed) }}
            {% else %}
                -${{ "{:,.0f}".format(st.state_refund_or_owed|abs) }}
            {% endif %}
        </div>
    </div>
</div>
{% endfor %}
{% endif %}
```

- [ ] **Step 2: Run full suite**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && ruff check . && mypy . && pytest`

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/dashboard.html
git commit -m "feat: display state tax results on dashboard"
```

---

## Chunk 2: No-Income-Tax State Stubs

### Task 4: Create no-income-tax state stubs

**Files:**
- Create: 9 state directories under `rule_packs/state/` (TX, FL, WA, NV, WY, SD, AK, NH, TN), each with manifest + rules YAML
- Test: `tests/test_state_expansion.py` (add stub tests)

- [ ] **Step 1: Write failing tests for no-income-tax stubs**

Add to `tests/test_state_expansion.py`:

```python
@pytest.mark.parametrize("state_code", ["TX", "FL", "WA", "NV", "WY", "SD", "AK", "NH", "TN"])
def test_no_income_tax_stub_loads(state_code: str) -> None:
    """Each no-income-tax stub loads without error."""
    pack_dir = BASE / "rule_packs" / "state" / state_code / "2024"
    sp = RulePack.load(pack_dir)
    assert sp.jurisdiction == state_code
    assert sp.tax_year == 2024


@pytest.mark.parametrize("state_code", ["TX", "FL", "WA", "NV", "WY", "SD", "AK", "NH", "TN"])
def test_no_income_tax_stub_returns_zero_tax(state_code: str) -> None:
    """No-income-tax stubs produce $0 state tax."""
    pack_dir = BASE / "rule_packs" / "state" / state_code / "2024"
    sp = RulePack.load(pack_dir)
    inp = _single_w2_input(state=state_code)
    run = CalculationEngine(FED, inp, state_packs={state_code: sp}).run()
    assert len(run.state_outputs) == 1
    st_out = run.state_outputs[0]
    assert st_out.state == state_code
    assert st_out.state_tax == Decimal("0")
```

- [ ] **Step 2: Create all 9 no-income-tax state stubs**

Each state gets two files:
- `rule_packs/state/{ST}/2024/state_{ST}_2024_manifest.yaml`
- `rule_packs/state/{ST}/2024/state_{ST}_2024_rules.yaml`

Manifest template:
```yaml
version: "1.0.0"
tax_year: 2024
jurisdiction: "{ST}"
```

Rules template (e.g., TX):
```yaml
constants: {}

rules:
  - id: "{st}.2024.agi"
    description: "{State Name} — no state income tax"
    type: "formula"
    expression: "zero"
    inputs:
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "{st}.2024.tax"
    description: "{State Name} state income tax (none)"
    type: "formula"
    expression: "zero"
    inputs:
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "{st}.2024.withholding"
    description: "{State Name} withholding"
    type: "sum"
    inputs:
      items: { ref: "input.withholding.state.{ST}" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "{st}.2024.refund_or_owed"
    description: "{State Name} refund/owed"
    type: "formula"
    expression: "withholding - tax"
    inputs:
      withholding: { ref: "{st}.2024.withholding" }
      tax: { ref: "{st}.2024.tax" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

- [ ] **Step 3: Run tests**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && pytest tests/test_state_expansion.py -v`
Expected: All stub tests pass

- [ ] **Step 4: Run full suite**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && ruff check . && mypy . && pytest`

- [ ] **Step 5: Commit**

```bash
git add rule_packs/state/ tests/test_state_expansion.py
git commit -m "feat: add no-income-tax state stubs (TX, FL, WA, NV, WY, SD, AK, NH, TN)"
```

---

## Chunk 3: Multi-State and Edge Cases

### Task 5: Multi-state W-2 tests and edge cases

**Files:**
- Test: `tests/test_state_expansion.py`

- [ ] **Step 1: Add multi-state and edge-case tests**

```python
def test_multi_state_w2s_produce_both_outputs() -> None:
    """W-2s from GA and TX produce outputs for both states."""
    TX = RulePack.load(BASE / "rule_packs" / "state" / "TX" / "2024")
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="GA Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("6000"),
                        state="GA",
                        state_withheld=Decimal("1500"),
                    ),
                    W2Data(
                        employer_name="TX Job",
                        wages=Decimal("30000"),
                        federal_withheld=Decimal("4000"),
                        state="TX",
                        state_withheld=Decimal("0"),
                    ),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp, state_packs={"GA": GA, "TX": TX}).run()
    assert len(run.state_outputs) == 2
    states = {s.state for s in run.state_outputs}
    assert states == {"GA", "TX"}

    ga = next(s for s in run.state_outputs if s.state == "GA")
    tx = next(s for s in run.state_outputs if s.state == "TX")
    assert ga.state_tax > 0
    assert ga.state_withholding == Decimal("1500")
    assert tx.state_tax == Decimal("0")
    assert tx.state_withholding == Decimal("0")


def test_state_not_in_available_packs_is_ignored() -> None:
    """W-2 state code not matching any loaded pack is silently ignored."""
    inp = _single_w2_input(state="CA")
    run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()
    assert run.state_outputs == []


def test_ga_all_filing_statuses() -> None:
    """GA produces valid output for all filing statuses with standard deductions."""
    for fs in [FilingStatus.SINGLE, FilingStatus.MFJ, FilingStatus.MFS, FilingStatus.HOH]:
        inp = _single_w2_input(filing_status=fs)
        run = CalculationEngine(FED, inp, state_packs={"GA": GA}).run()
        ga = run.state_outputs[0]
        assert ga.state_tax >= 0, f"Failed for {fs}"
```

- [ ] **Step 2: Run tests**

Run: `cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion && pytest tests/test_state_expansion.py -v`

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_expansion.py
git commit -m "test: add multi-state and edge-case vectors for state expansion"
```

---

## Chunk 4: State Template and Authoring Guide

### Task 6: Create state onboarding template

**Files:**
- Create: `rule_packs/state/_template/2024/state_TEMPLATE_2024_manifest.yaml`
- Create: `rule_packs/state/_template/2024/state_TEMPLATE_2024_rules.yaml`

- [ ] **Step 1: Create template manifest**

```yaml
# Replace TEMPLATE with 2-letter state code (e.g., CA)
# Replace State Name with full state name (e.g., California)
version: "0.1.0"
tax_year: 2024
jurisdiction: "TEMPLATE"
```

- [ ] **Step 2: Create template rules**

Skeleton rules YAML showing all common patterns (formula, lookup, sum, bracket_table) with comments explaining each.

- [ ] **Step 3: Commit**

```bash
git add rule_packs/state/_template/
git commit -m "feat: add state rule pack onboarding template"
```

### Task 7: Write STATE_AUTHORING_GUIDE.md

**Files:**
- Create: `docs/STATE_AUTHORING_GUIDE.md`

- [ ] **Step 1: Write the guide**

Cover: directory conventions, manifest, required rule IDs, cross-pack refs, rule types, no-income-tax pattern, testing.

- [ ] **Step 2: Commit**

```bash
git add docs/STATE_AUTHORING_GUIDE.md
git commit -m "docs: add state authoring guide for contributors"
```

---

## Chunk 5: Final Verification

### Task 8: Full verification and cleanup

- [ ] **Step 1: Run complete validation**

```bash
cd /home/dill/Code_Projects/Tax_Co-Pilot/.worktrees/state-expansion
ruff check . && mypy . && pytest
```

- [ ] **Step 2: Verify state pack discovery includes all new states**

```python
# Quick manual verification
from main import _load_state_packs
packs = _load_state_packs(2024)
assert len(packs) >= 10  # GA + 9 no-income-tax stubs
```
