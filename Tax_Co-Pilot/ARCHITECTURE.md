# Tax Copilot â€” Architecture & Design Document

## Assumptions

1. **Two taxpayers max** (you + spouse). No dependents modeled in MVP (stub only).
2. **Tax years**: 2024 first, structure supports any year.
3. **MVP filing statuses**: Single, MFJ, MFS. HoH/QSS deferred.
4. **MVP income types**: W-2, 1099-INT, 1099-DIV, 1099-B (short/long-term capital gains). Tips via W-2 Box 7.
5. **MVP state**: Georgia module stub. Texas = no state return needed (modeled as zero-rate state).
6. **Military modeling**: Domicile/residency fields on taxpayer, SCRA flag, combat zone exclusion flag. Rule application deferred to rule packs.
7. **Rule engine choice**: **Option A â€” YAML rule packs compiled to constrained AST**. Rationale: YAML is human-readable/editable, compiles to a safe evaluator with no arbitrary code execution, and versioning is trivial via file checksums.
8. **Numeric strategy**: Python `Decimal` with explicit rounding policies per rule (ROUND_HALF_UP default, matching IRS rounding).
9. **Stack**: Python 3.12 + FastAPI + SQLite + Jinja2 server-rendered UI (HTMX for interactivity). No JS framework needed in MVP.
10. **Encryption**: SQLCipher for encrypted SQLite at rest. Master key derived from user passphrase via Argon2id.

---

## A) MVP Definition

### In Scope
- Federal simplified 1040: gross income â†’ AGI â†’ taxable income â†’ tax â†’ credits â†’ refund/owed
- W-2 input (multiple per person), 1099-INT, 1099-DIV, 1099-B
- Standard deduction (MFJ/MFS/Single for 2024)
- Tax bracket computation (2024 rates)
- Child Tax Credit stub (data fields, no computation)
- Withholding reconciliation (federal)
- Two-person household, MFJ and MFS what-if comparison
- Georgia state module stub (income tax brackets, standard deduction)
- Full audit trace on every computed value
- CSV import for W-2 / 1099 data
- Export: JSON return snapshot, PDF audit report stub

### Out of Scope (MVP)
- Amended returns (1040-X), itemized deductions (Schedule A), self-employment (Schedule SE/C), AMT, EITC, education credits, IRA/HSA, foreign income, e-file

---

## B) Architecture

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚                        LOCAL MACHINE                            â”‚
â”‚                                                                 â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚
â”‚  â”‚                   Web UI (Jinja2 + HTMX)                 â”‚   â”‚
â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”‚   â”‚
â”‚  â”‚  â”‚Dashboard â”‚ â”‚  Data    â”‚ â”‚  Return  â”‚ â”‚  Audit &    â”‚  â”‚   â”‚
â”‚  â”‚  â”‚& Summaryâ”‚ â”‚  Entry   â”‚ â”‚  Review  â”‚ â”‚  Explain    â”‚  â”‚   â”‚
â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â”‚   â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚
â”‚                         â”‚ HTTP (localhost only)                  â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚
â”‚  â”‚                  FastAPI Application                      â”‚   â”‚
â”‚  â”‚                                                           â”‚   â”‚
â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚   â”‚
â”‚  â”‚  â”‚  Input       â”‚  â”‚  Calculation â”‚  â”‚  What-If /     â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  Service     â”‚  â”‚  Engine      â”‚  â”‚  Suggestion    â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  (CRUD,CSV)  â”‚  â”‚  (AST Eval)  â”‚  â”‚  Engine        â”‚   â”‚   â”‚
â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚   â”‚
â”‚  â”‚         â”‚                â”‚                   â”‚            â”‚   â”‚
â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚   â”‚
â”‚  â”‚  â”‚              Core Domain Layer                      â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”‚ Taxpayer  â”‚ â”‚ Ledger     â”‚ â”‚ ReturnRun       â”‚  â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”‚ Model     â”‚ â”‚ (inputs)   â”‚ â”‚ (immutable      â”‚  â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”‚           â”‚ â”‚            â”‚ â”‚  snapshots)     â”‚  â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â”‚   â”‚   â”‚
â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”¬â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚   â”‚
â”‚  â”‚                           â”‚                               â”‚   â”‚
â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â–¼â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚   â”‚
â”‚  â”‚  â”‚           Storage Layer (SQLCipher + Files)         â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”   â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”‚ tax_copilot  â”‚  â”‚ rule_packs/â”‚  â”‚attachmentsâ”‚   â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â”‚ .db          â”‚  â”‚ (YAML)     â”‚  â”‚/ (files)  â”‚   â”‚   â”‚   â”‚
â”‚  â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚   â”‚   â”‚
â”‚  â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚   â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜   â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

