# Multi-Year Support Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support tax years 2023 and 2024 concurrently, with dynamic rule pack loading, a year selector in the UI, and year-over-year comparison.

**Architecture:** Replace the hardcoded federal 2024 rule pack with a dynamic loader that discovers available years by scanning `rule_packs/federal/`, caches loaded packs, and selects the correct pack based on the submitted `tax_year`. State packs are similarly loaded per-year. The calculate form's `tax_year` field changes from a readonly input to a `<select>` dropdown populated with discovered years. Year-over-year comparison is handled by the existing `GET /runs/compare?a={id}&b={id}` route which already supports comparing any two runs side-by-side — once multi-year runs exist, users can compare across years using that existing view.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, Jinja2, PyYAML, Decimal, pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|---------------|
| `rule_packs/federal/2023/federal_2023_manifest.yaml` | Create | 2023 manifest (version, year, jurisdiction) |
| `rule_packs/federal/2023/federal_2023_rules.yaml` | Create | 2023 constants + rules (different brackets, deductions, limits) |
| `rule_packs/state/GA/2023/state_GA_2023_manifest.yaml` | Create | GA 2023 manifest |
| `rule_packs/state/GA/2023/state_GA_2023_rules.yaml` | Create | GA 2023 rules (5.75% graduated brackets) |
| `main.py` | Modify | Dynamic year-aware rule pack loading, cache, updated routes |
| `app/templates/pages/calculate.html` | Modify | tax_year dropdown populated with available years |
| `tests/test_multi_year.py` | Create | Golden tests for 2023 calculations, dynamic loading, routes |
| `tests/test_state_expansion.py` | Modify | Update imports: `_load_state_packs` → `_get_state_packs` |
| `tests/test_golden.py` | No change | Existing 2024 tests remain untouched |
| `README.md` | Modify | Add new files to tree |
| `CHANGELOG.md` | Modify | Record milestone 9 changes |
| `.agent_tools/05_session_log.md` | Modify | Append session log entry |

---

## Chunk 1: 2023 Federal Rule Pack

### Task 1: Create 2023 federal manifest

**Files:**
- Create: `rule_packs/federal/2023/federal_2023_manifest.yaml`

- [ ] **Step 1: Create the manifest file**

```yaml
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

version: "1.0.0"
tax_year: 2023
jurisdiction: "federal"
```

- [ ] **Step 2: Verify the manifest loads**

Run: `python -c "import yaml; from pathlib import Path; d = yaml.safe_load(Path('rule_packs/federal/2023/federal_2023_manifest.yaml').read_text()); print(d)"`
Expected: `{'version': '1.0.0', 'tax_year': 2023, 'jurisdiction': 'federal'}`

---

### Task 2: Create 2023 federal rules

**Files:**
- Create: `rule_packs/federal/2023/federal_2023_rules.yaml`

The structure is identical to `rule_packs/federal/2024/federal_2024_rules.yaml` with these changes:
1. All rule IDs: `fed.2024.*` → `fed.2023.*`
2. All internal refs: `fed.2024.*` → `fed.2023.*`
3. Updated constants for 2023 IRS values
4. Updated bracket tables for 2023 thresholds

- [ ] **Step 1: Create the 2023 rules file**

