# State Expansion — Design Spec

**Date:** 2026-03-16
**Milestone:** Roadmap §2 — State Expansion
**Status:** Draft

## Goal

Move from a single state stub (GA) to multi-state practical support. Wire the existing state engine infrastructure to the production web layer, add state packs for additional states, define a repeatable onboarding pattern, and add state-specific regression suites.

## Scope

| In scope | Out of scope (future milestones) |
|----------|----------------------------------|
| Wire state packs to main.py calculate route | Progressive bracket states (CA, NY — Milestone 10) |
| Auto-detect states from W-2 data | State-specific credits/deductions beyond std deduction |
| Display state results on dashboard | Multi-state residency (part-year, domicile rules) |
| Generalize `_run_states()` to remove GA hardcoding | State UI form changes (state selector dropdown) |
| Add no-income-tax state stubs (TX, FL, WA, NV, WY, SD, AK, NH, TN) | Year-over-year state comparison |
| State template directory + authoring guide | |
| Comprehensive state test suite | |

## Design

### 1. Generalize State Engine (`calculator.py`)

#### 1.1 Dynamic Withholding Resolution

Replace the hardcoded GA withholding block in `_run_states()` with a loop that resolves `input.withholding.state.{STATE}` for every state in `state_packs`:

```python
for state_code in self.state_packs:
    sc = state_code.upper()
    self.resolved[f"input.withholding.state.{sc}"] = sum(
        (w.state_withheld for tp in self.inputs.taxpayers
         for w in tp.w2s if (w.state or "").upper() == sc),
        Decimal("0"),
    )
```

#### 1.2 Dynamic Output Extraction

Replace the `if st == "GA":` block with convention-based key extraction. State packs MUST use the naming pattern `{st_lower}.{year}.{field}` for output keys:

```python
yr = sp.manifest.get("tax_year", 2024)
st_lower = state_code.lower()
outs.append(StateReturnOutput(
    state=st,
    state_agi=self.resolved.get(f"{st_lower}.{yr}.agi", Decimal("0")),
    state_standard_deduction=self.resolved.get(f"{st_lower}.{yr}.standard_deduction", Decimal("0")),
    state_personal_exemption=self.resolved.get(f"{st_lower}.{yr}.personal_exemption", Decimal("0")),
    state_taxable_income=self.resolved.get(f"{st_lower}.{yr}.taxable_income", Decimal("0")),
    state_tax=self.resolved.get(f"{st_lower}.{yr}.tax", Decimal("0")),
    state_withholding=self.resolved.get(f"{st_lower}.{yr}.withholding", Decimal("0")),
    state_refund_or_owed=self.resolved.get(f"{st_lower}.{yr}.refund_or_owed", Decimal("0")),
))
```

The `manifest` dict needs the `tax_year` field exposed. Currently `RulePack` stores it — we'll access it via `sp.manifest["tax_year"]`.

#### 1.3 RulePack Manifest Access

`RulePack` already loads the manifest YAML. We need to verify the `tax_year` field is accessible. If the manifest dict is stored as `sp.manifest`, we use it directly.

### 2. Wire State Packs to Production (`main.py`)

#### 2.1 State Pack Discovery and Loading

At startup, scan `rule_packs/state/` for state directories containing a `{year}/` subdirectory. Load and cache each state pack:

```python
STATE_PACKS_DIR = BASE_DIR / "rule_packs" / "state"

def _load_state_packs(year: int) -> dict[str, RulePack]:
    packs: dict[str, RulePack] = {}
    if not STATE_PACKS_DIR.exists():
        return packs
    for state_dir in sorted(STATE_PACKS_DIR.iterdir()):
        if not state_dir.is_dir():
            continue
        year_dir = state_dir / str(year)
        if year_dir.exists():
            packs[state_dir.name.upper()] = RulePack.load(year_dir)
    return packs

state_packs = _load_state_packs(2024)
```

#### 2.2 Auto-Detect States from W-2s

In `calculate_submit`, extract unique state codes from the parsed `TaxReturnInput`'s W-2 data and pass the corresponding state packs:

```python
states_needed = {
    w.state.upper()
    for tp in inputs.taxpayers for w in tp.w2s
    if w.state
}
active_state_packs = {s: state_packs[s] for s in states_needed if s in state_packs}
run = CalculationEngine(rule_pack, inputs, state_packs=active_state_packs).run()
```

### 3. Dashboard State Output

#### 3.1 Template Update (`dashboard.html`)

After the federal summary grid, add a state results section that renders each `StateReturnOutput` in `run.state_outputs`:

