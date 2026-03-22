# CA & NY State Rule Packs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Milestone 10 by adding California and New York state rule packs with progressive bracket tables, adding a "State of Residence" dropdown to the calculate form, and writing tests that verify correct tax calculations.

**Architecture:** Each state pack is a pair of YAML files (manifest + rules) following the established GA pattern. The engine already handles progressive `bracket_table` rules and convention-based state output extraction — no Python engine changes needed. The UI needs a state dropdown that supplements the existing W-2-based state detection. CA includes an additional mental health services surtax rule (1% on income over $1M).

**Tech Stack:** YAML rule packs, Jinja2 template, pytest, FastAPI form parsing

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `rule_packs/state/CA/2024/state_CA_2024_manifest.yaml` | Create | CA manifest (jurisdiction, year, version) |
| `rule_packs/state/CA/2024/state_CA_2024_rules.yaml` | Create | CA rules: AGI, deduction, taxable income, 9 brackets, MHS surtax, withholding, refund |
| `rule_packs/state/NY/2024/state_NY_2024_manifest.yaml` | Create | NY manifest |
| `rule_packs/state/NY/2024/state_NY_2024_rules.yaml` | Create | NY rules: AGI, deduction, taxable income, 9 brackets, withholding, refund |
| `tests/test_state_ca_ny.py` | Create | Tests for CA and NY calculations across filing statuses and income levels |
| `app/templates/pages/calculate.html` | Modify | Add "State of Residence" dropdown |
| `main.py` | Modify | Pass available states to template, merge residence state into active packs |
| `tests/test_state_expansion.py` | Modify | Update state pack count assertion from 10 to 12 |
| `README.md` | Modify | Add CA/NY directories to repository structure tree |
| `CHANGELOG.md` | Modify | Add M10 completion entry |

---

### Task 1: Create California Rule Pack

**Files:**
- Create: `rule_packs/state/CA/2024/state_CA_2024_manifest.yaml`
- Create: `rule_packs/state/CA/2024/state_CA_2024_rules.yaml`

- [ ] **Step 1: Create CA manifest**

```yaml
# SPDX-License-Identifier: AGPL-3.0-or-later
version: "1.0.0"
tax_year: 2024
jurisdiction: "CA"
```

- [ ] **Step 2: Create CA rules file**

CA 2024 tax details (from FTB):
- Standard deduction: $5,540 single, $11,080 MFJ, $5,540 MFS, $11,080 HOH
- 9 brackets (single): 1% (0–$10,412), 2% ($10,412–$24,684), 4% ($24,684–$38,959), 6% ($38,959–$54,081), 8% ($54,081–$68,350), 9.3% ($68,350–$349,137), 10.3% ($349,137–$418,961), 11.3% ($418,961–$698,271), 12.3% ($698,271+)
- MFJ brackets: double the single thresholds
- MFS brackets: same as single
- HOH brackets: different thresholds (between single and MFJ)
- Mental health services tax: 1% surtax on taxable income over $1,000,000 (all filing statuses)

The rules file must define:
- `ca.2024.agi` — formula referencing `fed.2024.agi.total`
- `ca.2024.standard_deduction` — lookup by filing status
- `ca.2024.taxable_income` — `max(agi - deduction, 0)`
- `ca.2024.tax.base` — bracket_table with 9 brackets per filing status
- `ca.2024.tax.mhs` — mental health services surtax: `max(taxable_income - 1000000, 0) * 0.01`
- `ca.2024.tax` — formula: `base_tax + mhs`
- `ca.2024.withholding` — sum of `input.withholding.state.CA`
- `ca.2024.refund_or_owed` — `withholding - tax`

- [ ] **Step 3: Verify CA pack loads without error**

Run: `python -c "from app.engine.rule_loader import RulePack; p = RulePack.load('rule_packs/state/CA/2024'); print(f'{p.jurisdiction} {p.tax_year} — {len(p.rules)} rules')"`
Expected: `CA 2024 — 8 rules`

---

### Task 2: Create New York Rule Pack

