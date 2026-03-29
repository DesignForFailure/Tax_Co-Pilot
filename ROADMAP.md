<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Roadmap

> **[← Back to README](README.md)** | **Roadmap** · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

This roadmap reflects the near-term plan for evolving Tax_Co-Pilot from MVP/alpha toward a broader and more stable release.

## Current Stage

**Status:** MVP / alpha (current SemVer line: `0.1.x`)  
**Focus:** Prove correctness, reproducibility, and auditability of core architecture.

---

## Near-Term Milestones

## 1) Federal Completeness (MVP hardening)

**Goal:** Expand the federal engine from simplified 1040-style coverage toward broader real-world household scenarios.

- Expand federal rule coverage for additional common income and adjustment categories.
- Improve edge-case handling, trace clarity, and deterministic rounding consistency.
- Add test vectors to reduce regression risk as rule pack complexity grows.
- Improve explainability output so each computed value is easier to audit.

## 2) State Expansion

**Goal:** Move from a single state stub to multi-state practical support.

- Add additional state rule pack scaffolds beyond GA.
- Define a repeatable onboarding pattern for new state modules.
- Improve multi-state household handling and state residency modeling.
- Introduce state-specific regression suites and validation fixtures.

## 3) Forms Support

**Goal:** Map calculated outputs to form-oriented workflows.

- Build form data models for key federal and state filing artifacts.
- Add export-ready structures for draft review and downstream tooling.
- Improve input capture coverage for form-required fields.
- Introduce consistency checks between calculated outputs and form mappings.

## 4) Security Hardening

**Goal:** Raise confidence in local-first data protection and operational safety.

- ~~Implement encryption at rest for the local database.~~ *(Done — SQLCipher AES-256 with Fernet fallback, PBKDF2 key derivation.)*
- ~~Add CI pipeline with automated linting, type checking, and testing.~~ *(Done — GitHub Actions with ruff, mypy, pytest, pip-audit.)*
- Harden key-management workflow and rotation procedures.
- Strengthen audit logging and trace tamper-evidence characteristics.
- Add dependency review and secure configuration baselines.
- Introduce targeted security tests and threat-model updates.

---

## Growth Milestones

## ~~5) Full Income Form UI and Spouse Support~~

~~**Goal:** Transform the calculate form from a single-W2/single-1099-B hardcoded layout into a dynamic, multi-form interface that exposes the full breadth of the existing domain models.~~

- ~~Add dynamic add/remove W-2 rows (HTMX or vanilla JS) with all relevant fields: employer name, wages (Box 1), federal withheld (Box 2), state (Box 15), state wages (Box 16), state withheld (Box 17). Use indexed form field names (e.g. `p_w2[0].wages`, `p_w2[1].wages`).~~
- ~~Add 1099-INT input section with dynamic rows: payer name, interest income, federal withheld. Models already exist in `app/models/domain.py` (`Form1099INTData`).~~
- ~~Add 1099-DIV input section with dynamic rows: payer name, ordinary dividends, qualified dividends, federal withheld. Models already exist in `app/models/domain.py` (`Form1099DIVData`).~~
- ~~Expand the 1099-B section to support multiple entries with add/remove, and expose the `is_long_term` boolean as a checkbox (field exists in model but not in UI).~~
- ~~Add a Spouse section that appears when filing status is MFJ or MFS. Spouse gets their own name fields and income form blocks (W-2s, 1099s). Backend constructs a second `Taxpayer` with `role=SPOUSE`.~~
- ~~Add Head of Household (HOH) and Qualifying Surviving Spouse (QSS) to the filing status dropdown. The `FilingStatus` enum and standard deduction constants already include these; bracket tables need to be added to the federal rules YAML.~~
- ~~Refactor form parsing in `main.py` `calculate_submit` from flat `Form(...)` parameters to structured indexed parsing. Extract into a helper like `_parse_tax_input_from_form(form_data) -> TaxReturnInput`.~~

## 6) Wire Existing Backend Features to UI

**Goal:** Expose the what-if scenario engine, CSV import service, and audit export service through UI routes and navigation — all of which exist as working backend code today.

