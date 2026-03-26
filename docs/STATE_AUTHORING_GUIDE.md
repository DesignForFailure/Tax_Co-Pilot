<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

# State Rule Pack Authoring Guide

> **[← Back to README](../README.md)** | [Encryption](ENCRYPTION.md) · [Rule Pack Authoring](RULE_PACK_AUTHORING.md) · **State Authoring** · [Export Control](EXPORT_CONTROL.md) · [Disclaimer](DISCLAIMER.md) · [Notice](NOTICE.md)

A practical guide for adding a new state to Tax Co-Pilot's rules-as-data engine.

---

## 1. Overview

Tax Co-Pilot separates tax logic from application code. Each jurisdiction's tax law is expressed as a **YAML rule pack** containing constants and rules that the generic `CalculationEngine` evaluates in topological order. Adding a new state requires no Python changes — only new YAML files and tests.

State rule packs live alongside (and depend on) the federal rule pack. The engine runs the federal pack first, then evaluates each state pack, allowing state rules to reference federal results like AGI.

## 2. Directory Structure

```
rule_packs/
  federal/
    2024/
      federal_2024_manifest.yaml
      federal_2024_rules.yaml
  state/
    GA/
      2024/
        state_GA_2024_manifest.yaml
        state_GA_2024_rules.yaml
    TX/
      2024/
        state_TX_2024_manifest.yaml
        state_TX_2024_rules.yaml
    _template/
      2024/
        state_TEMPLATE_2024_manifest.yaml
        state_TEMPLATE_2024_rules.yaml
```

Each state gets a directory named by its **two-letter postal code** (uppercase), containing a `2024/` subdirectory with exactly two files: a manifest and a rules file.

## 3. Manifest Requirements

The manifest is a small YAML file with three required fields:

```yaml
version: "1.0.0"
tax_year: 2024
jurisdiction: "GA"
```

| Field          | Description                                      |
|----------------|--------------------------------------------------|
| `version`      | Semantic version of this rule pack               |
| `tax_year`     | The tax year these rules apply to                |
| `jurisdiction` | Two-letter state code, matching the directory name |

## 4. Required Rule IDs

The engine extracts state results by **convention**. Each state pack must define rules with these IDs (replace `{st}` with the lowercase state code):

| Rule ID                    | Purpose                                  |
|----------------------------|------------------------------------------|
| `{st}.2024.agi`            | State adjusted gross income              |
| `{st}.2024.standard_deduction` | Standard deduction (if applicable)  |
| `{st}.2024.taxable_income` | State taxable income                     |
| `{st}.2024.tax`            | Computed state income tax                |
| `{st}.2024.withholding`    | Total state tax withheld from W-2s       |
| `{st}.2024.refund_or_owed` | Refund (positive) or balance due (negative) |

The engine looks for `{st}.2024.tax`, `{st}.2024.withholding`, and `{st}.2024.refund_or_owed` to populate the `StateOutput` object. Intermediate rules like `agi` and `taxable_income` appear in the audit trace.

## 5. Cross-Pack Federal AGI Reference

State rules can reference any federal rule result. The most common cross-reference is federal AGI:

```yaml
- id: "ca.2024.agi"
  description: "California AGI (starts from federal AGI)"
  type: "formula"
  expression: "federal_agi"
  inputs:
    federal_agi: { ref: "fed.2024.agi.total" }
```

The `{ ref: "fed.2024.agi.total" }` syntax tells the engine to resolve the value from the federal pack's computation results. This works because the engine runs federal rules before state rules.

## 6. Rule Types

Tax Co-Pilot supports four rule types. Here is a brief example of each.

### formula

Evaluates an arithmetic expression over named inputs. Supports `+`, `-`, `*`, `/`, `max()`, `min()`.

```yaml
- id: "ga.2024.tax"
  type: "formula"
  expression: "taxable_income * rate"
  inputs:
    taxable_income: { ref: "ga.2024.taxable_income" }
    rate: { literal: "0.0539" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 0
```

### lookup

Picks a value from a `constants` table using a key (typically filing status).

```yaml
constants:
  standard_deduction:
    single: "5400"
    mfj: "7100"
    mfs: "3550"
    hoh: "5400"

rules:
  - id: "ga.2024.standard_deduction"
    type: "lookup"
    table: "constants.standard_deduction"
    key: { ref: "input.filing_status" }
```

### sum

Adds all values in a list. Used for withholding collected across multiple W-2s.