```yaml
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

constants:
  standard_deduction:
    single: "13850"
    mfj: "27700"
    mfs: "13850"
    hoh: "20800"
    qss: "27700"

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

  adjustment_limits:
    student_loan_interest_max: "2500"
    educator_expenses_max: "300"
    ira_limit: "6500"
    hsa_limit:
      single: "3850"
      mfj: "7750"
      mfs: "3850"
      hoh: "3850"
      qss: "7750"

rules:
  - id: "fed.2023.gross_income.wages"
    description: "Total W-2 wages (Box 1)"
    form_line: "1040 Line 1a"
    type: "sum"
    inputs:
      items: { ref: "input.w2.wages" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.interest"
    description: "Total taxable interest (1099-INT)"
    form_line: "1040 Line 2b"
    type: "sum"
    inputs:
      items: { ref: "input.1099int.amount" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.dividends"
    description: "Total ordinary dividends (1099-DIV Box 1a)"
    form_line: "1040 Line 3b"
    type: "sum"
    inputs:
      items: { ref: "input.1099div.ordinary" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.capital_gains"
    description: "Net capital gains (1099-B proceeds - basis)"
    form_line: "Schedule D"
    type: "sum"
    inputs:
      items: { ref: "input.1099b.net_gain" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.self_employment"
    description: "Total self-employment income (1099-NEC Box 1)"
    form_line: "Schedule 1 Line 3"
    type: "sum"
    inputs:
      items: { ref: "input.1099nec.compensation" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.capital_gains_limited"
    description: "Net capital gains after loss limitation (-$3,000 max loss)"
    form_line: "1040 Line 7"
    type: "formula"
    expression: "max(gains, neg_limit)"
    inputs:
      gains: { ref: "fed.2023.gross_income.capital_gains" }
      neg_limit: { literal: "-3000" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.other"
    description: "Other income (Line 8 catch-all)"
    form_line: "Schedule 1 Line 8"
    type: "formula"
    expression: "other"
    inputs:
      other: { ref: "input.other_income" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.ss_half_benefits"
    description: "50% of total Social Security benefits"
    form_line: "SS Worksheet Line 2"
    type: "formula"
    expression: "benefits * half"
    inputs:
      benefits: { ref: "input.ssa.total_benefits" }
      half: { literal: "0.5" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.ss_base_threshold"
    description: "SS taxability base threshold by filing status"
    form_line: "SS Worksheet"
    type: "lookup"
    table: "constants.ss_taxability.base_threshold"
    key: { ref: "input.filing_status" }

  - id: "fed.2023.gross_income.ss_upper_threshold"
    description: "SS taxability upper threshold by filing status"
    form_line: "SS Worksheet"
    type: "lookup"
    table: "constants.ss_taxability.upper_threshold"
    key: { ref: "input.filing_status" }

  - id: "fed.2023.gross_income.ss_max_taxable"
    description: "85% of total SS benefits (maximum taxable amount)"
    form_line: "SS Worksheet Line 4"
    type: "formula"
    expression: "benefits * rate"
    inputs:
      benefits: { ref: "input.ssa.total_benefits" }
      rate: { literal: "0.85" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.ss_provisional"
    description: "Provisional income for SS taxability (non-SS income + 50% benefits)"
    form_line: "SS Worksheet Line 6"
    type: "formula"
    expression: "wages + interest + dividends + gains + se + other + half_ss"
    inputs:
      wages: { ref: "fed.2023.gross_income.wages" }
      interest: { ref: "fed.2023.gross_income.interest" }
      dividends: { ref: "fed.2023.gross_income.dividends" }
      gains: { ref: "fed.2023.gross_income.capital_gains_limited" }
      se: { ref: "fed.2023.gross_income.self_employment" }
      other: { ref: "fed.2023.gross_income.other" }
      half_ss: { ref: "fed.2023.gross_income.ss_half_benefits" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.ss_lower_calc"
    description: "SS taxability lower-tier amount (50% of provisional above base)"
    form_line: "SS Worksheet Line 10"
    type: "formula"
    expression: "max(min((prov - base) * rate, (upper - base) * rate), zero)"
    inputs:
      prov: { ref: "fed.2023.gross_income.ss_provisional" }
      base: { ref: "fed.2023.gross_income.ss_base_threshold" }
      upper: { ref: "fed.2023.gross_income.ss_upper_threshold" }
      rate: { literal: "0.50" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.ss_upper_calc"
    description: "SS taxability upper-tier amount (85% of provisional above upper threshold)"
    form_line: "SS Worksheet Line 14"
    type: "formula"
    expression: "max((prov - upper) * rate, zero)"
    inputs:
      prov: { ref: "fed.2023.gross_income.ss_provisional" }
      upper: { ref: "fed.2023.gross_income.ss_upper_threshold" }
      rate: { literal: "0.85" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.social_security"
    description: "Taxable Social Security benefits"
    form_line: "1040 Line 6b"
    type: "formula"
    expression: "min(max_taxable, lower + upper)"
    inputs:
      max_taxable: { ref: "fed.2023.gross_income.ss_max_taxable" }
      lower: { ref: "fed.2023.gross_income.ss_lower_calc" }
      upper: { ref: "fed.2023.gross_income.ss_upper_calc" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.gross_income.total"
    description: "Total income (all sources)"
    form_line: "1040 Line 9"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2023.gross_income.wages" }
        - { ref: "fed.2023.gross_income.interest" }
        - { ref: "fed.2023.gross_income.dividends" }
        - { ref: "fed.2023.gross_income.capital_gains_limited" }
        - { ref: "fed.2023.gross_income.self_employment" }
        - { ref: "fed.2023.gross_income.social_security" }
        - { ref: "fed.2023.gross_income.other" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.hsa_limit"
    description: "HSA contribution limit by filing status"
    form_line: "Form 8889"
    type: "lookup"
    table: "constants.adjustment_limits.hsa_limit"
    key: { ref: "input.filing_status" }

  - id: "fed.2023.adjustments.student_loan"
    description: "Student loan interest deduction (capped at $2,500)"
    form_line: "Schedule 1 Line 21"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.student_loan_interest" }
      cap: { literal: "2500" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.educator"
    description: "Educator expenses deduction (capped at $300)"
    form_line: "Schedule 1 Line 11"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.educator_expenses" }
      cap: { literal: "300" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.hsa"
    description: "HSA deduction (capped by filing status)"
    form_line: "Schedule 1 Line 13"
    type: "formula"
    expression: "min(input, limit)"
    inputs:
      input: { ref: "input.adjustments.hsa_contributions" }
      limit: { ref: "fed.2023.adjustments.hsa_limit" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.ira"
    description: "IRA deduction (capped at $6,500)"
    form_line: "Schedule 1 Line 20"
    type: "formula"
    expression: "min(input, cap)"
    inputs:
      input: { ref: "input.adjustments.ira_contributions" }
      cap: { literal: "6500" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.se_tax"
    description: "Self-employment tax deduction (user provides deductible half)"
    form_line: "Schedule 1 Line 15"
    type: "formula"
    expression: "input"
    inputs:
      input: { ref: "input.adjustments.self_employment_tax_deduction" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.adjustments.total"
    description: "Total above-the-line adjustments"
    form_line: "Schedule 1 Line 26"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2023.adjustments.student_loan" }
        - { ref: "fed.2023.adjustments.educator" }
        - { ref: "fed.2023.adjustments.hsa" }
        - { ref: "fed.2023.adjustments.ira" }
        - { ref: "fed.2023.adjustments.se_tax" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.agi.total"
    description: "Adjusted gross income (gross income minus adjustments)"
    form_line: "1040 Line 11"
    type: "formula"
    expression: "max(gross - adj, zero)"
    inputs:
      gross: { ref: "fed.2023.gross_income.total" }
      adj: { ref: "fed.2023.adjustments.total" }
      zero: { literal: "0" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.standard_deduction"
    description: "Standard deduction for 2023"
    form_line: "1040 Line 13"
    type: "lookup"
    table: "constants.standard_deduction"
    key: { ref: "input.filing_status" }

  - id: "fed.2023.taxable_income"
    description: "Taxable income = max(AGI - standard deduction, 0)"
    form_line: "1040 Line 15"
    type: "formula"
    expression: "max(agi - deduction, 0)"
    inputs:
      agi: { ref: "fed.2023.agi.total" }
      deduction: { ref: "fed.2023.standard_deduction" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "fed.2023.tax.brackets"
    description: "Federal income tax using 2023 bracket tables"
    form_line: "1040 Line 16"
    type: "bracket_table"
    input: { ref: "fed.2023.taxable_income" }
    key: { ref: "input.filing_status" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
    tables:
      single:
        - { lower: "0", upper: "11000", rate: "0.10" }
        - { lower: "11000", upper: "44725", rate: "0.12" }
        - { lower: "44725", upper: "95375", rate: "0.22" }
        - { lower: "95375", upper: "182100", rate: "0.24" }
        - { lower: "182100", upper: "231250", rate: "0.32" }
        - { lower: "231250", upper: "578125", rate: "0.35" }
        - { lower: "578125", upper: null, rate: "0.37" }
      mfj:
        - { lower: "0", upper: "22000", rate: "0.10" }
        - { lower: "22000", upper: "89450", rate: "0.12" }
        - { lower: "89450", upper: "190750", rate: "0.22" }
        - { lower: "190750", upper: "364200", rate: "0.24" }
        - { lower: "364200", upper: "462500", rate: "0.32" }
        - { lower: "462500", upper: "693750", rate: "0.35" }
        - { lower: "693750", upper: null, rate: "0.37" }
      mfs:
        - { lower: "0", upper: "11000", rate: "0.10" }
        - { lower: "11000", upper: "44725", rate: "0.12" }
        - { lower: "44725", upper: "95375", rate: "0.22" }
        - { lower: "95375", upper: "182100", rate: "0.24" }
        - { lower: "182100", upper: "231250", rate: "0.32" }
        - { lower: "231250", upper: "346875", rate: "0.35" }
        - { lower: "346875", upper: null, rate: "0.37" }
      hoh:
        - { lower: "0", upper: "15700", rate: "0.10" }
        - { lower: "15700", upper: "59850", rate: "0.12" }
        - { lower: "59850", upper: "95350", rate: "0.22" }
        - { lower: "95350", upper: "182100", rate: "0.24" }
        - { lower: "182100", upper: "231250", rate: "0.32" }
        - { lower: "231250", upper: "578100", rate: "0.35" }
        - { lower: "578100", upper: null, rate: "0.37" }
      qss:
        - { lower: "0", upper: "22000", rate: "0.10" }
        - { lower: "22000", upper: "89450", rate: "0.12" }
        - { lower: "89450", upper: "190750", rate: "0.22" }
        - { lower: "190750", upper: "364200", rate: "0.24" }
        - { lower: "364200", upper: "462500", rate: "0.32" }
        - { lower: "462500", upper: "693750", rate: "0.35" }
        - { lower: "693750", upper: null, rate: "0.37" }

  - id: "fed.2023.total_withholding"
    description: "Total federal withholding"
    form_line: "1040 Line 25d"
    type: "sum"
    inputs:
      items: { ref: "input.withholding.federal" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.estimated_payments"
    description: "Estimated tax payments made during the year"
    form_line: "1040 Line 26"
    type: "sum"
    inputs:
      items: { ref: "input.estimated_payments" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.total_payments"
    description: "Total payments (withholding + estimated)"
    form_line: "1040 Line 33"
    type: "sum"
    inputs:
      items:
        - { ref: "fed.2023.total_withholding" }
        - { ref: "fed.2023.estimated_payments" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "fed.2023.refund_or_owed"
    description: "Refund (positive) or amount owed (negative)"
    form_line: "1040 Line 34/37"
    type: "formula"
    expression: "payments - tax"
    inputs:
      payments: { ref: "fed.2023.total_payments" }
      tax: { ref: "fed.2023.tax.brackets" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

**Key differences from 2024:**
- `standard_deduction`: single $13,850 (was $14,600), mfj $27,700 (was $29,200), hoh $20,800 (was $21,900)
- `adjustment_limits.ira_limit`: $6,500 (was $7,000)
- `adjustment_limits.hsa_limit`: single $3,850 (was $4,150), mfj $7,750 (was $8,300)
- Bracket thresholds differ at every level (see tables above)
- All rule IDs use `fed.2023.*` namespace
- All internal refs point to `fed.2023.*` rules

- [ ] **Step 2: Verify the rule pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/federal/2023')); print(f'Loaded {len(p.rules)} rules, year={p.tax_year}')"`
Expected: `Loaded 31 rules, year=2023`

