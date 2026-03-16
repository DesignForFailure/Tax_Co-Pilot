# Federal Completeness — Design Spec

**Date:** 2026-03-15
**Milestone:** Roadmap §1 — Federal Completeness (MVP Hardening)
**Status:** Draft

## Goal

Expand the federal engine from simplified 1040-style coverage toward broader real-world household scenarios. Make AGI actually adjusted, add common income categories, harden edge cases, and improve trace explainability.

## Scope

| In scope | Out of scope (future milestones) |
|----------|----------------------------------|
| Self-employment income (1099-NEC) | Preferential QD/LTCG rates (0/15/20%) |
| Social Security benefits (partial taxability) | Itemized deductions |
| Other income (Line 8 catch-all) | Tax credits (CTC, EIC) |
| Above-the-line adjustments (student loan, IRA, HSA, educator, SE tax deduction) | UI form changes |
| Capital loss limitation (-$3,000) | Multi-year support |
| Bracket boundary edge-case tests | State expansion |
| Richer trace explanations with form line references | |

## Design

### 1. New Income Categories

#### 1.1 Domain Models (`app/models/domain.py`)

New models:

```python
class Form1099NECData(BaseModel):
    payer_name: str = ""
    nonemployee_compensation: Decimal = Decimal("0")  # Box 1
    federal_withheld: Decimal = Decimal("0")  # Box 4

class Form1099SSAData(BaseModel):
    payer_name: str = ""
    total_benefits: Decimal = Decimal("0")  # Box 5
    federal_withheld: Decimal = Decimal("0")  # Box 6
```

Changes to existing models:

- `Taxpayer`: add `form_1099_necs: list[Form1099NECData]` and `form_1099_ssas: list[Form1099SSAData]`
- `TaxReturnInput`: add `other_income: Decimal = Decimal("0")`, add `total_self_employment_income()` and `total_social_security_benefits()` helpers, update `total_federal_withholding()` to include NEC and SSA withholding

#### 1.2 Rule Pack (`federal_2024_rules.yaml`)

New constants:

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

New rules:

- `fed.2024.gross_income.self_employment` (sum): Sum of 1099-NEC compensation
- `fed.2024.gross_income.other` (formula): Pass-through of `input.other_income`
- `fed.2024.gross_income.ss_provisional` (formula): Non-SS gross income + 50% of SS benefits
- `fed.2024.gross_income.ss_taxable` (formula): Multi-step SS taxability calculation
- `fed.2024.gross_income.capital_gains_limited` (formula): `max(net_gains, -3000)` — capital loss limitation
- Update `fed.2024.gross_income.total`: include self_employment, ss_taxable, other; reference capital_gains_limited instead of raw capital_gains

#### 1.3 SS Benefits Taxability Logic

Implemented as a chain of rules rather than one expression:

1. `fed.2024.gross_income.ss_provisional`: sum of all non-SS income + 50% of total SS benefits
2. `fed.2024.gross_income.ss_taxable`: `min(total_benefits * 0.85, max(min((provisional - base_threshold) * 0.50, (upper_threshold - base_threshold) * 0.50), 0) + max((provisional - upper_threshold) * 0.85, 0))`

The thresholds vary by filing status (lookup from constants).

### 2. Above-the-Line Adjustments

#### 2.1 Domain Models

New model:

```python
class AdjustmentsData(BaseModel):
    student_loan_interest: Decimal = Decimal("0")
    ira_contributions: Decimal = Decimal("0")
    hsa_contributions: Decimal = Decimal("0")
    educator_expenses: Decimal = Decimal("0")
    self_employment_tax_deduction: Decimal = Decimal("0")
```

Changes:

- `TaxReturnInput`: add `adjustments: AdjustmentsData` with default factory, add `total_adjustments()` method

#### 2.2 Rule Pack

New constants:

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

New rules:

- `fed.2024.adjustments.student_loan` (formula): `min(input, 2500)`
- `fed.2024.adjustments.educator` (formula): `min(input, 300)`
- `fed.2024.adjustments.hsa` (formula): `min(input, limit)` with limit from lookup
- `fed.2024.adjustments.ira` (formula): `min(input, 7000)`
- `fed.2024.adjustments.se_tax` (formula): pass-through (user provides deductible half directly)
- `fed.2024.adjustments.total` (sum): sum of all adjustment rules
- Update `fed.2024.agi.total`: expression changes from `"gross"` to `"max(gross - adj, 0)"`

