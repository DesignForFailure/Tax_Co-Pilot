<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Hardening, QA & Auditability pass (complete):** Fixed SQL injection in SQLCipher PRAGMA, `tax_year` validation, unary negation in rule expressions, `hybrid_factory` consistency, URL-encoded error redirects, upload size limits with SQLite integrity validation, input sanitization (tags/notes caps, filename sanitization, export fallback). Added tamper-evident hash chain (`integrity_hash`, `previous_hash`) with `GET /audit/verify`. Key rotation via `POST /rotate-key` with `PRAGMA rekey`. Password cache clearing on shutdown. Explicit cipher parameters. CSRF token rotation after authentication. Made `pip-audit` blocking in CI.

### Changed
- Migrated from deprecated `@app.on_event("startup")` to lifespan context manager.
- All DB functions now use `contextlib.closing` for leak-safe connections.

### Added
- **Milestone 11 — Data Management & Developer Experience (complete):** Full return data export/import (`GET /export-all`, `POST /import-returns`), database backup/restore (`GET /backup`, `POST /restore`), run tagging and notes (`POST /runs/{id}/annotate`), rule pack validation CLI (`scripts/validate_rule_pack.py`), rule pack authoring guide (`docs/RULE_PACK_AUTHORING.md`), GitHub issue/PR templates (`.github/ISSUE_TEMPLATE/new_state.md`, `.github/PULL_REQUEST_TEMPLATE.md`).
- `tags` and `notes` fields on `ReturnRun` model with backward-compatible DB migration.
- `update_run_annotation()` in database service for inline tag/note editing.
- Export/import round-trip with checksum verification against loaded federal rule packs.
- Restore endpoint validates SQLite magic bytes before overwriting database.
- Data management tests (`tests/test_data_mgmt.py`): export JSON, backup download, round-trip, annotation, restore rejection.
- **Milestone 10 — State Tax Expansion (complete):** Added California (9 progressive brackets + 1% mental health services surtax) and New York (9 progressive brackets) state rule packs for tax year 2024. Added "State of Residence" dropdown to the calculate form. All state packs (GA, CA, NY, plus 9 no-income-tax stubs) now loadable and tested.
- `state_outputs_json` persistence column in `return_runs` plus backward-compatible migration path in `init_db()`.
- `_load_run_from_row()` hydration helper in `main.py` to consistently decode input/output/trace/state payloads.
- `ItemizedDeductionData` model for Schedule A inputs (medical, SALT, mortgage, charitable).
- `qualifying_children` field on `TaxReturnInput` for Child Tax Credit.
- 15 new federal rules per year: itemized deduction calculation (medical 7.5% AGI floor, SALT $10k cap, charitable 60% AGI cap), deduction election (`max(standard, itemized)`), Child Tax Credit with phaseout, post-credit tax.
- New `ReturnOutput` fields: `itemized_deductions`, `deduction_applied`, `child_tax_credit`, `total_credits`, `tax_before_credits`.
- Itemized Deductions (Schedule A) and Dependents sections on the calculate form.
- `ScheduleALines` form model and Schedule A form line mapping.
- 12 golden tests covering itemized deductions, SALT cap, medical floor, charitable cap, CTC basic/phaseout/combined (`tests/test_itemized_credits.py`).
- 2023 federal rule pack (`rule_packs/federal/2023/`) with IRS bracket tables, standard deductions, and adjustment limits.
- 2023 Georgia state rule pack (`rule_packs/state/GA/2023/`) with graduated bracket system (5.75% top rate).
- Dynamic rule pack loading: discovers available years by scanning `rule_packs/federal/`, caches loaded packs.
- Tax year dropdown on calculate form (was readonly, now selectable).
- `_discover_available_years()`, `_get_federal_pack()`, `_get_state_packs()` helpers in `main.py`.
- 2023 golden tests and trace completeness tests (`tests/test_multi_year.py`).
- Form data models (`Form1040Lines`, `Schedule1Lines`, `FormPacket`) mapping engine outputs to IRS form line items (`app/models/forms.py`).
- Form mapper service (`app/services/form_mapper.py`) with consistency checks between calculated outputs and form lines.
- `form_line` field on `TraceNode` for structured form-line annotation on every trace entry.
- Estimated tax payments input field and rules (`fed.2024.estimated_payments`, `fed.2024.total_payments`).
- Tax-exempt interest field on `Form1099INTData` and qualified dividends helper on `TaxReturnInput`.
- Above-the-line deductions, estimated payments, and other income sections on the calculate form.
- `GET /runs/{id}/forms`: IRS form-oriented view of calculation results (`app/templates/pages/forms_view.html`).
- `GET /runs/{id}/export/forms`: downloadable JSON export of form data.
- "View Forms" button on the dashboard.
- `estimated_tax_payments` and `total_payments` fields on `ReturnOutput`.
- Comprehensive form mapping and consistency check tests (`tests/test_forms.py`).