- [ ] **Step 3: Commit**

```bash
git add rule_packs/federal/2023/
git commit -m "feat(multi-year): add 2023 federal rule pack with IRS bracket tables"
```

---

## Chunk 2: 2023 GA State Rule Pack

### Task 3: Create 2023 GA state rule pack

**Files:**
- Create: `rule_packs/state/GA/2023/state_GA_2023_manifest.yaml`
- Create: `rule_packs/state/GA/2023/state_GA_2023_rules.yaml`

GA 2023 uses a graduated bracket system (5.75% top rate), unlike 2024's flat 5.39%. Standard deduction and exemption amounts also differ.

- [ ] **Step 1: Create the GA 2023 manifest**

```yaml
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

version: "1.0.0"
tax_year: 2023
jurisdiction: "GA"
```

- [ ] **Step 2: Create the GA 2023 rules**

```yaml
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

constants:
  standard_deduction:
    single: "5400"
    mfj: "7100"
    mfs: "3550"
    hoh: "5400"
  personal_exemption:
    single: "2700"
    mfj: "7400"
    mfs: "2700"
    hoh: "2700"

rules:
  - id: "ga.2023.agi"
    description: "Georgia AGI (starts from federal AGI)"
    type: "formula"
    expression: "federal_agi"
    inputs:
      federal_agi: { ref: "fed.2023.agi.total" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "ga.2023.standard_deduction"
    description: "Georgia standard deduction"
    type: "lookup"
    table: "constants.standard_deduction"
    key: { ref: "input.filing_status" }

  - id: "ga.2023.personal_exemption"
    description: "Georgia personal exemption"
    type: "lookup"
    table: "constants.personal_exemption"
    key: { ref: "input.filing_status" }

  - id: "ga.2023.taxable_income"
    description: "Georgia taxable income = max(AGI - standard deduction - personal exemption, 0)"
    type: "formula"
    expression: "max(agi - deduction - exemption, 0)"
    inputs:
      agi: { ref: "ga.2023.agi" }
      deduction: { ref: "ga.2023.standard_deduction" }
      exemption: { ref: "ga.2023.personal_exemption" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0

  - id: "ga.2023.tax"
    description: "Georgia income tax (2023 graduated brackets, top rate 5.75%)"
    type: "bracket_table"
    input: { ref: "ga.2023.taxable_income" }
    key: { ref: "input.filing_status" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
    tables:
      single:
        - { lower: "0", upper: "750", rate: "0.01" }
        - { lower: "750", upper: "2250", rate: "0.02" }
        - { lower: "2250", upper: "3750", rate: "0.03" }
        - { lower: "3750", upper: "5250", rate: "0.04" }
        - { lower: "5250", upper: "7000", rate: "0.05" }
        - { lower: "7000", upper: null, rate: "0.0575" }
      mfj:
        - { lower: "0", upper: "1000", rate: "0.01" }
        - { lower: "1000", upper: "3000", rate: "0.02" }
        - { lower: "3000", upper: "5000", rate: "0.03" }
        - { lower: "5000", upper: "7000", rate: "0.04" }
        - { lower: "7000", upper: "10000", rate: "0.05" }
        - { lower: "10000", upper: null, rate: "0.0575" }
      mfs:
        - { lower: "0", upper: "500", rate: "0.01" }
        - { lower: "500", upper: "1500", rate: "0.02" }
        - { lower: "1500", upper: "2500", rate: "0.03" }
        - { lower: "2500", upper: "3500", rate: "0.04" }
        - { lower: "3500", upper: "5000", rate: "0.05" }
        - { lower: "5000", upper: null, rate: "0.0575" }
      hoh:
        - { lower: "0", upper: "750", rate: "0.01" }
        - { lower: "750", upper: "2250", rate: "0.02" }
        - { lower: "2250", upper: "3750", rate: "0.03" }
        - { lower: "3750", upper: "5250", rate: "0.04" }
        - { lower: "5250", upper: "7000", rate: "0.05" }
        - { lower: "7000", upper: null, rate: "0.0575" }

  - id: "ga.2023.withholding"
    description: "Total Georgia tax withheld"
    type: "sum"
    inputs:
      items: { ref: "input.withholding.state.GA" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 2

  - id: "ga.2023.refund_or_owed"
    description: "Georgia refund (positive) or amount owed (negative)"
    type: "formula"
    expression: "withholding - tax"
    inputs:
      withholding: { ref: "ga.2023.withholding" }
      tax: { ref: "ga.2023.tax" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

**Key differences from GA 2024:**
- 2023 uses graduated `bracket_table` (6 brackets, top 5.75%) instead of flat 5.39% formula
- Same standard deduction and personal exemption amounts (GA didn't change these between 2023-2024)
- All rule IDs use `ga.2023.*` namespace
- Cross-pack ref points to `fed.2023.agi.total` instead of `fed.2024.agi.total`

- [ ] **Step 3: Verify the pack loads**

Run: `python -c "from app.engine.rule_loader import RulePack; from pathlib import Path; p = RulePack.load(Path('rule_packs/state/GA/2023')); print(f'Loaded {len(p.rules)} rules, year={p.tax_year}')"`
Expected: `Loaded 7 rules, year=2023`

- [ ] **Step 4: Commit**

```bash
git add rule_packs/state/GA/2023/
git commit -m "feat(multi-year): add GA 2023 state rule pack with graduated brackets"
```

---

## Chunk 3: Dynamic Rule Pack Loading

### Task 4: Replace hardcoded rule pack loading with dynamic discovery

**Files:**
- Modify: `main.py:130-153`

Currently `main.py` has:
```python
RULE_PACK_DIR = BASE_DIR / "rule_packs" / "federal" / "2024"
rule_pack = RulePack.load(RULE_PACK_DIR)
...
state_packs = _load_state_packs(2024)
```

Replace with dynamic discovery and caching.

- [ ] **Step 1: Write failing test for dynamic loading**

Create `tests/test_multi_year.py`:

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for Milestone 9: Multi-Year Support.

Covers: dynamic rule pack loading, 2023 federal calculations,
2023 GA state calculations, year-over-year comparison.
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED_2023 = RulePack.load(Path("rule_packs/federal/2023"))
FED_2024 = RulePack.load(Path("rule_packs/federal/2024"))


def test_2023_pack_loads_correct_year() -> None:
    assert FED_2023.tax_year == 2023
    assert FED_2023.jurisdiction == "federal"
    assert len(FED_2023.rules) == 31


def test_2024_pack_loads_correct_year() -> None:
    assert FED_2024.tax_year == 2024
    assert FED_2024.jurisdiction == "federal"
    assert len(FED_2024.rules) == 31
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_multi_year.py::test_2023_pack_loads_correct_year -v`
Expected: PASS