### Component Boundaries

| Component | Responsibility | Boundary |
|-----------|---------------|----------|
| **Web UI** | Rendering, user interaction, HTMX partial updates | No business logic |
| **Input Service** | CRUD for taxpayers, income records, deductions, CSV import | Validates schema, not tax rules |
| **Calculation Engine** | Loads rule pack, evaluates AST, produces traced results | Pure function: (inputs, rules) â†’ (outputs, trace). No DB writes. |
| **What-If Engine** | Runs calc engine N times with varied elections, ranks results | Orchestration only |
| **Suggestion Engine** | Pattern matching on inputs â†’ eligible suggestions | Read-only, never mutates |
| **Core Domain** | Data models, ledger, return runs | Owns schema, immutability contracts |
| **Storage** | SQLCipher DB, file storage for attachments & rule packs | Encryption, backup/restore |

---

## C) Data Model

### Entity Relationship (simplified)

```
Household 1â”€â”€* Taxpayer
Taxpayer  1â”€â”€* IncomeRecord
Taxpayer  1â”€â”€* DeductionRecord
Taxpayer  1â”€â”€* WithholdingRecord
Taxpayer  1â”€â”€* StateResidency

Household 1â”€â”€* TaxYear
TaxYear   1â”€â”€* ReturnRun
ReturnRun 1â”€â”€1 InputSnapshot    (JSON blob, immutable)
ReturnRun 1â”€â”€1 RulePackSnapshot (hash + version, immutable)
ReturnRun 1â”€â”€* CalculationNode  (the trace tree)
ReturnRun 1â”€â”€1 ReturnOutput     (final numbers)
```

### Key Tables