### Changed
- `MFS` handling is now per-person in `/calculate` (rejects spouse aggregation) and household-aggregated in `WhatIfEngine` by summing separate spouse returns.
- Runtime encryption now requires SQLCipher; Python-layer fallback provider is explicitly disabled to fail closed.
- `/whatif` now supports tax-year selection from discovered years (removed hardcoded 2024 submission).
- Dashboard heading now renders from `run.tax_year` instead of a hardcoded year.
- Run comparison now includes current output fields (`itemized_deductions`, `deduction_applied`, credits, and total payments) and refund delta coloring is corrected.
- Audit HTML export now renders all available state outputs generically instead of hardcoding a single Georgia row.
- README repository tree updated to match current structure (`.agent_tools`, additional state packs, `docs/superpowers`, etc.).
- `fed.{year}.taxable_income` now uses `deductions.applied` (max of standard/itemized) instead of `standard_deduction`.
- `fed.{year}.refund_or_owed` now uses `tax.after_credits` instead of `tax.brackets`.
- `ReturnOutput.federal_tax` now reflects post-credit tax (unchanged when no credits apply).
- Dashboard shows deduction type, tax before/after credits, and CTC amount.
- Form mapper refund/owed calculation uses post-credit tax when credits apply.
- `main.py` rule pack loading: replaced hardcoded 2024 federal/state pack with year-aware dynamic loading and caching.
- Calculate form: tax year field changed from `<input readonly>` to `<select>` dropdown.
- `calculator.py` output mapping: now uses rule pack's `tax_year` for dynamic rule ID prefix instead of hardcoded `fed.2024`.
- `fed.2024.refund_or_owed` now uses total payments (withholding + estimated) instead of withholding alone.

- `GET /whatif`, `POST /whatif`: What-if scenario comparison page using `WhatIfEngine` (MFJ vs MFS); shows diffs table, recommendation, and savings amount.
- `GET /import-csv`, `POST /import-csv`: CSV import page with textarea input and record-type dropdown (W-2, 1099-B, 1099-INT, 1099-DIV); displays per-line parse errors and parsed record table.
- `GET /runs/{run_id}/export/json`, `GET /runs/{run_id}/export/html`: Downloadable audit export endpoints using `generate_audit_html()` from `audit_export.py`.
- `POST /runs/{run_id}/delete`: Run deletion endpoint with CSRF protection; redirects to `/runs` on success.
- `GET /runs/compare?a={id}&b={id}`: Side-by-side run comparison view showing output diffs and delta for all `ReturnOutput` fields.
- `delete_return_run(run_id)` added to `app/services/database.py` (parameterized DELETE, hybrid_factory compatible).
- Extended `app/services/csv_import.py` with `1099-INT` and `1099-DIV` record type support following existing W-2/1099-B patterns.
- Nav links for What-If and Import CSV added to `app/templates/layouts/base.html`.
- Export JSON / Export HTML buttons added to `app/templates/pages/dashboard.html`.
- Delete buttons (with confirmation dialog) and comparison checkboxes added to `app/templates/pages/runs.html`; `past_runs` route now passes CSRF token to the template.
- New templates: `app/templates/pages/whatif.html`, `app/templates/pages/import_csv.html`, `app/templates/pages/run_compare.html`.
- `ReturnRun` moved to top-level import in `main.py`; `WhatIfEngine`, `generate_audit_html`, `import_csv`, `delete_return_run` imports added.
- New test file `tests/test_milestone6_routes.py`: 22 route integration tests covering all Milestone 6 features.