- [ ] **Step 3: Replace hardcoded loading in main.py**

Replace lines 133-153 in `main.py`. Change:

```python
RULE_PACK_DIR = BASE_DIR / "rule_packs" / "federal" / "2024"
rule_pack = RulePack.load(RULE_PACK_DIR)

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

To:

```python
FEDERAL_PACKS_DIR = BASE_DIR / "rule_packs" / "federal"
STATE_PACKS_DIR = BASE_DIR / "rule_packs" / "state"

# Cache: year -> loaded RulePack / state dict
_federal_cache: dict[int, RulePack] = {}
_state_cache: dict[int, dict[str, RulePack]] = {}


def _discover_available_years() -> list[int]:
    """Scan rule_packs/federal/ for available tax years."""
    years: list[int] = []
    if not FEDERAL_PACKS_DIR.exists():
        return years
    for year_dir in sorted(FEDERAL_PACKS_DIR.iterdir()):
        if year_dir.is_dir() and year_dir.name.isdigit():
            years.append(int(year_dir.name))
    return years


def _get_federal_pack(year: int) -> RulePack:
    """Load and cache a federal rule pack for the given year."""
    if year not in _federal_cache:
        pack_dir = FEDERAL_PACKS_DIR / str(year)
        _federal_cache[year] = RulePack.load(pack_dir)
    return _federal_cache[year]