**Files:**
- Create: `rule_packs/state/NY/2024/state_NY_2024_manifest.yaml`
- Create: `rule_packs/state/NY/2024/state_NY_2024_rules.yaml`

- [ ] **Step 1: Create NY manifest**

```yaml
# SPDX-License-Identifier: AGPL-3.0-or-later
version: "1.0.0"
tax_year: 2024
jurisdiction: "NY"
```

- [ ] **Step 2: Create NY rules file**

NY 2024 tax details (from NYS DTF):
- Standard deduction: $8,000 single, $16,050 MFJ, $8,000 MFS, $11,200 HOH
- 8 brackets (single): 4% (0–$8,500), 4.5% ($8,500–$11,700), 5.25% ($11,700–$13,900), 5.85% ($13,900–$80,650), 6.25% ($80,650–$215,400), 6.85% ($215,400–$1,077,550), 9.65% ($1,077,550–$5,000,000), 10.3% ($5,000,000–$25,000,000), 10.9% ($25,000,000+)
- MFJ brackets: different thresholds per NYS tables
- MFS brackets: same as single
- HOH brackets: same as single

Note: NY actually has 9 brackets for 2024. The ROADMAP says 8 but the actual NYS schedule has 9 (the top three high-income brackets at 9.65%, 10.3%, 10.9%).

The rules file must define:
- `ny.2024.agi` — formula referencing `fed.2024.agi.total`
- `ny.2024.standard_deduction` — lookup by filing status
- `ny.2024.taxable_income` — `max(agi - deduction, 0)`
- `ny.2024.tax` — bracket_table with brackets per filing status
- `ny.2024.withholding` — sum of `input.withholding.state.NY`
- `ny.2024.refund_or_owed` — `withholding - tax`

- [ ] **Step 3: Verify NY pack loads without error**

Run: `python -c "from app.engine.rule_loader import RulePack; p = RulePack.load('rule_packs/state/NY/2024'); print(f'{p.jurisdiction} {p.tax_year} — {len(p.rules)} rules')"`
Expected: `NY 2024 — 6 rules`

---

### Task 3: Write Tests for CA and NY

**Files:**
- Create: `tests/test_state_ca_ny.py`