- Add a What-If comparison page (`GET /whatif`, `POST /whatif`) that uses `WhatIfEngine` from `app/engine/whatif.py` to compare filing statuses (e.g. MFJ vs MFS). Render a template showing the `ScenarioComparison` model: diffs table, recommendation, and savings amount. Add a nav link.
- Add a CSV import page (`GET /import-csv`, `POST /import-csv`) with file upload and record-type selector (W-2, 1099-B). Use `import_csv()` from `app/services/csv_import.py`. Show results and errors. Extend `csv_import.py` to also support 1099-INT and 1099-DIV record types.
- Add audit export download buttons on the run detail page. Add `GET /runs/{run_id}/export/json` and `GET /runs/{run_id}/export/html` routes using `export_json()` and `generate_audit_html()` from `app/services/audit_export.py`. Return as downloadable file attachments.
- Add a run deletion endpoint (`POST /runs/{run_id}/delete`) with CSRF protection. Add `delete_return_run(run_id)` to `app/services/database.py`. Add a delete button on the runs list page.
- Add a run comparison view (`GET /runs/compare?a={id}&b={id}`) that loads two `ReturnRun` objects and renders a side-by-side diff of their outputs and traces. Add checkboxes on the runs list page to select two runs for comparison.

## 7) Above-the-Line Deductions and AGI Adjustments

**Goal:** Make AGI actually adjusted rather than equaling gross income. Add the most common above-the-line deductions so that downstream calculations (taxable income, credits, state AGI) are correct.

- Add a new `AdjustmentsData` model to `app/models/domain.py` with fields: `student_loan_interest`, `ira_contributions`, `hsa_contributions`, `educator_expenses`, `self_employment_tax_deduction` (all `Decimal`). Add to `TaxReturnInput` and add a `total_adjustments()` method.
- Add adjustment limit constants to `rule_packs/federal/2024/federal_2024_rules.yaml`: student loan interest max ($2,500), educator expenses max ($300), HSA limits ($4,150 single / $8,300 family), IRA contribution limits ($7,000 / $8,000 for age 50+).
- Add new rules: `fed.2024.adjustments.student_loan_interest`, `fed.2024.adjustments.ira`, `fed.2024.adjustments.hsa`, `fed.2024.adjustments.total` using `sum` and `formula` types with `min()` capping. Update `fed.2024.agi.total` expression from `"gross"` to `"gross - adjustments"`.
- Extend `app/engine/calculator.py` `_resolve_inputs()` to resolve the new adjustment input values into the namespace.
- Add an "Above-the-Line Deductions" card to the calculate form with fields for each adjustment type.
- Add test vectors with known IRS scenarios that verify AGI is correctly reduced and phaseout limits are enforced.

## 8) Itemized Deductions and Credits

**Goal:** Add the itemized deduction path and key tax credits so the engine handles the majority of real-world return scenarios.

- Add `ItemizedDeductionData` model to `app/models/domain.py` with fields: `mortgage_interest`, `state_and_local_taxes`, `real_estate_taxes`, `charitable_cash`, `charitable_noncash`, `medical_expenses`.
- Add itemized deduction rules to the federal rules YAML: SALT cap ($10,000 / $5,000 MFS) via `min()`, medical expenses above 7.5% AGI floor, charitable contributions with 60% AGI cap on cash, and `fed.2024.itemized.total` summing all categories.
- Add `fed.2024.deduction.applied` rule as `max(standard_deduction, itemized_total)`. Update `fed.2024.taxable_income` to reference the applied deduction instead of the standard deduction directly.
- Add child tax credit rules: $2,000 per qualifying child, phaseout at $200K single / $400K MFJ ($50 per $1,000 over threshold). Add `number_of_qualifying_children` to the input model.
- Add earned income credit rules with bracket-style phaseout ranges by filing status and number of qualifying children.
- Extend `ReturnOutput` in `app/models/domain.py` to include `deduction_type` (standard vs itemized), `deduction_amount`, `child_tax_credit`, `earned_income_credit`, `total_credits`. Update `federal_tax` to be post-credits. Update dashboard template.