def _get_state_packs(year: int) -> dict[str, RulePack]:
    """Load and cache all state rule packs for the given year."""
    if year not in _state_cache:
        packs: dict[str, RulePack] = {}
        if STATE_PACKS_DIR.exists():
            for state_dir in sorted(STATE_PACKS_DIR.iterdir()):
                if not state_dir.is_dir() or state_dir.name.startswith("_"):
                    continue
                year_dir = state_dir / str(year)
                if year_dir.exists():
                    packs[state_dir.name.upper()] = RulePack.load(year_dir)
        _state_cache[year] = packs
    return _state_cache[year]


available_years = _discover_available_years()

# Pre-warm caches for all discovered years
for _yr in available_years:
    _get_federal_pack(_yr)
    _get_state_packs(_yr)
```

- [ ] **Step 4: Update all references to `rule_pack` and `state_packs` in main.py**

There are three places that reference the old globals:

**4a.** In `calculate_submit` (~line 499-500), change:
```python
    run = CalculationEngine(
        rule_pack, inputs, state_packs=active_state_packs
    ).run()
```
To:
```python
    fed_pack = _get_federal_pack(inputs.tax_year)
    year_state_packs = _get_state_packs(inputs.tax_year)
    active_state_packs = {
        s: year_state_packs[s] for s in states_needed if s in year_state_packs
    }
    run = CalculationEngine(
        fed_pack, inputs, state_packs=active_state_packs
    ).run()
