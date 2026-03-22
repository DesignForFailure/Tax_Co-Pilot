<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# Rule Pack Authoring Guide

A practical reference for writing new Tax Co-Pilot rule packs from scratch.

---

## 1. Overview

Tax Co-Pilot separates tax law from application code. Each jurisdiction's rules live in a **YAML rule pack** — a pair of files (manifest + rules) that the generic `CalculationEngine` evaluates without any Python changes.

When a calculation runs, the engine:

1. Loads one or more rule packs (federal first, then each requested state).
2. Builds a dependency graph from explicit `{ ref: "..." }` links between rules.
3. Topologically sorts the rules so every dependency is satisfied before a rule runs.
4. Evaluates each rule using `Decimal` arithmetic (no floating-point rounding errors).
5. Records every rule's inputs, output, and rounding in an **audit trace** — a `TraceNode` per rule.

The SHA-256 checksum of the pack's YAML files is stored in every `ReturnRun`, so you can prove exactly which rules produced a result.

---

## 2. Directory Structure

```
rule_packs/
  federal/
    2024/
      manifest.yaml            # (or federal_2024_manifest.yaml — legacy naming supported)
      rules.yaml               # (or federal_2024_rules.yaml)
  state/
    GA/
      2024/
        state_GA_2024_manifest.yaml
        state_GA_2024_rules.yaml
    CA/
      2024/
        state_CA_2024_manifest.yaml
        state_CA_2024_rules.yaml
```

Each pack lives in `rule_packs/{jurisdiction}/{year}/` and contains exactly two YAML files:

- **manifest** — version, tax year, and jurisdiction identifier
- **rules** — constants block and the list of rules

The loader accepts either the canonical names (`manifest.yaml` / `rules.yaml`) or the legacy `*_manifest.yaml` / `*_rules.yaml` pattern. If more than one `*_manifest.yaml` or `*_rules.yaml` file exists in the directory, the loader will error to avoid ambiguity.

---

## 3. Manifest Format

The manifest is intentionally minimal — three required fields:

```yaml
version: "1.0.0"
tax_year: 2024
jurisdiction: "GA"
```

| Field          | Type   | Description                                               |
|----------------|--------|-----------------------------------------------------------|
| `version`      | string | Semantic version of this rule pack                        |
| `tax_year`     | int    | The tax year these rules apply to (must be > 0)           |
| `jurisdiction` | string | Jurisdiction identifier: `"federal"` or a two-letter state code |

The `jurisdiction` value controls the required **prefix** for all rule IDs in the pack. The mapping is:

| `jurisdiction` value                   | Required rule ID prefix |
|----------------------------------------|-------------------------|
| `"federal"`, `"fed"`, `"us"`, `"usa"` | `fed.`                  |
| Two-letter code (e.g. `"GA"`)          | `ga.` (lowercased)      |

The loader enforces this at load time — a rule whose ID does not start with the correct prefix will fail validation.

---

## 4. The Four Rule Types

### 4.1 `formula` — Arithmetic over named inputs

Evaluates an expression string over a set of named variables. Each variable is bound to either another rule's output (`ref`) or a hard-coded decimal string (`literal`).

```yaml
- id: "ga.2024.taxable_income"
  description: "Georgia taxable income"
  type: "formula"
  expression: "max(agi - deduction - exemption, 0)"
  inputs:
    agi:       { ref: "ga.2024.agi" }
    deduction: { ref: "ga.2024.standard_deduction" }
    exemption: { ref: "ga.2024.personal_exemption" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 0
```

Every identifier in `expression` must appear as a key under `inputs`. Undeclared identifiers cause a load-time error.

### 4.2 `lookup` — Constant table keyed by filing status

Resolves a value from the `constants` block using a dynamic key (almost always `input.filing_status`).

```yaml
constants:
  standard_deduction:
    single: "14600"
    mfj:    "29200"
    mfs:    "14600"
    hoh:    "21900"
    qss:    "29200"

rules:
  - id: "fed.2024.standard_deduction"
    description: "Standard deduction for 2024"
    type: "lookup"
    table: "constants.standard_deduction"
    key: { ref: "input.filing_status" }
```

The `table` field is a dotted path into the `constants` block (see Section 6). The `key` field resolves at runtime to a string used to index the table.

`lookup` rules do not need `rounding` or `inputs` fields — they return the raw constant value.

### 4.3 `sum` — Add a list of values

Adds all items in a list reference. The typical use is summing a collection of income items or withholding entries across multiple W-2s.