## 9) Multi-Year Support

**Goal:** Support tax years 2023 and 2024 concurrently, with a year selector in the UI and year-over-year comparison.

- Create `rule_packs/federal/2023/` with manifest and rules YAML. Same structure as 2024 with different numeric constants (2023 standard deduction: $13,850 single / $27,700 MFJ; different bracket thresholds).
- Make the rule pack loader year-aware. Replace the hardcoded `RULE_PACK_DIR = BASE_DIR / "rule_packs" / "federal" / "2024"` in `main.py` with a `load_rule_pack(year: int)` function that resolves paths dynamically and caches loaded packs by year.
- Change the tax year field in the calculate form from `readonly` to a dropdown populated with available years (discovered by scanning `rule_packs/federal/` at startup).
- Update `calculate_submit` to use the submitted `tax_year` to select the correct rule pack.
- Add a year-over-year comparison view that lets users select runs from different tax years for side-by-side comparison.
- Create `rule_packs/state/GA/2023/` to validate multi-year works for states.

## 10) State Tax Expansion

**Goal:** Add high-population states, wire the existing GA stub to the UI, and create a documented onboarding template so contributors can add new states easily.

- Wire GA to the UI: add a "State of Residence" dropdown to the calculate form. When a state is selected, pass the corresponding state rule pack to `CalculationEngine`. Display `StateReturnOutput` on the dashboard below the federal summary.
- Generalize state output extraction in `app/engine/calculator.py` `_run_states()`. Replace GA-specific hardcoded key lookups with dynamic extraction by convention: `{state_code}.{year}.agi`, `{state_code}.{year}.taxable_income`, etc.
- Create California rule pack (`rule_packs/state/CA/2024/`): 9 progressive brackets (1%–12.3%), CA standard deduction ($5,363 single / $10,726 MFJ), mental health services tax (1% on income over $1M).
- Create New York rule pack (`rule_packs/state/NY/2024/`): 8 progressive brackets (4%–10.9%), NY standard deduction ($8,000 single / $16,050 MFJ).
- Create no-income-tax stubs for TX, FL, WA, NV, WY, SD, AK, NH, TN — minimal one-rule packs that return $0 state tax.
- Write a state onboarding guide (`docs/STATE_AUTHORING_GUIDE.md`) documenting: directory conventions, manifest requirements, required rule IDs, cross-pack federal AGI references, bracket table format, and testing patterns. Include a template directory at `rule_packs/state/_template/`.

## 11) Data Management and Developer Experience

**Goal:** Add data portability, backup/restore, and developer tooling to support growing rule pack contributions and user data management.

- Add full return data export/import: `GET /export-all` dumps all `return_runs` to a JSON file; `POST /import-returns` accepts a JSON file and inserts runs with checksum verification.
- Add database backup/restore: `GET /backup` returns a copy of the SQLite file as a download; `POST /restore` accepts a database file upload and replaces the current database (with confirmation prompt). Handle encrypted databases appropriately.
- Create a rule pack validation CLI at `scripts/validate_rule_pack.py` that wraps `RulePack.load()` with argparse and error formatting. Allows contributors to validate packs without running the full application.
- Write a rule pack authoring guide at `docs/RULE_PACK_AUTHORING.md` documenting: the four rule types (sum, formula, lookup, bracket_table), the expression mini-language, the constant system, namespace conventions, and worked examples.
- Add GitHub issue and PR templates (`.github/ISSUE_TEMPLATE/new_state.md`, `.github/PULL_REQUEST_TEMPLATE.md`) with checklists for new state contributions.
- Add run tagging and notes: optional `tags` and `notes` fields on `ReturnRun` and the database schema so users can annotate runs (e.g. "final version", "before IRA contribution").

---

## Milestone Dependency Order

```
5 (UI forms) ──► 6 (wire backend features)
                    │
                    ▼
                 7 (AGI adjustments)
                    │
              ┌─────┼─────┐
              ▼     ▼     ▼
           8 (deductions  9 (multi-year)
              + credits)
              │           │
              └─────┬─────┘
                    ▼
                10 (state expansion)
                    │
                    ▼
                11 (data mgmt + DX)
```