```

Also remove the old `active_state_packs` dict comprehension that references `state_packs` global (the 3 lines before — `states_needed = ...`, `active_state_packs = ...`). The `states_needed` extraction stays the same but `state_packs` is replaced by `year_state_packs`.

**4b.** In the whatif POST route (~line 606), change:
```python
    engine = WhatIfEngine(rule_pack)
```
To:
```python
    engine = WhatIfEngine(_get_federal_pack(inputs.tax_year))
```

**4c.** In `calculate_form` GET route (~line 296-301), pass available years to template:
```python
@app.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/calculate.html",
        {"request": request, "csrf": csrf, "available_years": available_years},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp
```

- [ ] **Step 5: Update `tests/test_state_expansion.py` imports**

Two tests import the old `_load_state_packs` function. Update both occurrences:

In `tests/test_state_expansion.py`, change:
```python
    from main import _load_state_packs
```
To:
```python
    from main import _get_state_packs
```

And change:
```python
    packs = _load_state_packs(2024)
```
To:
```python
    packs = _get_state_packs(2024)
```

This appears twice in the file — in `test_state_pack_discovery` (~line 262) and `test_state_pack_discovery_skips_template` (~line 275).

- [ ] **Step 6: Run existing tests to verify no regressions**

Run: `python -m pytest tests/test_golden.py tests/test_golden2.py tests/test_forms.py tests/test_state_expansion.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add main.py tests/test_state_expansion.py
git commit -m "feat(multi-year): dynamic year-aware federal and state rule pack loading with cache"
```

---

### Task 5: Update calculate form — year dropdown

**Files:**
- Modify: `app/templates/pages/calculate.html:15`

- [ ] **Step 1: Replace readonly input with select dropdown**

In `app/templates/pages/calculate.html`, change:

```html
<div><label>Tax Year</label><input type="number" name="tax_year" value="2024" readonly></div>
```

To:

```html
<div>
    <label>Tax Year</label>
    <select name="tax_year">
        {% for yr in available_years|sort(reverse=true) %}
        <option value="{{ yr }}" {% if yr == 2024 %}selected{% endif %}>{{ yr }}</option>
        {% endfor %}
    </select>