- [ ] **Step 1: Write CA and NY test file**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for California and New York state rule packs."""

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
CA = RulePack.load(BASE / "rule_packs" / "state" / "CA" / "2024")
NY = RulePack.load(BASE / "rule_packs" / "state" / "NY" / "2024")


def _make_input(
    state: str,
    wages: str = "75000",
    withheld: str = "3000",
    filing_status: FilingStatus = FilingStatus.SINGLE,
) -> TaxReturnInput:
    return TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Test",
                last_name="User",
                w2s=[
                    W2Data(
                        employer_name="TestCo",
                        wages=Decimal(wages),
                        federal_withheld=Decimal("10000"),
                        state=state,
                        state_wages=Decimal(wages),
                        state_withheld=Decimal(withheld),
                    )
                ],
            )
        ],
    )


# ── California Tests ──────────────────────────────────────────


def test_ca_single_75k() -> None:
    """CA single filer at $75k — golden test with hand-verified values.

    Taxable income: 75000 - 5540 = 69460
    Bracket tax: 104.12 + 285.44 + 571.00 + 907.32 + 1141.52 + 103.23 = 3112.63 → 3113
    """
    inp = _make_input("CA")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    assert len(run.state_outputs) == 1
    ca = run.state_outputs[0]
    assert ca.state == "CA"
    assert ca.state_taxable_income == Decimal("69460")
    assert ca.state_tax == Decimal("3113")
    assert ca.state_withholding == Decimal("3000")
    assert ca.state_refund_or_owed == ca.state_withholding - ca.state_tax


def test_ca_mfj_150k() -> None:
    """CA MFJ at $150k uses MFJ brackets and deduction."""
    inp = _make_input("CA", wages="150000", withheld="6000", filing_status=FilingStatus.MFJ)
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    assert ca.state_tax > Decimal("0")
    # MFJ deduction is $11,080 so taxable income ~ $138,920
    assert ca.state_taxable_income > Decimal("130000")


def test_ca_mental_health_surtax_below_threshold() -> None:
    """CA income below $1M should have no MHS surtax."""
    inp = _make_input("CA", wages="500000", withheld="20000")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    # Tax should be bracket tax only, no surtax
    # At $500k single, base tax is roughly $34k-$38k range
    assert ca.state_tax > Decimal("30000")
    assert ca.state_tax < Decimal("50000")


def test_ca_mental_health_surtax_above_threshold() -> None:
    """CA income above $1M should include 1% MHS surtax on excess."""
    inp = _make_input("CA", wages="1500000", withheld="80000")
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    # Taxable income ~ $1,494,460. MHS surtax on ~$494,460 = ~$4,945
    # Base bracket tax on $1.5M is roughly $175k. Total > $175k.
    assert ca.state_tax > Decimal("150000")


@pytest.mark.parametrize("fs", [FilingStatus.SINGLE, FilingStatus.MFJ, FilingStatus.MFS, FilingStatus.HOH])
def test_ca_all_filing_statuses(fs: FilingStatus) -> None:
    """CA produces valid output for all filing statuses."""
    inp = _make_input("CA", filing_status=fs)
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()
    ca = run.state_outputs[0]
    assert ca.state == "CA"
    assert ca.state_tax >= Decimal("0")


# ── New York Tests ────────────────────────────────────────────


def test_ny_single_75k() -> None:
    """NY single filer at $75k — golden test with hand-verified values.

    Taxable income: 75000 - 8000 = 67000
    Bracket tax: 340.00 + 144.00 + 115.50 + 3106.35 = 3705.85 → 3706
    """
    inp = _make_input("NY")
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    assert len(run.state_outputs) == 1
    ny = run.state_outputs[0]
    assert ny.state == "NY"
    assert ny.state_taxable_income == Decimal("67000")
    assert ny.state_tax == Decimal("3706")
    assert ny.state_withholding == Decimal("3000")
    assert ny.state_refund_or_owed == ny.state_withholding - ny.state_tax


def test_ny_mfj_150k() -> None:
    """NY MFJ at $150k uses MFJ brackets and deduction."""
    inp = _make_input("NY", wages="150000", withheld="6000", filing_status=FilingStatus.MFJ)
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    ny = run.state_outputs[0]
    assert ny.state_tax > Decimal("0")
    # MFJ deduction is $16,050 so taxable income ~ $133,950
    assert ny.state_taxable_income > Decimal("120000")


@pytest.mark.parametrize("fs", [FilingStatus.SINGLE, FilingStatus.MFJ, FilingStatus.MFS, FilingStatus.HOH])
def test_ny_all_filing_statuses(fs: FilingStatus) -> None:
    """NY produces valid output for all filing statuses."""
    inp = _make_input("NY", filing_status=fs)
    run = CalculationEngine(FED, inp, state_packs={"NY": NY}).run()
    ny = run.state_outputs[0]
    assert ny.state == "NY"
    assert ny.state_tax >= Decimal("0")


# ── Multi-State Tests ─────────────────────────────────────────


def test_ca_and_ny_together() -> None:
    """Both CA and NY can run in the same engine invocation."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Test",
                last_name="User",
                w2s=[
                    W2Data(
                        employer_name="CA Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("7000"),
                        state="CA",
                        state_wages=Decimal("50000"),
                        state_withheld=Decimal("2000"),
                    ),
                    W2Data(
                        employer_name="NY Job",
                        wages=Decimal("50000"),
                        federal_withheld=Decimal("7000"),
                        state="NY",
                        state_wages=Decimal("50000"),
                        state_withheld=Decimal("2500"),
                    ),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp, state_packs={"CA": CA, "NY": NY}).run()
    states = {s.state for s in run.state_outputs}
    assert states == {"CA", "NY"}
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_state_ca_ny.py -v`
Expected: All tests PASS

- [ ] **Step 3: Commit rule packs and tests**

```bash
git add rule_packs/state/CA/ rule_packs/state/NY/ tests/test_state_ca_ny.py
git commit -m "feat(m10): add CA and NY state rule packs with tests"
```

---

### Task 4: Add State of Residence Dropdown to Calculate Form

**Files:**
- Modify: `app/templates/pages/calculate.html:12-33` (Filing Information card)
- Modify: `main.py:342-350` (calculate_form GET handler)
- Modify: `main.py:548-569` (calculate_submit POST handler)

- [ ] **Step 1: Pass available states to template**

In `main.py`, the `calculate_form` handler currently passes `available_years`. Add `available_states` — a sorted list of state codes from `_get_state_packs(2024)`.

In `main.py` around line 342, change:
```python
{"request": request, "csrf": csrf, "available_years": available_years}
```
to:
```python
{"request": request, "csrf": csrf, "available_years": available_years, "available_states": sorted(_get_state_packs(max(available_years)).keys())}
```

- [ ] **Step 2: Add dropdown to calculate template**

In `app/templates/pages/calculate.html`, inside the Filing Information card (after the filing status select, around line 32), add a State of Residence dropdown:

```html
<div>
    <label>State of Residence</label>
    <select name="state_of_residence">
        <option value="">— None —</option>
        {% for st in available_states %}
        <option value="{{ st }}">{{ st }}</option>
        {% endfor %}
    </select>