- **5 must come first** because every subsequent milestone adds UI form elements.
- **7 must precede 8** because itemized deductions and credits depend on correct AGI.
- **9 and 10 can run in parallel** once 7 is stable.
- **11 is largely independent** but becomes most valuable after 8–10.

---

## Implementation Prompts for AI Coding Agents

Below are copy-paste-ready prompts for AI coding agents to implement each milestone. Each prompt is self-contained with the necessary context, file paths, and acceptance criteria.

---

### ~~Prompt: Milestone 5 — Full Income Form UI and Spouse Support~~

```
~~You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application.~~

~~TASK: Overhaul the tax calculation input form to support all income types the
backend already handles, and add spouse support.~~

~~CURRENT STATE:~~
- ~~The calculate form at `app/templates/pages/calculate.html` only captures a
  single W-2 (employer, wages, withheld) and a single 1099-B (description,
  proceeds, basis).~~
- ~~The domain models in `app/models/domain.py` already support: multiple W-2s
  (with state fields Box 15-17), Form1099INTData, Form1099DIVData, multiple
  Form1099BData (with is_long_term), and a Taxpayer model with spouse role.~~
- ~~The form parser in `main.py` `calculate_submit` (line ~276) uses flat
  Form(...) parameters for a single W-2 and single 1099-B.~~

~~WHAT TO BUILD:~~

1. ~~In `app/templates/pages/calculate.html`:~~
   - ~~Add dynamic add/remove rows for W-2s using vanilla JS or HTMX. Each W-2
     row needs: employer_name, wages, federal_withheld, state, state_wages,
     state_withheld. Use indexed names like `p_w2_0_wages`, `p_w2_1_wages`.~~
   - ~~Add a 1099-INT section with dynamic rows: payer_name, interest_income,
     federal_withheld.~~
   - ~~Add a 1099-DIV section with dynamic rows: payer_name, ordinary_dividends,
     qualified_dividends, federal_withheld.~~
   - ~~Make 1099-B support multiple entries with add/remove and an is_long_term
     checkbox.~~
   - ~~Add a Spouse section that shows/hides based on filing status (MFJ/MFS).
     Spouse gets the same income form blocks as primary.~~
   - ~~Add "hoh" (Head of Household) and "qss" (Qualifying Surviving Spouse) to
     the filing status <select>.~~

~~2. In `main.py` `calculate_submit`:~~
   - ~~Replace flat Form(...) params with parsing `await request.form()` to
     extract indexed fields into lists of domain model objects.~~
   - ~~Extract this logic into a helper: `_parse_tax_input_from_form(form_data)
     -> TaxReturnInput`.~~
   - ~~Build the Taxpayer list with primary + optional spouse, each with their
     own W-2, 1099-INT, 1099-DIV, and 1099-B lists.~~

~~3. In `rule_packs/federal/2024/federal_2024_rules.yaml`:~~
   - ~~Add HOH and QSS bracket tables under `fed.2024.tax.brackets.tables`
     (currently only single, mfj, mfs exist). Use 2024 IRS bracket thresholds
     for HOH and QSS.~~

~~ACCEPTANCE CRITERIA:~~
- ~~A user can add multiple W-2s with state fields and remove them dynamically.~~
- ~~A user can add 1099-INT, 1099-DIV, and multiple 1099-B entries.~~
- ~~Selecting MFJ or MFS reveals a spouse section with its own income forms.~~
- ~~HOH and QSS are selectable filing statuses and produce correct calculations.~~
- ~~All existing tests continue to pass.~~
- ~~The form gracefully handles the case of zero income entries (empty form).~~
```

---

### Prompt: Milestone 6 — Wire Existing Backend Features to UI

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application.

TASK: Expose three existing backend services (what-if engine, CSV import, audit
export) through UI routes and templates. Also add run deletion and run comparison.