```yaml
- id: "ga.2024.withholding"
  type: "sum"
  inputs:
    items: { ref: "input.withholding.state.GA" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 2
```

### bracket_table

Computes progressive tax from graduated brackets, keyed by filing status. Each bracket's rate applies only to income within that bracket's range. Set `upper` to `null` for the top bracket.

```yaml
- id: "ny.2024.tax"
  type: "bracket_table"
  input: { ref: "ny.2024.taxable_income" }
  key: { ref: "input.filing_status" }
  rounding: "ROUND_HALF_UP"
  rounding_precision: 0
  tables:
    single:
      - { lower: "0",     upper: "8500",   rate: "0.04" }
      - { lower: "8500",  upper: "11700",  rate: "0.045" }
      - { lower: "11700", upper: "13900",  rate: "0.0525" }
      - { lower: "13900", upper: null,     rate: "0.055" }
    mfj:
      - { lower: "0",     upper: "17150",  rate: "0.04" }
      - { lower: "17150", upper: "23600",  rate: "0.045" }
      - { lower: "23600", upper: "27900",  rate: "0.0525" }
      - { lower: "27900", upper: null,     rate: "0.055" }
```

## 7. No-Income-Tax States

Nine states have no individual income tax (AK, FL, NH, NV, SD, TN, TX, WA, WY). These still need a minimal rule pack so the engine can report zero tax and return any erroneous withholding.

See `rule_packs/state/TX/2024/` for the canonical example. The key pattern:

- `{st}.2024.agi` — formula returning literal `"0"`
- `{st}.2024.tax` — formula returning literal `"0"`
- `{st}.2024.withholding` — sum of `input.withholding.state.{ST}` (in case W-2s have amounts)
- `{st}.2024.refund_or_owed` — `withholding - tax`

No constants, no deduction rules, no bracket tables needed.

## 8. Testing

Write tests using the `CalculationEngine` with `state_packs` parameter. Load both the federal and state rule packs, construct a `TaxReturnInput`, and verify results.

```python
from pathlib import Path
from decimal import Decimal

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus, Taxpayer, TaxpayerRole,
    TaxReturnInput, W2Data,
)

RULES = Path("rule_packs")
FED = RulePack(RULES / "federal" / "2024")
CA  = RulePack(RULES / "state" / "CA" / "2024")

def test_ca_single_filer() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[Taxpayer(role=TaxpayerRole.PRIMARY, first_name="J", last_name="D")],
        w2s=[
            W2Data(
                payer_name="Employer",
                wages=Decimal("75000"),
                federal_tax_withheld=Decimal("10000"),
                state_code="CA",
                state_wages=Decimal("75000"),
                state_tax_withheld=Decimal("3000"),
            ),
        ],
    )
    run = CalculationEngine(FED, inp, state_packs={"CA": CA}).run()

    ca_out = run.state_outputs[0]
    assert ca_out.state == "CA"
    assert ca_out.tax >= Decimal("0")
    assert ca_out.refund_or_owed == ca_out.withholding - ca_out.tax
```

Place test files in the `tests/` directory. Run with `pytest tests/test_your_state.py -v`.

## 9. Quick Start Checklist

1. **Copy the template:**
   ```bash
   cp -r rule_packs/state/_template rule_packs/state/{ST}
   ```

2. **Rename files:**
   ```bash
   cd rule_packs/state/{ST}/2024
   mv state_TEMPLATE_2024_manifest.yaml state_{ST}_2024_manifest.yaml
   mv state_TEMPLATE_2024_rules.yaml    state_{ST}_2024_rules.yaml
   ```

3. **Update the manifest:** Set `jurisdiction` to your state code and `version` to `"1.0.0"` when ready.

4. **Edit the rules file:**
   - Replace all `{st}` with your lowercase state code (e.g., `ca`)
   - Replace all `{ST}` with your uppercase state code (e.g., `CA`)
   - Fill in actual deduction amounts in `constants`
   - Choose flat-rate (Option A) or progressive brackets (Option B) for the tax rule
   - Delete the unused tax option

5. **For no-income-tax states:** Use `rule_packs/state/TX/2024/` as your starting point instead of the full template. Copy it and replace `tx`/`TX` with your state code.

6. **Write tests:** Add a test file in `tests/` following the pattern in section 8.

7. **Verify:** Run `ruff check . && mypy . && pytest` to confirm everything passes.

8. **Reference implementations:**
   - Progressive/flat-rate state: `rule_packs/state/GA/2024/`
   - No-income-tax stub: `rule_packs/state/TX/2024/`