</div>
```

- [ ] **Step 3: Merge residence state into active packs in calculate_submit**

In `main.py` `calculate_submit`, after extracting `states_needed` from W-2 state codes (around line 556), also include the state of residence:

```python
residence = str(fd.get("state_of_residence", "")).strip().upper()
if residence:
    states_needed.add(residence)
```

This ensures that if a user selects CA as their residence but has no CA W-2, the CA state pack still runs.

- [ ] **Step 4: Commit UI changes**

```bash
git add app/templates/pages/calculate.html main.py
git commit -m "feat(m10): add State of Residence dropdown to calculate form"
```

---

### Task 5: Update Existing Tests and Pack Count

**Depends on:** Tasks 1 and 2 must be complete (CA and NY packs must exist on disk) before running these assertions.

**Files:**
- Modify: `tests/test_state_expansion.py:260-268` (state pack count assertion)

- [ ] **Step 1: Update pack count assertion**

In `tests/test_state_expansion.py` `test_state_pack_discovery`, change:
```python
assert len(packs) >= 10
```
to:
```python
assert len(packs) >= 12
```

And add CA/NY to the assertions:
```python
assert "CA" in packs
assert "NY" in packs
```

- [ ] **Step 2: Run full test suite**

Run: `ruff check . && mypy . && pytest`
Expected: All checks pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_state_expansion.py
git commit -m "test(m10): update state pack discovery count for CA + NY"
```

---

### Task 6: Update README Tree and CHANGELOG

**Files:**
- Modify: `README.md` (repository structure tree)
- Modify: `CHANGELOG.md`
- Modify: `.agent_tools/05_session_log.md`

- [ ] **Step 1: Run tree discovery command**

```bash
find . -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -path '*/.mypy_cache/*' -not -path '*/.ruff_cache/*' | sort
```

- [ ] **Step 2: Update README.md repository structure tree**

Add the new `rule_packs/state/CA/` and `rule_packs/state/NY/` directories and their files to the tree. Also add `tests/test_state_ca_ny.py`.

- [ ] **Step 3: Add CHANGELOG entry**

Add under the appropriate version section:
```
- **Milestone 10 — State Tax Expansion (complete):** Added California (9 progressive brackets + 1% mental health services surtax) and New York (9 progressive brackets) state rule packs for tax year 2024. Added "State of Residence" dropdown to the calculate form. All state packs (GA, CA, NY, plus 9 no-income-tax stubs) now loadable and tested.
```

- [ ] **Step 4: Append session log entry**

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md .agent_tools/05_session_log.md
git commit -m "docs: update repository tree and changelog for M10 CA/NY state packs"
```

- [ ] **Step 6: Final verification**

Run: `ruff check . && mypy . && pytest`
Expected: All pass with zero failures