EXISTING BACKEND CODE (already implemented and tested):
- `app/engine/whatif.py`: WhatIfEngine.compare_filing_status(input) returns a
  ScenarioComparison with scenario_a, scenario_b, diffs, recommendation, savings.
- `app/services/csv_import.py`: import_csv(csv_text, record_type) returns
  (records, errors). Supports "W2" and "1099-B" record types.
- `app/services/audit_export.py`: export_json(run, path) and
  generate_audit_html(run) produce export artifacts.
- `app/services/database.py`: has list_return_runs() and get_return_run(id).

WHAT TO BUILD:

1. What-If Comparison Page:
   - GET /whatif: render a form where users enter tax data (reuse the calculate
     form pattern) and select two filing statuses to compare.
   - POST /whatif: run WhatIfEngine.compare_filing_status(), render results
     showing both scenarios side-by-side with diffs and savings.
   - Add a "What-If" link to the nav in `app/templates/layouts/base.html`.

2. CSV Import Page:
   - GET /import-csv: render a form with a textarea (paste CSV) or file upload,
     and a record-type dropdown (W-2, 1099-B, 1099-INT, 1099-DIV).
   - POST /import-csv: parse with import_csv(), display results and errors,
     let user proceed to calculate with the imported data.
   - Extend csv_import.py to support "1099-INT" and "1099-DIV" record types
     following the existing W2/1099-B patterns.

3. Audit Export Buttons:
   - GET /runs/{run_id}/export/json: return the run as a downloadable JSON file.
   - GET /runs/{run_id}/export/html: return the audit HTML as a downloadable file.
   - Add "Export JSON" and "Export HTML" buttons on the run detail page
     (dashboard.html when viewing a specific run).

4. Run Deletion:
   - Add delete_return_run(run_id) to app/services/database.py.
   - POST /runs/{run_id}/delete with CSRF protection.
   - Add a delete button (with confirmation) on the runs list page (runs.html).

5. Run Comparison:
   - GET /runs/compare?a={id}&b={id}: load two ReturnRun objects and render a
     side-by-side comparison template showing output diffs and trace differences.
   - Add checkboxes on the runs list page to select two runs for comparison.

ACCEPTANCE CRITERIA:
- What-if page shows clear MFJ vs MFS comparison with savings amount.
- CSV import successfully parses W-2 and 1099-B CSVs and shows per-line errors.
- Export buttons produce valid downloadable JSON and HTML files.
- Run deletion removes the run from the database and redirects to runs list.
- Run comparison shows meaningful side-by-side output diffs.
- All existing tests pass. Add new tests for the new routes.
```

---

### Prompt: Milestone 7 — Above-the-Line Deductions and AGI Adjustments

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application
with YAML-based rule packs and a deterministic calculation engine.

TASK: Add above-the-line deductions so AGI is properly adjusted. Currently AGI
equals gross income (the rule `fed.2024.agi.total` has expression: "gross").

WHAT TO BUILD:

1. In `app/models/domain.py`:
   - Add an AdjustmentsData model with Decimal fields: student_loan_interest,
     ira_contributions, hsa_contributions, educator_expenses,
     self_employment_tax_deduction.
   - Add an `adjustments: AdjustmentsData` field to TaxReturnInput (with a
     default factory).
   - Add a total_adjustments() method to TaxReturnInput that sums all fields.

2. In `rule_packs/federal/2024/federal_2024_rules.yaml`:
   - Add constants for limits:
     - student_loan_interest_max: "2500"
     - educator_expenses_max: "300"
     - hsa_limit: { single: "4150", mfj: "8300", mfs: "4150", hoh: "4150",
       qss: "8300" }
     - ira_limit: "7000"
   - Add rules:
     - fed.2024.adjustments.student_loan (formula: min(input, 2500))
     - fed.2024.adjustments.educator (formula: min(input, 300))
     - fed.2024.adjustments.hsa (formula: min(input, limit) using lookup)
     - fed.2024.adjustments.ira (formula: min(input, 7000))
     - fed.2024.adjustments.total (sum of all adjustment rules)
   - Update fed.2024.agi.total: change expression from "gross" to
     "max(gross - adj, 0)" with adj referencing fed.2024.adjustments.total.

3. In `app/engine/calculator.py`:
   - In _resolve_inputs(), add resolution for:
     - input.adjustments.student_loan_interest
     - input.adjustments.ira_contributions
     - input.adjustments.hsa_contributions
     - input.adjustments.educator_expenses
     - input.adjustments.self_employment_tax_deduction

4. In `app/templates/pages/calculate.html`:
   - Add an "Above-the-Line Deductions" card with numeric input fields for
     each adjustment type. These are simple single-value fields (no dynamic rows).

5. In `main.py`:
   - Parse the new adjustment form fields and populate AdjustmentsData on
     TaxReturnInput.

6. Add test vectors in `tests/`:
   - Test that AGI is reduced by student loan interest (capped at $2,500).
   - Test that AGI is reduced by educator expenses (capped at $300).
   - Test with zero adjustments (AGI = gross income, backward compatible).
   - Test with adjustments exceeding limits (caps enforced).

ACCEPTANCE CRITERIA:
- AGI is correctly reduced by the sum of applicable adjustments.
- Each adjustment respects its IRS-defined cap.
- Zero adjustments produce the same result as before (backward compatible).
- All existing golden tests continue to pass unchanged.
```