```sql
-- Core entities
CREATE TABLE household (
    id TEXT PRIMARY KEY,  -- UUID
    name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE taxpayer (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL REFERENCES household(id),
    role TEXT NOT NULL CHECK (role IN ('primary', 'spouse')),
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    ssn_encrypted BLOB,          -- encrypted at app level
    date_of_birth TEXT,
    is_active_duty_military BOOLEAN DEFAULT FALSE,
    military_branch TEXT,
    domicile_state TEXT,          -- legal domicile (may differ from physical)
    scra_eligible BOOLEAN DEFAULT FALSE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE tax_year (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL REFERENCES household(id),
    year INTEGER NOT NULL,
    filing_status TEXT NOT NULL CHECK (filing_status IN
        ('single','mfj','mfs','hoh','qss')),
    created_at TEXT NOT NULL,
    UNIQUE(household_id, year)
);

CREATE TABLE income_record (
    id TEXT PRIMARY KEY,
    taxpayer_id TEXT NOT NULL REFERENCES taxpayer(id),
    tax_year_id TEXT NOT NULL REFERENCES tax_year(id),
    form_type TEXT NOT NULL,      -- 'W2', '1099-INT', '1099-DIV', '1099-B'
    source_name TEXT NOT NULL,    -- employer/payer name
    data_json TEXT NOT NULL,      -- form-specific fields as JSON
    attachment_ids TEXT,           -- comma-separated attachment IDs
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE withholding_record (
    id TEXT PRIMARY KEY,
    taxpayer_id TEXT NOT NULL REFERENCES taxpayer(id),
    tax_year_id TEXT NOT NULL REFERENCES tax_year(id),
    source TEXT NOT NULL,         -- 'W2', 'estimated_payment', '1099'
    federal_withheld TEXT NOT NULL,  -- Decimal as string
    state_withheld TEXT,
    state TEXT,
    income_record_id TEXT REFERENCES income_record(id),
    created_at TEXT NOT NULL
);

CREATE TABLE state_residency (
    id TEXT PRIMARY KEY,
    taxpayer_id TEXT NOT NULL REFERENCES taxpayer(id),
    tax_year_id TEXT NOT NULL REFERENCES tax_year(id),
    state TEXT NOT NULL,
    residency_type TEXT NOT NULL CHECK (residency_type IN
        ('domicile','physical','statutory')),
    start_date TEXT,
    end_date TEXT,
    days_present INTEGER,
    notes TEXT
);

-- Immutable run artifacts
CREATE TABLE return_run (
    id TEXT PRIMARY KEY,
    tax_year_id TEXT NOT NULL REFERENCES tax_year(id),
    scenario_name TEXT NOT NULL DEFAULT 'baseline',
    filing_status TEXT NOT NULL,
    rule_pack_version TEXT NOT NULL,
    rule_pack_checksum TEXT NOT NULL,
    input_snapshot_json TEXT NOT NULL,   -- frozen copy of all inputs
    output_json TEXT NOT NULL,           -- final return numbers
    trace_json TEXT NOT NULL,            -- full calculation trace
    total_federal_tax TEXT NOT NULL,     -- Decimal string
    total_state_tax TEXT NOT NULL,
    total_refund_or_owed TEXT NOT NULL,
    conservatism_level TEXT NOT NULL CHECK (conservatism_level IN
        ('conservative','balanced','exploratory')),
    created_at TEXT NOT NULL,
    notes TEXT
);

CREATE TABLE attachment (
    id TEXT PRIMARY KEY,
    household_id TEXT NOT NULL REFERENCES household(id),
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_path TEXT NOT NULL,       -- relative path in attachments/
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL
);
```

### Immutability Strategy
- `return_run` rows are **INSERT-only**. No UPDATE/DELETE.
- `input_snapshot_json` is a deep copy at run time â€” input changes don't affect past runs.
- Rule pack checksum ensures reproducibility: same inputs + same rules = same output.
- Soft deletes on mutable tables (`income_record`, etc.) via `deleted_at` column.

---

## D) Rule Pack Design

### File Structure

```
rule_packs/
â”œâ”€â”€ federal/
â”‚   â””â”€â”€ 2024/
â”‚       â”œâ”€â”€ manifest.yaml          # version, checksum, changelog
â”‚       â”œâ”€â”€ constants.yaml         # standard deduction, exemption amounts
â”‚       â”œâ”€â”€ filing_status.yaml     # rules for status determination
â”‚       â”œâ”€â”€ income.yaml            # gross income computation
â”‚       â”œâ”€â”€ agi.yaml               # adjustments to income
â”‚       â”œâ”€â”€ deductions.yaml        # standard/itemized
â”‚       â”œâ”€â”€ taxable_income.yaml    # AGI - deductions
â”‚       â”œâ”€â”€ tax_brackets.yaml      # progressive bracket tables
â”‚       â”œâ”€â”€ credits.yaml           # CTC, etc.
â”‚       â””â”€â”€ withholding.yaml       # refund/owed computation
â””â”€â”€ state/
    â””â”€â”€ GA/
        â””â”€â”€ 2024/
            â”œâ”€â”€ manifest.yaml
            â”œâ”€â”€ constants.yaml
            â””â”€â”€ income_tax.yaml
```

### Manifest Example

```yaml
# rule_packs/federal/2024/manifest.yaml
pack_id: "federal-2024"
version: "1.0.0"
tax_year: 2024
jurisdiction: "federal"
checksum_sha256: "a1b2c3..."  # computed over all rule files
changelog:
  - version: "1.0.0"
    date: "2025-01-15"
    notes: "Initial 2024 federal rules"
```