</div>
```

- [ ] **Step 2: Verify the form renders**

Run: `python -m pytest tests/test_milestone6_routes.py::test_calculate_page_returns_200 -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/calculate.html
git commit -m "feat(multi-year): change tax year from readonly input to dropdown"
```

---

## Chunk 4: Golden Tests for 2023

### Task 6: Write 2023 federal golden tests

**Files:**
- Modify: `tests/test_multi_year.py`

- [ ] **Step 1: Add 2023 calculation golden tests**

Append to `tests/test_multi_year.py`:

```python
def test_2023_single_w2() -> None:
    """Single filer, $50k wages, 2023.

    Standard deduction: $13,850. Taxable: $36,150.
    Tax: 10% on $11,000 = $1,100 + 12% on $25,150 = $3,018 = $4,118
    Refund: $6,000 - $4,118 = $1,882
    """
    inp = TaxReturnInput(
        tax_year=2023,
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
    run = CalculationEngine(FED_2023, inp).run()

    assert run.output.standard_deduction == Decimal("13850")
    assert run.output.taxable_income == Decimal("36150")
    assert run.output.federal_tax == Decimal("4118")
    assert run.output.refund_or_owed == Decimal("1882")


def test_2023_mfj_w2() -> None:
    """MFJ, $85k wages, 2023.

    Standard deduction: $27,700. Taxable: $57,300.
    Tax: 10% on $22,000 = $2,200 + 12% on $35,300 = $4,236 = $6,436
    Refund: $12,000 - $6,436 = $5,564
    """
    inp = TaxReturnInput(
        tax_year=2023,
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
    run = CalculationEngine(FED_2023, inp).run()

    assert run.output.standard_deduction == Decimal("27700")
    assert run.output.taxable_income == Decimal("57300")
    assert run.output.federal_tax == Decimal("6436")
    assert run.output.refund_or_owed == Decimal("5564")


def test_2023_differs_from_2024() -> None:
    """Same inputs should produce different results for 2023 vs 2024."""
    inp_2023 = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    inp_2024 = inp_2023.model_copy(update={"tax_year": 2024})

    run_2023 = CalculationEngine(FED_2023, inp_2023).run()
    run_2024 = CalculationEngine(FED_2024, inp_2024).run()

    # Different standard deductions
    assert run_2023.output.standard_deduction == Decimal("13850")
    assert run_2024.output.standard_deduction == Decimal("14600")

    # Different taxable income and tax
    assert run_2023.output.taxable_income != run_2024.output.taxable_income
    assert run_2023.output.federal_tax != run_2024.output.federal_tax


def test_2023_zero_income() -> None:
    """Zero income produces zero tax for 2023."""
    inp = TaxReturnInput(
        tax_year=2023,
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
    run = CalculationEngine(FED_2023, inp).run()
    assert run.output.taxable_income == Decimal("0")
    assert run.output.federal_tax == Decimal("0")


def test_2023_trace_completeness() -> None:
    """Every rule in the 2023 pack should appear in the trace."""
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp).run()
    traced_ids = {t.rule_id for t in run.trace}
    expected = {
        "fed.2023.gross_income.wages",
        "fed.2023.gross_income.interest",
        "fed.2023.gross_income.dividends",
        "fed.2023.gross_income.capital_gains",
        "fed.2023.gross_income.capital_gains_limited",
        "fed.2023.gross_income.self_employment",
        "fed.2023.gross_income.other",
        "fed.2023.gross_income.ss_half_benefits",
        "fed.2023.gross_income.ss_provisional",
        "fed.2023.gross_income.ss_base_threshold",
        "fed.2023.gross_income.ss_upper_threshold",
        "fed.2023.gross_income.ss_lower_calc",
        "fed.2023.gross_income.ss_upper_calc",
        "fed.2023.gross_income.ss_max_taxable",
        "fed.2023.gross_income.social_security",
        "fed.2023.gross_income.total",
        "fed.2023.adjustments.hsa_limit",
        "fed.2023.adjustments.student_loan",
        "fed.2023.adjustments.educator",
        "fed.2023.adjustments.hsa",
        "fed.2023.adjustments.ira",
        "fed.2023.adjustments.se_tax",
        "fed.2023.adjustments.total",
        "fed.2023.agi.total",
        "fed.2023.standard_deduction",
        "fed.2023.taxable_income",
        "fed.2023.tax.brackets",
        "fed.2023.total_withholding",
        "fed.2023.estimated_payments",
        "fed.2023.total_payments",
        "fed.2023.refund_or_owed",
    }
    assert expected == traced_ids
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_multi_year.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_multi_year.py
git commit -m "test(multi-year): add 2023 federal golden tests and trace completeness"
```

---

### Task 7: Add 2023 GA state test and route integration tests

**Files:**
- Modify: `tests/test_multi_year.py`

- [ ] **Step 1: Add GA 2023 and route tests**

Append to `tests/test_multi_year.py`:

```python
import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db
from main import app

GA_2023 = RulePack.load(Path("rule_packs/state/GA/2023"))

CSRF = "test-csrf-token"


@pytest.fixture()
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def test_2023_ga_state_tax() -> None:
    """GA 2023: $85k MFJ, GA graduated brackets."""
    inp = TaxReturnInput(
        tax_year=2023,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[
                    W2Data(
                        employer_name="X",
                        wages=Decimal("85000"),
                        federal_withheld=Decimal("12000"),
                        state="GA",
                        state_withheld=Decimal("2000"),
                    )
                ],
            )
        ],
    )
    run = CalculationEngine(FED_2023, inp, state_packs={"GA": GA_2023}).run()
    assert run.state_outputs, "Expected GA output"
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    assert ga.state_agi == run.output.agi
    assert ga.state_taxable_income >= 0
    # GA 2023 uses graduated brackets (top 5.75%), not flat 5.39%
    assert ga.state_tax > 0