---

### Prompt: Milestone 8 — Itemized Deductions and Credits

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application
with YAML-based rule packs. AGI adjustments from Milestone 7 must already be
implemented before starting this milestone.

TASK: Add itemized deductions (with standard-vs-itemized comparison) and key
tax credits (child tax credit, earned income credit).

WHAT TO BUILD:

1. Itemized Deductions:
   - Add ItemizedDeductionData model to domain.py: mortgage_interest,
     state_and_local_taxes, real_estate_taxes, charitable_cash,
     charitable_noncash, medical_expenses (all Decimal).
   - Add to TaxReturnInput as optional itemized_deductions field.
   - Add rules to federal_2024_rules.yaml:
     - fed.2024.itemized.salt: sum(state_and_local_taxes + real_estate_taxes),
       capped at min(total, 10000) for most statuses or 5000 for MFS.
     - fed.2024.itemized.medical: max(medical - 0.075 * agi, 0)
     - fed.2024.itemized.charitable: sum(cash + noncash), cash capped at
       0.60 * agi.
     - fed.2024.itemized.total: sum of all itemized categories.
     - fed.2024.deduction.applied: max(standard_deduction, itemized_total).
   - Update fed.2024.taxable_income to use fed.2024.deduction.applied instead
     of fed.2024.standard_deduction.

2. Child Tax Credit:
   - Add number_of_qualifying_children (int) to TaxReturnInput.
   - Add rules:
     - fed.2024.credits.ctc.base: children * 2000
     - fed.2024.credits.ctc.phaseout: max(0, (agi - threshold) / 1000) * 50
       where threshold is 200000 single / 400000 MFJ.
     - fed.2024.credits.ctc.final: max(base - phaseout, 0)

3. Earned Income Credit:
   - Add EIC tables as bracket-style constants in the rules YAML for 0, 1, 2,
     and 3+ qualifying children by filing status.
   - Implement using bracket_table or a new conditional rule type if needed.

4. Update ReturnOutput in domain.py:
   - Add fields: deduction_type (str: "standard" or "itemized"),
     deduction_amount, child_tax_credit, earned_income_credit, total_credits.
   - Update federal_tax to be post-credits.
   - Add fed.2024.refund_or_owed to account for: withheld - (tax - credits).

5. Update UI:
   - Add "Itemized Deductions" card to calculate form (collapsible, optional).
   - Add "Dependents" section with qualifying children count.
   - Update dashboard to show deduction type, credits, and post-credit tax.