```html
{% for st in run.state_outputs %}
<h2>{{ st.state }} State Return</h2>
<div class="summary-grid">
    {% for label, val in [
        ("State AGI", st.state_agi),
        ("Standard Deduction", st.state_standard_deduction),
        ("Taxable Income", st.state_taxable_income),
        ("State Tax", st.state_tax),
        ("State Withholding", st.state_withholding),
    ] %}
    ...
    {% endfor %}
    <div class="summary-item">refund/owed logic for st.state_refund_or_owed</div>
</div>
{% endfor %}
```

### 4. No-Income-Tax State Stubs

Create minimal rule packs for: TX, FL, WA, NV, WY, SD, AK, NH, TN.

Each stub has:
- A manifest (jurisdiction, tax_year, version)
- A single-rule YAML with one `formula` rule that outputs `$0` tax
- Conventional rule IDs so the generic extractor works: `{st}.2024.agi`, `{st}.2024.tax`, `{st}.2024.refund_or_owed`

Example for TX:

```yaml
constants: {}

rules:
  - id: "tx.2024.agi"
    description: "Texas has no state income tax"
    type: "formula"
    expression: "zero"
    inputs:
      zero: { literal: "0" }

  - id: "tx.2024.tax"
    description: "Texas state income tax (none)"
    type: "formula"
    expression: "zero"
    inputs:
      zero: { literal: "0" }

  - id: "tx.2024.refund_or_owed"
    description: "Texas refund/owed (no income tax)"
    type: "formula"
    expression: "withholding"
    inputs:
      withholding: { ref: "input.withholding.state.TX" }
```

### 5. State Template and Authoring Guide

#### 5.1 Template Directory

Create `rule_packs/state/_template/2024/` with:
- `state_TEMPLATE_2024_manifest.yaml` — placeholder manifest
- `state_TEMPLATE_2024_rules.yaml` — skeleton with AGI, standard deduction, taxable income, tax, withholding, refund_or_owed rules

#### 5.2 Authoring Guide (`docs/STATE_AUTHORING_GUIDE.md`)

Document:
- Directory conventions (`rule_packs/state/{STATE_CODE}/{YEAR}/`)
- Manifest requirements (jurisdiction, tax_year, version)
- Required rule ID conventions (`{st}.{year}.agi`, `.tax`, `.refund_or_owed`)
- Cross-pack federal AGI reference pattern
- How to use lookup, formula, bracket_table, and sum rule types
- How to handle no-income-tax states
- Testing patterns

### 6. Test Suite

#### 6.1 New Test File: `tests/test_state_expansion.py`

Test vectors:
- GA state tax calculation (MFJ, single) — verify existing behavior through generalized engine
- TX no-income-tax stub returns $0 tax
- FL no-income-tax stub returns $0 tax
- Multi-state W-2s (GA + TX) — both states produce output
- State withholding extraction for arbitrary states
- No state packs produces empty state_outputs (backward compatibility)
- State pack discovery loads correct packs
- State output on dashboard template renders correctly

### 7. Backward Compatibility

- All existing golden tests pass unchanged (no state packs passed = no state output)
- The existing `test_georgia_state_tax_flow` test in `test_golden2.py` continues to work
- GA rule pack YAML is not modified

### 8. Files Changed

| File | Change type |
|------|------------|
| `app/engine/calculator.py` | Generalize `_run_states()`: dynamic withholding, convention-based output extraction |
| `main.py` | Add `_load_state_packs()`, auto-detect states, pass to engine |
| `app/templates/pages/dashboard.html` | Add state output section |
| `rule_packs/state/TX/2024/` | New: no-income-tax stub |
| `rule_packs/state/FL/2024/` | New: no-income-tax stub |
| `rule_packs/state/WA/2024/` | New: no-income-tax stub |
| `rule_packs/state/NV/2024/` | New: no-income-tax stub |
| `rule_packs/state/WY/2024/` | New: no-income-tax stub |
| `rule_packs/state/SD/2024/` | New: no-income-tax stub |
| `rule_packs/state/AK/2024/` | New: no-income-tax stub |
| `rule_packs/state/NH/2024/` | New: no-income-tax stub |
| `rule_packs/state/TN/2024/` | New: no-income-tax stub |
| `rule_packs/state/_template/2024/` | New: onboarding template |
| `docs/STATE_AUTHORING_GUIDE.md` | New: authoring guide |
| `tests/test_state_expansion.py` | New: ~15-20 state test vectors |

### 9. Known Simplifications

- No state-specific credits or itemized deductions
- No progressive bracket states (CA, NY deferred to Milestone 10)
- No part-year residency or domicile modeling
- No state selector in UI — states are auto-detected from W-2 state fields
- NH taxes only interest/dividends (not wages) — stub approximation returns $0
- TN has no income tax as of 2021 — stub is accurate