- Full third-party license audit and NOTICE file (`docs/NOTICE.md`) with copyright notices for all production dependencies.
- Legal notices page in the web UI (`/legal` route, `app/templates/pages/legal.html`) with SQLCipher BSD-3-Clause attribution, dependency table, and disclaimers.
- Footer attribution bar in `app/templates/layouts/base.html` with license, SQLCipher credit, and link to legal notices page.
- Export control notice (`docs/EXPORT_CONTROL.md`) with ECCN classification, TSU exception details, and BIS notification template.
- Data privacy and liability disclaimer (`docs/DISCLAIMER.md`) tailored for local-first tax software.
- Legal & Acknowledgments section in `README.md` and `README.txt` crediting the encryption engine and key frameworks.
- Established project-level release documentation with a formal changelog.
- Added a public roadmap focused on federal completeness, state expansion, forms support, and security hardening.
- Added an explicit alpha support policy and versioning approach in the README.
- Database encryption at rest using SQLCipher (AES-256) with Python/Fernet fallback (`app/services/encryption.py`, `app/config.py`).
- Password-protected database with PBKDF2-HMAC-SHA256 key derivation (100,000+ iterations).
- Database unlock UI page (`app/templates/pages/unlock.html`).
- Encryption setup and usage guide (`docs/ENCRYPTION.md`).
- GitHub Actions CI pipeline (`.github/workflows/ci.yml`) running ruff, mypy, pytest, and pip-audit.
- Input validation for required trimmed first/last names on calculation submit.
- What-if scenario analysis engine (`app/engine/whatif.py`).
- Test suite for encryption (`tests/test_encryption.py`, `tests/test_encrypted_database.py`).
- Test for taxpayer name validation (`tests/test_calculate_name_validation.py`).
- Test for `_resolve_ref` edge cases (`tests/test_calculator_resolve_ref.py`).
- Test for UTF-8 encoding integrity (`tests/test_encoding_guard.py`).

### Changed
- Tightened AI agent governance docs (`AGENTS.md`, `.agent_tools/*`) with stricter MUST-level routing, formatting, append-only log protocol, and explicit validation reporting rules.
- Added a README tree mapping rule so agents use the documented repository structure first and must update the tree when structure changes.
- License changed from MIT to **GNU AGPL v3**; AGPL headers added to all source files.
- Restructured tests from project root into `tests/` directory.
- Moved `whatif.py` into `app/engine/`.
- Updated `pyproject.toml` license classifier from MIT to AGPL-3.0-or-later.
- Hardened `_resolve_ref` handling for missing or invalid string references.

### Fixed
- Persisted runs now retain and reload `state_outputs` (state data no longer disappears after save/load).
- Form mapper refund/owed math now uses line 22 when credits exist, including zero-after-credit cases.
- Form view now renders 1040 lines 12/19/21/22 so applied-deduction and post-credit tax values are visible.
- SPDX headers normalized to AGPL in `app/models/forms.py` and `app/services/form_mapper.py`.
- SQLCipher cursor compatibility via hybrid row factory supporting both index and key access.
- SQLCipher backup-path handling in encryption service corrected to append suffix safely.
- Ruff UP035 typing import warnings resolved in encryption service.
- Mypy `no-any-return` error resolved in security headers middleware.
- Additional MyPy type fixes across `app/main.py`, `tests/test_golden2.py`, and related modules.
- UTF-8 encoding issues in calculation outputs.

## [0.1.0-alpha.1] - 2026-02-15

### Added
- Initial MVP architecture for local-first, privacy-preserving tax computation.
- Deterministic rules engine with versioned rule packs for federal and state modules.
- Local web UI with calculation flow and run history views.
- Golden tests and baseline federal/state rule pack stubs.

### Notes
- This is an alpha/MVP release. Breaking changes are expected while core data models, rules, and APIs stabilize.