### Rule Example: Tax Brackets

```yaml
# rule_packs/federal/2024/tax_brackets.yaml
rules:
  - id: "fed.2024.tax.brackets"
    description: "2024 Federal income tax brackets"
    applies_to:
      filing_status: ["single", "mfj", "mfs"]
    type: "bracket_table"
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0    # round to whole dollars
    tables:
      mfj:
        - { lower: 0,       upper: 23200,   rate: "0.10" }
        - { lower: 23200,   upper: 94300,   rate: "0.12" }
        - { lower: 94300,   upper: 201050,  rate: "0.22" }
        - { lower: 201050,  upper: 383900,  rate: "0.24" }
        - { lower: 383900,  upper: 487450,  rate: "0.32" }
        - { lower: 487450,  upper: 731200,  rate: "0.35" }
        - { lower: 731200,  upper: null,    rate: "0.37" }
      single:
        - { lower: 0,       upper: 11600,   rate: "0.10" }
        - { lower: 11600,   upper: 47150,   rate: "0.12" }
        - { lower: 47150,   upper: 100525,  rate: "0.22" }
        - { lower: 100525,  upper: 191950,  rate: "0.24" }
        - { lower: 191950,  upper: 243725,  rate: "0.32" }
        - { lower: 243725,  upper: 609350,  rate: "0.35" }
        - { lower: 609350,  upper: null,    rate: "0.37" }
      mfs:
        - { lower: 0,       upper: 11600,   rate: "0.10" }
        - { lower: 11600,   upper: 47150,   rate: "0.12" }
        - { lower: 47150,   upper: 100525,  rate: "0.22" }
        - { lower: 100525,  upper: 191950,  rate: "0.24" }
        - { lower: 191950,  upper: 243725,  rate: "0.32" }
        - { lower: 243725,  upper: 365600,  rate: "0.35" }
        - { lower: 365600,  upper: null,    rate: "0.37" }

  - id: "fed.2024.standard_deduction"
    description: "2024 Standard deduction amounts"
    type: "lookup"
    values:
      single: "14600"
      mfj: "29200"
      mfs: "14600"
      hoh: "21900"

  - id: "fed.2024.taxable_income"
    description: "Taxable income = AGI - deduction"
    type: "formula"
    expression: "max(agi - standard_deduction, 0)"
    inputs:
      agi: { ref: "fed.2024.agi.total" }
      standard_deduction: { ref: "fed.2024.standard_deduction", key: "filing_status" }
    rounding: "ROUND_HALF_UP"
    rounding_precision: 0
```

---

## E) Calculation Engine

### Evaluation Plan

1. **Load** rule pack YAML â†’ parse into internal `RuleNode` AST.
2. **Resolve** dependencies: rules reference other rules â†’ build DAG.
3. **Topological sort** â†’ evaluate in dependency order.
4. **Each evaluation** produces a `TraceNode`:

```json
{
  "node_id": "fed.2024.tax.brackets",
  "rule_id": "fed.2024.tax.brackets",
  "rule_pack_version": "1.0.0",
  "description": "2024 Federal income tax brackets",
  "inputs": {
    "taxable_income": {
      "value": "85000.00",
      "source": "fed.2024.taxable_income"
    },
    "filing_status": {
      "value": "mfj",
      "source": "user_input"
    }
  },
  "intermediates": [
    { "bracket": "10%", "range": "0â€“23200", "tax": "2320.00" },
    { "bracket": "12%", "range": "23200â€“85000", "tax": "7416.00" }
  ],
  "result": {
    "value": "9736.00",
    "units": "USD",
    "rounding": "ROUND_HALF_UP",
    "precision": 0
  },
  "explanation": "Tax on $85,000 MFJ: 10% on first $23,200 = $2,320 + 12% on remaining $61,800 = $7,416. Total = $9,736."
}
```

### Numeric Strategy
- All monetary values: `decimal.Decimal` with string serialization.
- Rounding applied per-rule as specified in rule YAML.
- No floats anywhere in the calculation path.
- Cent-level precision maintained; final values rounded per IRS convention (whole dollars on return).

