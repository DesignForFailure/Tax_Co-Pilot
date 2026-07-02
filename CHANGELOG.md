<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Changelog

> **[← Back to README](README.md)** | [Roadmap](ROADMAP.md) · **Changelog** · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **Roadmap v2 Milestone 19 (complete): Earned Income Tax Credit.** The 2023/2024/2025 federal packs (bumped to 1.4.0) implement IRC §32 using the M16 `matrix_lookup` type for the parameter tables (filing status × qualifying children, capped at 3): maximum credit, phase-in rate, phaseout threshold (higher for MFJ), and phaseout rate — dollar amounts per Rev. Procs. 2022-38/2023-34/2024-40. Earned income follows Pub 596 Worksheet B (wages + SE net profit − half-SE-tax deduction, using M18's Schedule SE chain); the phaseout runs on the greater of AGI or earned income; the investment income limit ($11,000/$11,600/$11,950) disqualifies via a step gate; MFS filers are ineligible (zero max-credit column). **Deliberate deviation from the roadmap sketch:** the EIC is refundable, so it joins total payments (1040 Line 27 → 33) rather than the nonrefundable credit total — a filer whose income tax is already zeroed by the CTC still receives the full EIC as a refund. `ReturnOutput.earned_income_credit` added; 1040 line 27 wired through the form packet, forms view, and mapper consistency check. Covered by `tests/test_eitc.py` (18 hand-verified vectors).
- **Roadmap v2 Milestone 18 (complete): Self-employment tax auto-calculation.** SE tax is now computed automatically from 1099-NEC income across the 2023/2024/2025 federal packs (bumped to 1.3.0), per Schedule SE: 92.35% net-earnings factor, the $400 floor (IRC §1402(b)(2)), the Social Security portion (12.4%) capped at the year's wage base ($160,200 / $168,600 / $176,100) *reduced by W-2 wages*, and the uncapped 2.9% Medicare portion. The employer-equivalent half flows into AGI automatically (`fed.YYYY.adjustments.se_tax` uses the calculated value whenever NEC income exists, falling back to the manual field otherwise), and the refund now settles against a new `fed.YYYY.tax.total_liability` (income tax after credits + SE tax → 1040 Line 24). `ReturnOutput` gains `self_employment_tax`; the 1040 form packet and forms view gain lines 23/24. The calculate and what-if pages gain 1099-NEC entry rows (previously SE income had no web input path). Covered by `tests/test_se_tax.py` (15 hand-verified vectors incl. wage-base interaction and the $400 floor).
- **Roadmap v2 Milestone 17 (complete): Long-term capital gains preferential rates.** Long-term capital gains and qualified dividends are now taxed at 0%/15%/20% via the Qualified Dividends and Capital Gain Tax Worksheet instead of ordinary rates. New domain helpers (`total_long_term_capital_gains`, `total_short_term_capital_gains`) and engine inputs (`input.1099b.long_term_gain`/`short_term_gain`); new rules in the 2023/2024/2025 federal packs (bumped to 1.2.0): Schedule D short/long netting (`income.net_capital_gain` = smaller of lines 15/16, floored at zero), `income.preferential` (qualified dividends + net capital gain, capped at taxable income), `income.ordinary`, year-correct 0%/15% ceilings from IRS Rev. Procs. 2022-38/2023-34/2024-40, rate stacking on top of ordinary income (`tax.ltcg`), and the worksheet's final smaller-of comparison against all-ordinary tax (`tax.total_before_credits`, now the owner of 1040 Line 16). Short-term gains remain at ordinary rates; the -$3,000/-$1,500 capital loss limitation is unchanged. `ReturnOutput.tax_before_credits` prefers the worksheet total and falls back to the plain bracket tax for custom packs predating this change. Covered by `tests/test_ltcg_rates.py` (16 hand-verified golden vectors, including the smaller-of band where all-ordinary treatment wins).

## [0.3.0] - 2026-07-02

Phase 2 (capability expansion, milestone 16) is complete; per the roadmap the version line is promoted to `0.3.0`.

### Added
- **Roadmap v2 Milestone 16 (complete): `matrix_lookup` rule type.** Rules can now index nested constant tables by two or more keys simultaneously (e.g. filing status × number of children — the shape EITC parameter tables need). The loader validates that `keys` lists at least two reference entries and that `table` nests exactly as deep as the key list with numeric-string leaves (non-string YAML keys are rejected with quoting guidance). The evaluator canonicalizes numeric key values (a rounded `2.00` indexes key `"2"`), participates in dependency ordering via `{ref: ...}` keys, emits a `TraceNode` recording the full lookup path, and fails unknown key paths with the dimension, failing key, and available options. Documented in `docs/RULE_PACK_AUTHORING.md` §4.5; covered by `tests/test_matrix_lookup.py` (22 tests). The web rule editor rejects `matrix_lookup` edits with a clear message instead of silently rewriting the rule shape (no form section for nested tables yet).

## [0.2.0] - 2026-07-02

Phase 1 (structural hardening, milestones 12–15) is complete; per the roadmap the version line is promoted from `0.1.x` to `0.2.0`.

### Added
- **Roadmap v2 Milestone 15 (complete): Paginated run listings.** `list_return_runs()` now returns `(runs, total_count)` with `page`/`page_size` keyword arguments (LIMIT/OFFSET, clamped inputs), alongside new `count_return_runs()` and `list_all_return_runs()` helpers. `/runs` accepts `?page=N` (25 per page), renders Previous / windowed page numbers / Next controls with a "Showing X–Y of Z runs" summary, and redirects past-the-end pages to the last real page. The home page now reads its run count from `COUNT(*)` plus the five newest rows instead of loading every run; `/export-all` still exports everything via `list_all_return_runs()`. Covered by `tests/test_milestone15_pagination.py` (14 tests) and verified in Chromium.
- **Roadmap v2 Milestone 14 (complete): CSP hardening.** Removed `'unsafe-inline'` from both `script-src` and `style-src`. The 717-line design system moved from `base.html` to `app/static/css/main.css` (plus utility classes replacing all 60+ inline `style=""` attributes); all six inline `<script>` blocks became external files under `app/static/js/` (`theme.js`, `submit-guard.js`, `forms.js`, `compare.js`, `rule-editor.js`); every inline event handler (`onclick`/`onchange`/`onsubmit`) was replaced with delegated listeners driven by `data-*` attributes, including a shared `data-confirm` mechanism for destructive-action dialogs; per-request dynamic data (available states per year, rule-editor row counts) now travels via `data-*` attributes instead of Jinja-generated JavaScript. Static files are mounted at `/static`; `tests/test_milestone14_csp.py` (9 tests) enforces the header, template cleanliness, and served assets. Verified interactively in Chromium under the strict policy (theme toggle, dynamic form rows, spouse toggle, rule editor, confirm dialogs).
- **Roadmap: added Milestone 24 — Military-Specific Tax Calculations** (combat zone pay exclusion per IRC §112 with the commissioned-officer cap, W-2 Box 12 code Q handling, active-duty PCS moving expense deduction, reservist travel adjustment, and the EITC combat-pay election).
- **Roadmap v2 Milestone 13 (complete): Structured logging.** New `app/log.py` configures a `tax_copilot` logger (structured plaintext to stderr, level via `TAX_COPILOT_LOG_LEVEL`, optional 10 MB × 3 rotating file handler via `TAX_COPILOT_LOG_FILE`), wired into startup before any DB or encryption operation. Security events now produce log entries: startup (version, encryption state, available years), database unlock attempts, key rotation, encryption migration, keyring read/write failures, password validation failures, run creation/deletion, hash-chain verification results, CSRF validation failures, CSV/bulk import summaries, and backup/restore operations. Every `except Exception` block in `app/` now logs before handling — enforced by an AST-based guard test in the new `tests/test_logging.py` (17 tests).
- **Full-repository code review remediation (2026-07):** engine/loader hardening (runtime cycle detection and memoized rule evaluation, strict rounding-mode and bracket-table validation, reserved `input` namespace, state-pack prefix enforcement, rule-id charset validation), integrity-chain repair (stored-hash propagation in `verify_chain`, chain relinking on run deletion), CSV header validation, rule-editor validate-before-delete, atomic YAML/restore writes with WAL sidecar cleanup, spouse-data guard for non-MFJ filing statuses, and test isolation via `tests/conftest.py` (the suite previously wiped/replaced the real `data/tax_copilot.db`).
- New regression/golden test suites: `test_engine_hardening.py`, `test_chain_integrity.py`, `test_services_hardening.py`, `test_web_hardening.py`, `test_federal_corrections.py`, `test_state_corrections.py`.

### Rule pack corrections (affected packs bumped to 1.1.0)
- **Federal 2023/2024/2025:** Social Security lower tier capped at 50% of benefits (Pub 915); provisional income now includes tax-exempt interest and subtracts non-student-loan adjustments; MFS capital loss limit −$1,500 (IRC §1211(b)); CTC phaseout rounds AGI excess up to the next $1,000 (Form 8812); noncash charitable contributions capped at 30% of AGI.
- **GA 2024:** SB 56 standard deduction ($24,000 MFJ / $12,000 others), personal exemptions repealed — the pack previously used pre-2024 amounts, overstating GA tax. **GA 2023:** HoH now uses the MFJ bracket schedule; MFS exemption corrected to $3,700.
- **CA 2024:** bracket thresholds updated from the 2023 to the 2024 FTB schedules; HoH now uses Schedule Z. **NY 2024:** middle-bracket rates corrected to 5.5%/6.0%; HoH now has its own schedule.
- **NH 2024:** models the 3% Interest & Dividends tax (final year before repeal) instead of a no-tax stub.

### Known limitations (documented, not yet modeled)
- Qualified dividends and long-term capital gains are taxed at ordinary rates (no Qualified Dividends & Capital Gain Tax Worksheet yet).
- No EITC, refundable ACTC, $500 credit for other dependents, or additional standard deduction for age 65+/blind.
- GA dependent exemption ($4,000) not modeled; NY tax-benefit recapture above $107,650 NYAGI not modeled.
- SQLCipher key handling caveat documented in `docs/ENCRYPTION.md` (raw-key interpretation for passwords whose UTF-8 form is exactly 32/48 bytes; `TAX_COPILOT_KEY_ITERATIONS` is pinned by `cipher_compatibility = 4`).

### Added
- **Roadmap v2 Milestone 12 (complete):** Split the `main.py` monolith into `app/routes/` and `app/route_helpers/`, keeping `main.py` as a 93-line app-wiring module and adding `tests/test_milestone12_structure.py` to guard the new boundary.
- UI workspace refresh: added a dedicated landing page (`GET /`), moved the latest-run summary to `GET /dashboard`, and added `GET /runs/{run_id}/audit` for a full audit-trace page with collapsed rule-evaluation rows.
- **Milestone 12 — Rule Pack Editor (complete):** GUI-based rule pack management system. Create, edit, clone, import, and export YAML rule packs via web UI. Standard packs are read-only; custom variants stored in `custom_vN/` subdirectories. Type-adaptive rule editor for sum, formula, lookup, and bracket_table rules with inline bracket table editing. Calculate form integration with variant selector dropdown. Full validation via `RulePack.load()` on every save. CSRF-protected POST routes. Path traversal protection on all route parameters.
- `app/services/rule_pack_editor.py`: CRUD service for rule packs (list, load, clone, create, save, delete, validate, import, export).
- Rule Pack Manager page (`GET /rule-packs`) with grouped pack table, inline create form, and export/delete actions.
- Pack Detail page with metadata card, rule list, validation results, and clone/export/delete actions.
- Type-adaptive Rule Editor page with dynamic form sections for all four rule types.
- YAML Import page (`GET /rule-packs/import`) with file upload and `RulePack.load()` validation.
- "Rule Pack Variant" dropdown on calculate form for selecting custom federal packs.
- `tests/test_rule_pack_editor.py`: 24 service-layer unit tests.
- `tests/test_rule_pack_routes.py`: 15 route integration tests with test cleanup fixture.
- **Hardening, QA & Auditability pass (complete):** Fixed SQL injection in SQLCipher PRAGMA, `tax_year` validation, unary negation in rule expressions, `hybrid_factory` consistency, URL-encoded error redirects, upload size limits with SQLite integrity validation, input sanitization (tags/notes caps, filename sanitization, export fallback). Added tamper-evident hash chain (`integrity_hash`, `previous_hash`) with `GET /audit/verify`. Key rotation via `POST /rotate-key` with `PRAGMA rekey`. Password cache clearing on shutdown. Explicit cipher parameters. CSRF token rotation after authentication. Made `pip-audit` blocking in CI.

### Changed
- Web architecture now separates route handlers (`app/routes/`) from shared route utilities (`app/route_helpers/`); tests that previously imported `main.py` internals now target the extracted helper modules directly.
- Version labeling is now consistent across the app and documentation: `app.__version__` is the canonical application version source, alpha/beta terminology remains a separate project-status label, and custom rule-pack variant IDs (`custom_vN`) are now presented separately from manifest semantic versions.
- Rule pack cloning/import now preserves manifest semantic versions, new empty custom variants start at an independent rule-pack line (`1.0.0`), and SQLite now tracks its own schema generation separately via `PRAGMA user_version`.
- UI/UX refresh across the shared layout and primary pages: added browser-aware light/dark theme support with a manual theme toggle, introduced clearer top-level navigation, added jump links on long data-entry pages, reduced spacing clutter on dashboard/runs/forms/import/legal pages, and folded the README ASCII wordmark into the dashboard presentation.
- Rule pack manager/detail/import/editor pages and the encryption unlock/rotate screens now use the shared card/table/form layout system for clearer spacing, more consistent navigation, and better readability in both light and dark themes.

### Fixed
- Compatibility: Legacy custom rule packs that still store shorthand numeric manifest versions such as `1` now continue to load, validate, and run; editor write paths canonicalize those manifests back to full SemVer like `1.0.0`.
- Compliance: Added missing SPDX headers across repository configs, templates, YAML rule packs, GitHub automation files, and `README.txt`, and synchronized the README repository tree with the tracked `docs/superpowers/plans/2026-03-24-ui-ux-beta-hardening.md` file.
- **UX/Safety: Locked workspace routes now fail closed to `/unlock`** — DB-backed dashboard/history/export/audit/import flows, plus calculation submit, now redirect to the unlock screen instead of surfacing misleading empty-state copy or raw encrypted-database errors; the calculate spouse jump link was also corrected to target the rendered section anchor.
- **QA: Shipped state template now validates** — `rule_packs/state/_template/2024/` now uses a self-consistent `template.` rule namespace so repository-wide validation sweeps do not fail on the bundled starter pack.
- **UI: Rule Pack Manager create form no longer hides supported states** — `GET /rule-packs` now derives jurisdiction options from the actual discovered packs instead of a stale hardcoded `CA/NY/GA` list.
- **Compliance: Removed contradictory duplicate SPDX headers** — cleaned duplicate AGPL/GPL header lines from touched Python modules and tests.
- **Correctness: Withholding-only tax forms no longer disappear during parsing** — blank-name/blank-income rows are preserved when they still carry federal or state withholding data.
- **Correctness: Empty hidden spouse rows no longer break MFS submissions** — spouse detection now uses parsed content instead of raw dynamic-form key presence.
- **Correctness: Integrity verification now covers immutable state/run metadata** — hash recomputation now includes filing status, scenario, rule-pack version, state outputs, and created timestamp while still excluding mutable annotations.
- **Correctness: Multi-state execution is deterministic** — state pack loading/execution now sorts state codes to stabilize outputs and traces across processes.
- **Safety: What-if MFS comparison now fails closed on unsupported household-only fields** — multi-taxpayer MFS what-if runs reject shared income/deduction/payment inputs that the current data model cannot allocate safely.
- **UI: Calculate form state choices are now tax-year aware** — the residence dropdown is populated from year-specific state packs instead of always using the latest year.
- **UX: What-if household allocation failures now render inline** — `/whatif` now shows a page-level error card for unsupported multi-spouse household-only field combinations instead of falling back to a plain-text 400 response.
- **Docs: CI and public scope text synchronized with current behavior** — CONTRIBUTING/README/README.txt now match the blocking `pip-audit` gate, current multi-year/state support, and generic rule-pack layout.
- **Cleanup: Removed stale HTMX runtime/dependency references** — dropped the unused script include and aligned README/legal/NOTICE entries with the actual shipped frontend stack.
- **Security: Timing side-channel in key rotation** — `current_password` comparison in `/rotate-key` now uses `secrets.compare_digest` (constant-time) instead of `!=`.
- **Security: SQL injection in encryption migrations** — Table names from `sqlite_master` are now validated against `^[A-Za-z_][A-Za-z0-9_]*$` before interpolation into SQL in `_migrate_to_sqlcipher` and `_migrate_to_python_encryption`.
- **Integrity: Race condition in hash chain linking** — `save_return_run` now wraps `_get_latest_hash` read and INSERT in a single `BEGIN IMMEDIATE` / `COMMIT` block to prevent concurrent saves from duplicating `previous_hash`.
- **Correctness: Float coercion in bracket audit trace** — Bracket label formatting changed from `f"{(rate * 100):g}%"` (implicit float) to `f"{(rate * Decimal('100')).normalize()}%"` preserving Decimal fidelity.
- **Validation: Negative rounding precision** — `_round()` now raises `ValueError` if `precision < 0`, preventing silent misrounding from malformed rule packs.
- **Security: Upload size cap on rule pack import** — Rule pack file uploads are now limited to 2 MiB per file.
- **Compliance: SPDX license headers** — Added `# SPDX-License-Identifier: AGPL-3.0-or-later` to 28 Python source files that were missing the machine-readable identifier.
- **Cleanup: Removed garbage file** — Deleted accidental file in repo root (mypy error message saved as filename).
- **Edge case: `_safe_eval` misparse of nested `max()`/`min()`** — Bracket-matching now uses depth tracking instead of `endswith(")")`, which broke on expressions like `max(a, b) + c`.
- **Edge case: Backup route missing WAL checkpoint** — `GET /backup` now runs `PRAGMA wal_checkpoint(TRUNCATE)` before reading the DB file, ensuring all committed transactions are included.
- **Edge case: Restore route overwrites DB on failure** — Restore now keeps a `.pre_restore_backup` copy and rolls back if `init_db()` fails on the restored file.
- **Edge case: `_parse_money` rejects `$` prefix and unicode minus signs** — Dollar signs, en-dashes, em-dashes, and unicode minus (U+2212) are now normalized before parsing.
- **Edge case: CSV BOM breaks import** — `csv_import.py` now strips UTF-8 BOM (`\ufeff`) that Excel adds by default on Windows.
- **Edge case: Import returns crashes on non-UTF-8 files** — `POST /import-returns` now catches `UnicodeDecodeError` and returns 400.
- **Edge case: Import returns gives opaque error on duplicate run IDs** — Duplicate runs are now detected and skipped with a clear error message instead of a SQLite PRIMARY KEY violation.
- **Edge case: QSS filing status missing from state rule packs** — Added `qss` (Qualifying Surviving Spouse) entries to GA 2023, GA 2024, CA 2024, NY 2024, and template rule packs.
- **Edge case: `form_mapper` crashes on `None` trace values** — `Decimal(str(None))` → now guards with explicit `None` check.
- **Edge case: `verify_chain` silently skips empty hashes** — Runs with missing `integrity_hash` are now reported as `missing_hash` errors; chain propagation uses expected hash to avoid poisoning.
- **Edge case: `rotate_key` connection leak on error** — SQLCipher connection in `rotate_key()` now wrapped in `try/finally` to ensure `conn.close()`.
- **Edge case: Corrupted plaintext DB misclassified as encrypted** — `detect_encryption_state` now checks for SQLite magic bytes before assuming encryption, raising `RuntimeError` for corrupted files.
- **Edge case: `annotate_run` silently succeeds for nonexistent runs** — Now returns 404 when run ID not found (backed by `update_run_annotation` returning `bool`).
- **Edge case: Same-password key rotation allowed** — `/rotate-key` now rejects `new_password == current_password`.
- **Edge case: `export_yaml` crashes on missing files** — Now raises `ValueError` if manifest or rules file not found.
- **Edge case: `delete_rule` silently succeeds when rule not found** — Now raises `ValueError`.
- **Edge case: Custom pack name validation missing** — `clone_pack`, `create_empty_pack`, and `import_yaml` now validate custom names (non-empty, no control chars, max 100 chars).
- **Edge case: TOCTOU in `clone_pack`/`create_empty_pack`** — `mkdir(exist_ok=False)` race caught with `FileExistsError` handler.
- **Edge case: `Content-Disposition` header unquoted filenames** — Backup and export routes now quote filenames per RFC 6266.
- **Edge case: `save_return_run` missing ROLLBACK on error** — Transaction now wrapped in `try/except` with explicit `ROLLBACK`.

### Changed
- Migrated from deprecated `@app.on_event("startup")` to lifespan context manager.
- All DB functions now use `contextlib.closing` for leak-safe connections.

### Added
- **ci.yml** - Pushed file from previous milestone; required pushing separately from branch.
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

## [0.1.0] - 2026-02-15

### Added
- Initial MVP architecture for local-first, privacy-preserving tax computation.
- Deterministic rules engine with versioned rule packs for federal and state modules.
- Local web UI with calculation flow and run history views.
- Golden tests and baseline federal/state rule pack stubs.

### Notes
- This is an alpha/MVP release. Breaking changes are expected while core data models, rules, and APIs stabilize.