```yaml
- id: "fed.2024.gross_income.total"
  description: "Total income (all sources)"
  type: "sum"
  inputs:
    items:
      - { ref: "fed.2024.gross_income.wages" }
      - { ref: "fed.2024.gross_income.interest" }
      - { ref: "fed.2024.gross_income.dividends" }
      - { ref: "fed.2024.gross_income.capital_gains_limited" }
      - { ref: "fed.2024.gross_income.self_employment" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 2
```

`items` can also be a single ref (not a list) when the input itself is already a collection (e.g., all W-2 wages):

```yaml
- id: "ga.2024.withholding"
  description: "Total Georgia tax withheld"
  type: "sum"
  inputs:
    items: { ref: "input.withholding.state.GA" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 2
```

### 4.4 `bracket_table` — Progressive tax brackets

Computes tax by applying graduated bracket rates to successive slices of income. The `input` field is the taxable income amount, and `key` selects the correct bracket schedule by filing status.

```yaml
- id: "ca.2024.tax.base"
  description: "California income tax using 2024 bracket tables"
  type: "bracket_table"
  input: { ref: "ca.2024.taxable_income" }
  key: { ref: "input.filing_status" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 2
  tables:
    single:
      - { lower: "0",      upper: "10412",  rate: "0.01" }
      - { lower: "10412",  upper: "24684",  rate: "0.02" }
      - { lower: "24684",  upper: "38959",  rate: "0.04" }
      - { lower: "38959",  upper: null,     rate: "0.06" }
    mfj:
      - { lower: "0",      upper: "20824",  rate: "0.01" }
      - { lower: "20824",  upper: "49368",  rate: "0.02" }
      - { lower: "49368",  upper: "77918",  rate: "0.04" }
      - { lower: "77918",  upper: null,     rate: "0.06" }
```

Bracket rules:
- `lower` and `upper` are decimal strings. `upper: null` marks the top bracket (unbounded).
- Each filing status must be a non-empty list.
- Required fields per bracket entry: `lower`, `rate`. (`upper` is optional only for the final bracket.)
- The `tables` mapping must include every filing status your users may file under.

---

## 5. Expression Mini-Language

Formula expressions are validated against a strict allowlist before the pack loads. The engine does **not** use `eval` — expressions are parsed and executed by the `CalculationEngine` using `Decimal` arithmetic.

### Allowed characters

```
a-z  A-Z  0-9  _  +  -  *  /  (  )  ,  .  (space)
```

Any character outside this set causes a load-time `RulePackError`.

### Operators

| Operator | Meaning          |
|----------|------------------|
| `+`      | Addition         |
| `-`      | Subtraction      |
| `*`      | Multiplication   |
| `/`      | Division         |

Standard operator precedence applies. Use parentheses to control evaluation order.

### Functions

| Function    | Meaning                                      |
|-------------|----------------------------------------------|
| `max(a, b)` | Returns the larger of two values             |
| `min(a, b)` | Returns the smaller of two values            |

Only `max` and `min` are in the allowlist. No other function names are permitted.

### Variable references

Every non-function identifier in an expression must be declared in the `inputs` block:

```yaml
expression: "max(agi - deduction, 0)"
inputs:
  agi:       { ref: "ga.2024.agi" }
  deduction: { ref: "ga.2024.standard_deduction" }
```

The literal `0` above is a numeric literal embedded directly in the expression, not a named input. Named literals are declared with `{ literal: "..." }`:

```yaml
expression: "taxable_income * rate"
inputs:
  taxable_income: { ref: "ga.2024.taxable_income" }
  rate: { literal: "0.0539" }
```

Literal values must be valid decimal strings (e.g., `"0.0539"`, `"-3000"`, `"0"`).

---

## 6. The Constants System

The `constants:` block at the top of `rules.yaml` stores named tables of values that do not depend on runtime inputs. Constants are typically used for filing-status-keyed amounts.

```yaml
constants:
  standard_deduction:
    single: "5400"
    mfj:    "7100"
    mfs:    "3550"
    hoh:    "5400"
  personal_exemption:
    single: "2700"
    mfj:    "7400"
    mfs:    "2700"
    hoh:    "2700"
```

Reference a constant in a `lookup` rule using a dotted path starting with `"constants."`:

```yaml
- id: "ga.2024.standard_deduction"
  type: "lookup"
  table: "constants.standard_deduction"
  key: { ref: "input.filing_status" }
```

For nested constants (e.g., `constants.ss_taxability.base_threshold`), the full dotted path resolves level by level:

```yaml
constants:
  ss_taxability:
    base_threshold:
      single: "25000"
      mfj:    "32000"

rules:
  - id: "fed.2024.gross_income.ss_base_threshold"
    type: "lookup"
    table: "constants.ss_taxability.base_threshold"
    key: { ref: "input.filing_status" }
```

Constants are pack-local. You cannot reference another pack's constants directly; cross-pack data flows through rule references instead.

---

## 7. Namespace Conventions

Rule IDs follow the pattern `{prefix}.{year}.{category}.{name}`:

| Jurisdiction | Prefix | Example ID                         |
|--------------|--------|------------------------------------|
| Federal      | `fed`  | `fed.2024.agi.total`               |
| State (GA)   | `ga`   | `ga.2024.taxable_income`           |
| State (CA)   | `ca`   | `ca.2024.tax.base`                 |
| State (NY)   | `ny`   | `ny.2024.tax`                      |

The prefix is derived from the manifest `jurisdiction` field at load time. The loader enforces that every rule ID starts with the correct prefix for the pack — this prevents one pack from accidentally overwriting another's values in the `resolved[...]` namespace at runtime.

Use lowercase for the entire ID. Categories like `gross_income`, `adjustments`, `agi`, `deductions`, `tax`, `credits`, `withholding`, and `refund_or_owed` are conventional but not enforced by the loader.

---

## 8. Input References

The `input.*` namespace exposes the user's `TaxReturnInput` data to rules. These are resolved by the engine, not by any rule in a pack.

### Common input references

| Reference                          | What it provides                                       |
|------------------------------------|--------------------------------------------------------|
| `input.filing_status`              | Filing status string: `"single"`, `"mfj"`, `"mfs"`, `"hoh"`, `"qss"` |
| `input.w2.wages`                   | List of W-2 Box 1 wage amounts                         |
| `input.withholding.federal`        | List of federal tax withheld amounts from W-2s         |
| `input.withholding.state.{ST}`     | List of state tax withheld amounts for state `{ST}`    |
| `input.1099int.amount`             | List of taxable interest amounts from 1099-INTs        |
| `input.1099div.ordinary`           | List of ordinary dividend amounts from 1099-DIVs       |
| `input.1099b.net_gain`             | List of net capital gains from 1099-Bs                 |
| `input.1099nec.compensation`       | List of self-employment income from 1099-NECs          |
| `input.ssa.total_benefits`         | Total Social Security benefits received                |
| `input.qualifying_children`        | Number of qualifying children for CTC                  |
| `input.adjustments.student_loan_interest` | Student loan interest paid                      |
| `input.adjustments.hsa_contributions`     | HSA contributions made                          |
| `input.itemized.mortgage_interest` | Home mortgage interest paid                            |
| `input.estimated_payments`         | List of estimated tax payments                         |

### Cross-pack references

State rules commonly reference federal results using `{ ref: "fed.{year}.{rule_id}" }`. The engine runs the federal pack first, so federal results are available when state rules execute.

```yaml
- id: "ga.2024.agi"
  description: "Georgia AGI (starts from federal AGI)"
  type: "formula"
  expression: "federal_agi"
  inputs:
    federal_agi: { ref: "fed.2024.agi.total" }
```

Cross-pack references bypass the intra-pack dependency graph (they are not topologically sorted within the pack), but the engine guarantees the federal pack is fully evaluated first.

---

## 9. Rounding

Every rule that produces a numeric result should declare a rounding mode and precision.

| Field                | Value             | Meaning                                      |
|----------------------|-------------------|----------------------------------------------|
| `rounding`           | `"ROUND_HALF_UP"` | Standard round-half-up (the only supported mode) |
| `rounding_precision` | `0`               | Round to whole dollars                       |
| `rounding_precision` | `2`               | Round to cents                               |

Intermediate rules (e.g., computing a floor or a rate-scaled amount) often use `rounding_precision: 2`. Final output rules (total tax, taxable income, refund) typically use `rounding_precision: 0` to match IRS/state form instructions.

```yaml
rounding: "ROUND_HALF_UP"
rounding_precision: 0
```

`lookup` rules do not perform arithmetic and do not need rounding fields.

---

## 10. Worked Example — Flat-Rate State Pack

This is a complete, minimal rule pack for a hypothetical state "XY" with a 4% flat income tax, two deductions, and state withholding.

**`rule_packs/state/XY/2024/state_XY_2024_manifest.yaml`**