#### 2.3 Engine Changes

`_resolve_inputs()` adds:

- `input.1099nec.compensation`
- `input.ssa.total_benefits`
- `input.other_income`
- `input.adjustments.student_loan_interest`
- `input.adjustments.ira_contributions`
- `input.adjustments.hsa_contributions`
- `input.adjustments.educator_expenses`
- `input.adjustments.self_employment_tax_deduction`

### 3. Edge-Case Hardening

#### 3.1 Capital Loss Limitation

New rule `fed.2024.gross_income.capital_gains_limited`: `max(net_gains, -3000)`. The `gross_income.total` rule references this instead of the raw `capital_gains` rule.

The raw `capital_gains` rule is retained for audit transparency (trace shows both unlimited and limited values).

#### 3.2 Test Vectors

Bracket boundary tests at exact thresholds for all 5 filing statuses. Zero income across all statuses. Income below standard deduction. Negative AGI from large adjustments. Capital loss at exactly -$3,000 and beyond.

### 4. Explainability Improvements

#### 4.1 Form Line References in YAML

Add optional `form_line` field to each rule definition:

```yaml
- id: "fed.2024.gross_income.wages"
  description: "Total W-2 wages (Box 1)"
  form_line: "1040 Line 1a"
  type: "sum"
  ...
```

The engine reads `form_line` and prepends it to the explanation string.

#### 4.2 Explanation Templates by Rule Type

- **Sum**: `"{form_line}: {count} item(s) totaling {result}"` — e.g., `"1040 Line 1a: 2 W-2(s) totaling $85,000.00"`
- **Formula**: `"{form_line}: {expanded_expression} = {result}"` — e.g., `"1040 Line 11: $85,000.00 gross income − $2,500.00 adjustments = $82,500.00"`
- **Lookup**: `"{form_line}: {key} → {result}"` — e.g., `"1040 Line 13: MFJ → $29,200"`
- **Bracket table**: `"{form_line}: Tax on {income} ({status}): {bracket_details} = {result}"` (existing format with line ref prefix)

#### 4.3 ReturnOutput Field Updates

Add `adjustments_total: Decimal` to `ReturnOutput` so the dashboard can display it. Update `calculator.py` `run()` to populate it.

### 5. Backward Compatibility

All existing golden tests must pass unchanged:

- When `adjustments` is not provided, `AdjustmentsData` defaults to all zeros → `fed.2024.adjustments.total` = 0 → AGI = gross income (same as before)
- When no 1099-NEC/SSA/other_income is provided, those resolve to 0 → gross income unchanged
- When capital gains >= 0, the loss limitation rule is a no-op
- `test_trace_contains_all_rules` will need updating to include new rule IDs

### 6. Files Changed

| File | Change type |
|------|------------|
| `app/models/domain.py` | Add Form1099NECData, Form1099SSAData, AdjustmentsData; extend Taxpayer, TaxReturnInput, ReturnOutput |
| `rule_packs/federal/2024/federal_2024_rules.yaml` | Add constants, ~12 new rules, update 2 existing rules, add form_line fields |
| `app/engine/calculator.py` | Extend _resolve_inputs(), update explanation generation, populate new output fields |
| `app/engine/rule_loader.py` | Pass through form_line field (no validation change needed — it's metadata) |
| `tests/test_golden_m1.py` | New file: ~15-20 test vectors |
| `tests/test_golden.py` | Update `test_trace_contains_all_rules` expected set |
| `tests/test_golden2.py` | Update `test_trace_completeness` expected set |

### 7. Known Simplifications

- All income taxed at ordinary rates (no preferential QD/LTCG 0/15/20% rates)
- SS taxability uses simplified provisional income (no tax-exempt interest component)
- No income-based phaseouts on IRA/HSA deductions
- SE tax deduction is input-provided, not computed from SE income
- No AMT consideration