ACCEPTANCE CRITERIA:
- When itemized > standard, the engine uses itemized (and vice versa).
- SALT is capped at $10K ($5K MFS).
- Medical deduction only applies above 7.5% AGI floor.
- CTC phases out correctly at income thresholds.
- All existing tests pass (standard deduction path unchanged when no itemized).
```

---

### Prompt: Milestone 9 — Multi-Year Support

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application.
Rule packs live in `rule_packs/federal/{year}/` and `rule_packs/state/{STATE}/{year}/`.

TASK: Add support for multiple tax years (2023 + 2024) with dynamic rule pack
loading and a year selector in the UI.

WHAT TO BUILD:

1. Create 2023 federal rule pack at `rule_packs/federal/2023/`:
   - federal_2023_manifest.yaml (tax_year: 2023, version: "1.0.0")
   - federal_2023_rules.yaml with 2023 IRS constants:
     - Standard deduction: $13,850 single, $27,700 MFJ, $13,850 MFS,
       $20,800 HOH, $27,700 QSS.
     - 2023 bracket thresholds (different from 2024).
   - Same rule IDs but with "2023" in the namespace (fed.2023.*).

2. Make rule pack loading dynamic in `main.py`:
   - Replace the hardcoded `RULE_PACK_DIR = BASE_DIR / "rule_packs" / "federal"
     / "2024"` and `rule_pack = RulePack.load(RULE_PACK_DIR)` with:
   - A function that discovers available years by scanning rule_packs/federal/.
   - A cache dict mapping year -> loaded RulePack.
   - Update calculate_submit to select the rule pack matching the submitted
     tax_year.

3. Update the calculate form:
   - Change tax_year from a readonly input to a <select> dropdown populated
     with available years.

4. Create 2023 GA state rule pack at `rule_packs/state/GA/2023/` with 2023
   GA tax constants.

5. Add year-over-year comparison:
   - GET /compare-years: page where user selects two runs from different years
     and sees a side-by-side comparison of outputs.

ACCEPTANCE CRITERIA:
- User can select 2023 or 2024 from the form and get correct calculations.
- 2023 standard deductions and brackets differ from 2024 and are correct.
- The rule pack cache avoids reloading packs on every request.
- All existing 2024 tests pass without modification.
- New tests verify 2023 calculations with known IRS scenarios.
```

---

### Prompt: Milestone 10 — State Tax Expansion

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application.
The engine already supports state calculations — see `app/engine/calculator.py`
`_run_states()` and the existing GA pack at `rule_packs/state/GA/2024/`.

TASK: Wire state tax to the UI, generalize the state engine, add CA and NY
packs, add no-income-tax stubs, and write a state onboarding guide.

WHAT TO BUILD:

1. Wire states to the UI:
   - Add a "State of Residence" dropdown to calculate.html populated with
     available states (scan rule_packs/state/ at startup).
   - In main.py, when a state is selected, load its rule pack and pass it
     as state_packs to CalculationEngine.
   - On the dashboard, display StateReturnOutput below the federal summary
     (state AGI, state taxable income, state tax, state refund/owed).

2. Generalize state output extraction:
   - In calculator.py _run_states(), replace GA-specific hardcoded key lookups
     with dynamic extraction by convention:
     {state_code}.{year}.agi, {state_code}.{year}.standard_deduction,
     {state_code}.{year}.taxable_income, {state_code}.{year}.tax,
     {state_code}.{year}.withholding, {state_code}.{year}.refund_or_owed.

3. Create California rule pack at `rule_packs/state/CA/2024/`:
   - 9 brackets: 1%, 2%, 4%, 6%, 8%, 9.3%, 10.3%, 11.3%, 12.3%.
   - Standard deduction: $5,363 single / $10,726 MFJ.
   - Mental health services tax: 1% on taxable income over $1,000,000.
   - Uses federal AGI as starting point (cross-pack ref to fed.2024.agi.total).

4. Create New York rule pack at `rule_packs/state/NY/2024/`:
   - 8 brackets: 4%, 4.5%, 5.25%, 5.85%, 6.25%, 6.85%, 9.65%, 10.3%, 10.9%.
   - Standard deduction: $8,000 single / $16,050 MFJ.
   - Uses federal AGI as starting point.