### Sandboxing
- The expression evaluator supports only: `+`, `-`, `*`, `/`, `min`, `max`, `round`, `if/else`, `lookup`, `bracket_calc`, `sum`, `ref`.
- No `eval()`, no `exec()`, no imports. AST nodes are a closed enum.

---

## F) UI/UX Plan

### Screens

| Screen | Purpose |
|--------|---------|
| **Setup** | Create household, add taxpayers, set tax year & filing status |
| **Income Entry** | Add W-2s, 1099s per person. CSV import. |
| **Withholding** | Auto-populated from W-2s, manual adjustments |
| **Review & Calculate** | Run calculation, see summary: income â†’ AGI â†’ tax â†’ refund |
| **What-If Comparison** | Side-by-side: MFJ vs MFS, standard vs itemized |
| **Explain This Number** | Click any value â†’ trace tree with rule IDs, inputs, intermediates |
| **Audit Report** | Export full ReturnRun as JSON or formatted PDF |
| **Settings** | Backup/restore, change passphrase, manage rule packs |

### "Explain This Number" View
Every computed value in the UI is a clickable link. Clicking opens a panel showing:
- Rule ID and description
- All input values with their sources
- Step-by-step intermediate calculations
- Final value with rounding info
- Link to the YAML rule definition

---

## G) Security & Privacy Plan

| Concern | Approach |
|---------|----------|
| **Encryption at rest** | SQLCipher (AES-256-CBC). DB file unreadable without key. |
| **Key derivation** | Argon2id from user passphrase. Salt stored in a separate `.salt` file. |
| **SSN handling** | Encrypted at application level (Fernet) before DB storage. Displayed masked (XXX-XX-1234) in UI. |
| **Local auth** | Passphrase required on app start. Session timeout after 15 min inactivity. |
| **No network** | App binds to `127.0.0.1` only. No outbound calls. |
| **Backup** | Encrypted `.db` file + `rule_packs/` + `attachments/` â†’ single encrypted ZIP. |
| **Threat model** | Primary threat: local device compromise. Mitigations: encryption at rest, passphrase, session timeout. Not designed to resist nation-state actors with physical access + unlimited time. |

---

## H) Development Plan

### Milestones

| # | Milestone | Deliverable |
|---|-----------|-------------|
| 1 | **Vertical Slice** | Single taxpayer, W-2 input, federal bracket calc, trace output, web UI showing result + explanation |
| 2 | **Full MVP Input** | Two taxpayers, all MVP income types, CSV import, withholding |
| 3 | **What-If Engine** | MFJ vs MFS comparison, scenario ranking |
| 4 | **State Module** | Georgia income tax stub |
| 5 | **Audit & Export** | Full ReturnRun persistence, JSON/PDF export, diff between runs |
| 6 | **Security Hardening** | SQLCipher, Argon2, session management, backup/restore |
| 7 | **Suggestion Engine** | Filing status suggestions, deduction completeness checks |

### First Vertical Slice (Milestone 1)
- Single taxpayer enters one W-2
- App computes: gross income â†’ standard deduction â†’ taxable income â†’ bracket tax â†’ withholding â†’ refund/owed
- Full trace JSON stored and viewable in UI
- Rule pack: `federal/2024/` with brackets and standard deduction

---

## I) Risks & Mitigations

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Rule incorrectness** | High | Golden return tests: known inputs â†’ known outputs from IRS publications. Checksummed rule packs. |
| **State tax variability** | Medium | Each state is a separate rule pack. Only model states you need. Start with GA. |
| **Tax law updates** | Medium | Versioned rule packs. New year = new pack. Old packs frozen. |
| **Rounding edge cases** | Medium | Explicit rounding policy per rule. Golden tests include rounding scenarios. |
| **Audit exposure** | Low | App doesn't file â€” it computes and explains. User reviews before using numbers. Disclaimer on every output. |
| **Scope creep** | Medium | Strict MVP. Each new form/schedule is a separate milestone. |