```yaml
version: "1.0.0"
tax_year: 2024
jurisdiction: "XY"
```

**`rule_packs/state/XY/2024/state_XY_2024_rules.yaml`**

```yaml
constants:
  standard_deduction:
    single: "4000"
    mfj:    "8000"
    mfs:    "4000"
    hoh:    "6000"
    qss:    "8000"

rules:
  # Step 1: Start from federal AGI (cross-pack reference)
  - id: "xy.2024.agi"
    description: "XY AGI (starts from federal AGI)"
    type: "formula"
    expression: "federal_agi"
    inputs:
      federal_agi: { ref: "fed.2024.agi.total" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  # Step 2: Look up the standard deduction for filing status
  - id: "xy.2024.standard_deduction"
    description: "XY standard deduction"
    type: "lookup"
    table: "constants.standard_deduction"
    key: { ref: "input.filing_status" }

  # Step 3: Subtract the deduction from AGI
  - id: "xy.2024.taxable_income"
    description: "XY taxable income = max(AGI - deduction, 0)"
    type: "formula"
    expression: "max(agi - deduction, 0)"
    inputs:
      agi:       { ref: "xy.2024.agi" }
      deduction: { ref: "xy.2024.standard_deduction" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  # Step 4: Apply flat 4% rate
  - id: "xy.2024.tax"
    description: "XY income tax at 4% flat rate"
    type: "formula"
    expression: "taxable_income * rate"
    inputs:
      taxable_income: { ref: "xy.2024.taxable_income" }
      rate: { literal: "0.04" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  # Step 5: Sum withholding from all W-2s
  - id: "xy.2024.withholding"
    description: "Total XY tax withheld"
    type: "sum"
    inputs:
      items: { ref: "input.withholding.state.XY" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  # Step 6: Compute refund or balance due
  - id: "xy.2024.refund_or_owed"
    description: "XY refund (positive) or amount owed (negative)"
    type: "formula"
    expression: "withholding - tax"
    inputs:
      withholding: { ref: "xy.2024.withholding" }
      tax:         { ref: "xy.2024.tax" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

The engine reads state output from three conventional rule IDs: `{st}.{year}.tax`, `{st}.{year}.withholding`, and `{st}.{year}.refund_or_owed`. These must exist in every state pack.

---

## 11. Validation

Use `scripts/validate_rule_pack.py` to check a pack before committing:

```bash
python scripts/validate_rule_pack.py rule_packs/state/XY/2024
```

On success:
```
OK: XY 2024 v1.0.0
    Rules: 6
    Checksum: a3f8...
```

On failure, the error message includes the rule ID and the specific problem:

```
VALIDATION FAIL: Rule xy.2024.taxable_income (formula) references unknown identifiers ['deductin']. Declare them under inputs: ['agi', 'deduction']
```

Common validation errors and their causes:

| Error message                              | Cause                                                        |
|--------------------------------------------|--------------------------------------------------------------|
| `Rule id ... does not match jurisdiction prefix` | Rule ID uses the wrong prefix for this pack           |
| `references unknown identifiers [...]`     | Expression uses a name not declared in `inputs`              |
| `references unknown rule id: ...`          | A `{ ref: "..." }` points to a rule that does not exist in the pack |
| `Rule dependency cycle detected`           | Two rules reference each other (directly or indirectly)      |
| `(lookup) must include non-empty 'table'`  | The `table` field is missing or empty                        |
| `(bracket_table) bracket missing 'lower'`  | A bracket entry is missing a required field                  |

The validator runs the same `RulePack.load()` call the engine uses, so a pack that passes validation is guaranteed to load at runtime.

---

## 12. Reference Implementations

| Pack                              | Tax structure                            | Notable features                           |
|-----------------------------------|------------------------------------------|--------------------------------------------|
| `rule_packs/federal/2024/`        | Full 1040-style federal return           | All four rule types, SS taxability worksheet, CTC phaseout |
| `rule_packs/state/GA/2024/`       | Flat rate (5.39%) with deductions        | Simplest state pack with constants         |
| `rule_packs/state/CA/2024/`       | Progressive brackets + surtax            | `bracket_table` + supplemental `formula` for the 1% MHS surtax |
| `rule_packs/state/TX/2024/`       | No income tax                            | Minimal stub: zero tax, withholding sum, refund of over-withheld amounts |

For adding a new state specifically, see `docs/STATE_AUTHORING_GUIDE.md`, which covers required rule IDs, the state template, and integration testing patterns.