def test_calculate_with_2023(_ensure_db: None) -> None:
    """Submit a calculation using tax year 2023 via the form."""
    client = _client()
    form = {
        "csrf_token": CSRF,
        "tax_year": "2023",
        "filing_status": "single",
        "p_first": "Test",
        "p_last": "User",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "50000",
        "p_w2_0_federal_withheld": "6000",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303

    from app.services.database import list_return_runs

    runs = list_return_runs()
    assert runs
    # Verify at least one run used 2023 (don't rely on ordering)
    assert any(r["tax_year"] == 2023 for r in runs)


def test_calculate_form_shows_year_dropdown(_ensure_db: None) -> None:
    """The calculate form should show available years as a dropdown."""
    client = _client()
    r = client.get("/calculate")
    assert r.status_code == 200
    assert "2023" in r.text
    assert "2024" in r.text
    assert "<select" in r.text
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `python -m pytest tests/test_multi_year.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_multi_year.py
git commit -m "test(multi-year): add GA 2023 state test and route integration tests"
```

---

## Chunk 5: Final Validation and Documentation

### Task 8: Run full test suite and lint checks

- [ ] **Step 1: Run ruff**

Run: `ruff check .`
Expected: PASS (no new violations)

- [ ] **Step 2: Run mypy**

Run: `mypy .`
Expected: PASS (no new errors)

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest -v`
Expected: All tests pass including new test_multi_year.py

- [ ] **Step 4: Fix any issues found**

If lint/type/test errors, fix them before proceeding.

---

### Task 9: Update README tree and CHANGELOG

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update README.md file tree**

Add new files to the tree:
- `rule_packs/federal/2023/` section (manifest + rules)
- `rule_packs/state/GA/2023/` section (manifest + rules)
- `tests/test_multi_year.py` (under `tests/`)

- [ ] **Step 2: Update CHANGELOG.md**

Add under `## [Unreleased]`:

```markdown
### Added
- 2023 federal rule pack (`rule_packs/federal/2023/`) with IRS bracket tables, standard deductions, and adjustment limits.
- 2023 Georgia state rule pack (`rule_packs/state/GA/2023/`) with graduated bracket system (5.75% top rate).
- Dynamic rule pack loading: discovers available years by scanning `rule_packs/federal/`, caches loaded packs.
- Tax year dropdown on calculate form (was readonly, now selectable).
- `_discover_available_years()`, `_get_federal_pack()`, `_get_state_packs()` helpers in `main.py`.
- 2023 golden tests and trace completeness tests (`tests/test_multi_year.py`).

### Changed
- `main.py` rule pack loading: replaced hardcoded 2024 federal/state pack with year-aware dynamic loading and caching.
- Calculate form: tax year field changed from `<input readonly>` to `<select>` dropdown.
```

- [ ] **Step 3: Commit**

```bash
git add README.md CHANGELOG.md
git commit -m "docs: update README tree and CHANGELOG for Milestone 9 Multi-Year Support"
```

---

### Task 10: Session log entry

**Files:**
- Modify: `.agent_tools/05_session_log.md`

- [ ] **Step 1: Append session log entry**

```
- [YYYY-MM-DD] rule_packs/federal/2023/federal_2023_manifest.yaml, rule_packs/federal/2023/federal_2023_rules.yaml, rule_packs/state/GA/2023/state_GA_2023_manifest.yaml, rule_packs/state/GA/2023/state_GA_2023_rules.yaml, main.py, app/templates/pages/calculate.html, tests/test_multi_year.py, README.md, CHANGELOG.md: Milestone 9 — 2023 federal rule pack (different brackets/deductions/limits), 2023 GA state pack (graduated brackets), dynamic year-aware rule pack loading with caching, tax year dropdown on calculate form.
```

Replace `YYYY-MM-DD` with today's date.

- [ ] **Step 2: Commit**

```bash
git add .agent_tools/05_session_log.md
git commit -m "docs: add session log entry for Milestone 9"
```