5. Create no-income-tax stubs for: TX, FL, WA, NV, WY, SD, AK, NH, TN.
   Each is a minimal rule pack with one rule that outputs $0 state tax.

6. Write `docs/STATE_AUTHORING_GUIDE.md`:
   - Directory convention: rule_packs/state/{STATE_CODE}/{YEAR}/
   - Manifest requirements (jurisdiction, tax_year, version).
   - Required rule ID conventions.
   - How to reference federal AGI (cross-pack dependency).
   - How to structure bracket tables.
   - How to test a new state pack.
   - Include a template at rule_packs/state/_template/.

ACCEPTANCE CRITERIA:
- Selecting GA, CA, or NY in the form produces correct state tax calculations.
- Selecting TX, FL, etc. produces $0 state tax.
- State output appears on the dashboard.
- The state engine works without any state-specific hardcoding in Python.
- The STATE_AUTHORING_GUIDE.md is complete enough for a contributor to add a
  new state by following the guide alone.
```

---

### Prompt: Milestone 11 — Data Management and Developer Experience

```
You are working on Tax_Co-Pilot, a FastAPI + Jinja2 local-first tax application
with SQLite storage (app/services/database.py) and YAML rule packs loaded by
app/engine/rule_loader.py.

TASK: Add data portability (export/import all returns), database backup/restore,
a rule pack validation CLI, authoring docs, and contribution templates.

WHAT TO BUILD:

1. Full return data export/import:
   - GET /export-all: query all return_runs via list_return_runs(), serialize
     as a JSON array, return as a downloadable .json file.
   - POST /import-returns: accept a JSON file upload, validate each entry
     against the ReturnRun model, insert via save_return_run(). Include
     checksum verification. Report success/error counts.

2. Database backup/restore:
   - GET /backup: return a copy of the SQLite database file (DB_PATH from
     database.py) as a downloadable attachment.
   - POST /restore: accept a database file upload. Validate it is a valid
     SQLite database. Replace the current DB file (after confirmation via a
     two-step flow). Re-initialize connections. For encrypted DBs, the backup
     is the encrypted file.

3. Rule pack validation CLI:
   - Create scripts/validate_rule_pack.py with argparse.
   - Accept a directory path argument.
   - Call RulePack.load(path) and catch/format all validation errors.
   - Print success message with pack metadata (version, year, jurisdiction,
     rule count) or detailed error report.
   - Exit code 0 for success, 1 for failure.

4. Rule pack authoring guide at docs/RULE_PACK_AUTHORING.md:
   - Document the four rule types with YAML examples:
     sum, formula, lookup, bracket_table.
   - Document the expression mini-language: +, -, *, /, max(), min(),
     parentheses, variable refs, literals.
   - Document the constant system and how lookups work.
   - Document namespace conventions (fed.{year}.*, {state}.{year}.*).
   - Include a complete worked example of a minimal rule pack.

5. GitHub contribution templates:
   - .github/ISSUE_TEMPLATE/new_state.md: template for requesting a new state.
   - .github/PULL_REQUEST_TEMPLATE.md: checklist including pack validates,
     tests pass, bracket tables sourced from official docs.

6. Run tagging and notes:
   - Add tags (TEXT, nullable) and notes (TEXT, nullable) columns to
     return_runs table in database.py init_db().
   - Add tags and notes fields to ReturnRun model in domain.py.
   - Add a POST /runs/{run_id}/annotate endpoint to update tags/notes.
   - Show tags/notes on the runs list page with inline editing.

ACCEPTANCE CRITERIA:
- Exported JSON can be re-imported and produces identical runs.
- Database backup produces a valid downloadable SQLite file.
- validate_rule_pack.py correctly validates existing packs and reports errors
  for malformed packs.
- The authoring guide is clear enough to write a new rule pack from scratch.
- All existing tests pass. New tests cover export/import round-trip.
```

---

## Versioning & Release Trajectory

- Continue using **Semantic Versioning**.
- Treat `0.y.z` as **alpha** period where breaking changes may happen between minor releases.
- Promote to `1.0.0` once core interfaces, rule pack contracts, and data model stability criteria are met.
