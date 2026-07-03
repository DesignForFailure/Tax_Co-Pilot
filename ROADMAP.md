<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Roadmap v2

> **[← Back to README](README.md)** | **Roadmap** · [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md)
>
> Previous roadmap (milestones 1–11, all complete) archived at [`docs/ROADMAP_ARCHIVE_v1.md`](docs/ROADMAP_ARCHIVE_v1.md).

This roadmap covers the next phase of development: structural hardening, correctness fixes, and capability expansion. The ordering is deliberate — infrastructure work comes first to reduce the cost of every subsequent change.

## Current Stage

**Status:** Late Alpha — milestones 1–24 complete; Phase 4 (M20–M24) is done and the `0.4.0` promotion follows.
**SemVer line:** `0.3.x`.
**Test suite:** 560 passing, 4 skipped, 0 failures.
**Quality gates:** ruff clean, mypy clean, CI green (Python 3.11 + 3.12).

---

## Phase 1 — Structural Hardening

These milestones reduce future overhead by fixing core infrastructure before adding features.

### M12: Break Up `main.py` Monolith

**Status:** Complete on 2026-03-29. `main.py` now handles only app wiring, middleware, and lifespan; route logic lives in `app/routes/` and shared web helpers live in `app/route_helpers/`.

**Goal:** Split the 1,744-line `main.py` into focused route modules with shared utilities, so that future changes touch small, cohesive files instead of one sprawling monolith.

**Current state of `main.py`:**
- Lines 34–115: Imports (82 lines)
- Lines 117–236: App setup, middleware, global caches, cache helpers
- Lines 239–294: `_parse_money()` currency parser
- Lines 297–396: CSRF, DB lock checks, startup, run loading helpers
- Lines 399–445: Home + Dashboard routes (`/`, `/dashboard`)
- Lines 448–468: Calculate form GET route
- Lines 470–761: Form-parsing helpers (constants, money parsing, indexed field collection, W-2/1099 parsers, taxpayer builder, full input assembler, rule editor form parser)
- Lines 767–836: Calculate POST route
- Lines 838–944: Run management routes (`/runs`, `/runs/compare`, `/runs/{id}`, `/runs/{id}/audit`)
- Lines 950–989: What-if routes (`/whatif` GET/POST)
- Lines 995–1025: CSV import routes (`/import-csv` GET/POST)
- Lines 1031–1113: Run export routes (JSON, HTML, forms view, forms export)
- Lines 1119–1128: Run deletion (`/runs/{id}/delete`)
- Lines 1131–1134: Legal notices (`/legal`)
- Lines 1137–1200: Encryption unlock (`/unlock` GET/POST)
- Lines 1203–1218: Run annotation (`/runs/{id}/annotate`)
- Lines 1221–1359: Bulk export/import + backup/restore (`/export-all`, `/import-returns`, `/backup`, `/restore`)
- Lines 1362–1434: Key rotation + audit verify (`/rotate-key`, `/audit/verify`)
- Lines 1437–1739: Rule pack editor routes (16 handlers)
- Lines 1742–1745: ValueError exception handler

**What to build:**

```
app/
├── routes/
│   ├── __init__.py          # Package init
│   ├── calculate.py         # GET /, GET /dashboard, GET/POST /calculate, GET/POST /whatif
│   ├── navigation.py        # GET /legal (static pages with no service dependencies)
│   ├── runs.py              # GET /runs, GET /runs/{id}, GET /runs/{id}/audit,
│   │                        # GET /runs/{id}/forms, POST /runs/{id}/delete,
│   │                        # POST /runs/{id}/annotate, GET /runs/compare
│   ├── import_export.py     # GET/POST /import-csv, GET /runs/{id}/export/json,
│   │                        # GET /runs/{id}/export/html, GET /runs/{id}/export/forms,
│   │                        # GET /export-all, POST /import-returns,
│   │                        # GET /backup, POST /restore
│   ├── encryption.py        # GET/POST /unlock, GET/POST /rotate-key, GET /audit/verify
│   └── rule_packs.py        # All 16 /rule-packs/* handlers
├── route_helpers/
│   ├── __init__.py
│   ├── csrf.py              # _get_csrf_token(), _verify_csrf()
│   ├── db_state.py          # _database_locked(), _locked_database_response(),
│   │                        # _load_run_from_row(), _load_latest_run(), _startup()
│   ├── form_parsing.py      # _parse_money(), _form_str(), _form_money(),
│   │                        # _sanitize_filename(), _collect_indices(),
│   │                        # _parse_w2s(), _parse_1099ints(), _parse_1099divs(),
│   │                        # _parse_1099bs(), _parse_taxpayer(),
│   │                        # _taxpayer_has_form_data(), _parse_tax_input_from_form(),
│   │                        # _parse_rule_form()
│   │                        # Constants: _MAX_TEXT, _MAX_INDEXED_ENTRIES,
│   │                        # _MAX_IMPORT_BYTES, _MAX_RESTORE_BYTES,
│   │                        # _MAX_IMPORT_ENTRIES, _MAX_NOTES, _IDX_RE
│   └── pack_cache.py        # _federal_cache, _state_cache, available_years,
│                            # _bust_pack_cache(), _discover_available_years(),
│                            # _get_federal_pack(), _get_state_packs(),
│                            # _available_states_by_year()
main.py                      # App factory, lifespan, middleware, router includes,
                             # ValueError handler. Target: <100 lines.
```

**Dependency rules for the split:**
- `route_helpers/` modules import only from `app/services/`, `app/engine/`, `app/models/`, `app/config`, and stdlib. They never import from route modules or `main.py`.
- Route modules import from `route_helpers/` and `app/` packages. They never import from each other.
- `main.py` imports the FastAPI `app`, wires routers via `app.include_router()`, configures middleware, and defines the lifespan. It imports nothing from route modules directly.
- Each route module creates an `APIRouter` with an appropriate `prefix` and `tags` list.
- Templates and `BASE_DIR` are accessible via a shared module-level reference in `route_helpers/` or passed through `request.app.state`.

**Security constants** (`_MAX_TEXT`, `_MAX_INDEXED_ENTRIES`, `_MAX_IMPORT_BYTES`, `_MAX_RESTORE_BYTES`, `_MAX_IMPORT_ENTRIES`, `_MAX_NOTES`, `_IDX_RE`) move to `route_helpers/form_parsing.py`.

**Acceptance criteria:**
- `main.py` is under 100 lines.
- Every existing route responds identically (same paths, same status codes, same templates).
- `ruff check . && mypy . && pytest` — all 308 tests pass, zero new lint or type errors.
- No circular imports.

---

### M13: Structured Logging

**Status:** Complete on 2026-07-02. `app/log.py` configures the `tax_copilot` logger at startup; security events (unlock, key rotation, run lifecycle, hash verification, CSRF failures, backup/restore, imports) all produce log entries, and an AST guard test in `tests/test_logging.py` enforces that no `except Exception` block swallows silently.

**Goal:** Add Python `logging` throughout the application so that security events, errors, and operational state changes are observable.

**Current state:** Zero imports of `logging` anywhere in the codebase. Eight or more `except Exception` blocks silently swallow errors. No audit trail for security-sensitive operations.

**What to build:**

1. **Create `app/log.py`** — centralized logger configuration:
   - Configure a named `tax_copilot` logger with structured plaintext output (`timestamp level module message`).
   - Default level: `INFO` in production, `DEBUG` when `TAX_COPILOT_LOG_LEVEL=DEBUG`.
   - Console handler (stderr) for all levels.
   - Optional rotating file handler at `data/tax_copilot.log` (10 MB max, 3 backups).
   - Environment variable `TAX_COPILOT_LOG_LEVEL` to override.

2. **Add security event logging** — every one of these must produce a log entry:
   - `app/services/encryption.py`:
     - Password validation attempts (success/failure) — lines 270–278 (`get_password_from_keyring`), 294–300 (`set_password_in_keyring`)
     - Database unlock attempts (success/failure)
     - Key rotation (start, success, failure)
     - Encryption state detection results — lines 211–225
     - Migration operations (start, success, failure)
   - `app/services/database.py`:
     - Run creation (run_id, tax_year, filing_status)
     - Run deletion (run_id)
     - Hash chain verification (result: pass/fail, break position if fail)
     - DB initialization
     - JSON decode errors in hash verification — lines 323–326, 385, 474
   - Route handlers (`app/routes/` after M12):
     - Backup download
     - Restore upload (success/failure)
     - CSV import (record_type, count, error_count)
     - Bulk import (count, skipped, errors)
     - CSRF validation failures

3. **Fix silent exception swallowing** — replace bare `except Exception` with logged exceptions:
   - `encryption.py:276` → `logger.warning("Keyring read failed", exc_info=True); return None`
   - `encryption.py:299` → `logger.warning("Keyring write failed", exc_info=True); return False`
   - `encryption.py:211-224` → `logger.debug("Encryption state detection: %s", state)`
   - `database.py` hash verification paths → `logger.error("Hash verification: JSON decode error at row %s", row_id)`
   - All route-level `except Exception as e` blocks → `logger.exception("Route error")` before returning error response

4. **Wire logging into startup** — call `app.log.configure()` at the top of `_startup()` in `route_helpers/db_state.py` (or `main.py` lifespan) so logging is active before any DB or encryption operations.

**Acceptance criteria:**
- Starting the app produces a startup log line with version, encryption state, and available years.
- Unlocking the database logs the attempt and result.
- Creating a run logs the run_id and tax_year.
- Deleting a run logs the run_id.
- Key rotation logs start and outcome.
- No `except Exception` block exists without a `logger` call.
- Existing tests unaffected (logging does not change behavior).
- `ruff check . && mypy . && pytest` clean.

---

### M14: Remove `unsafe-inline` from CSP

**Status:** Complete on 2026-07-02. All inline CSS/JS extracted to `app/static/`; CSP is now `script-src 'self'; style-src 'self'`. Inline event handlers (`onclick=`/`onchange=`/`onsubmit=`) were also removed (they are blocked by `script-src 'self'` too) in favor of delegated listeners and `data-*` attributes; per-request data (state lists, editor row counts) travels via `data-*` attributes instead of Jinja-generated scripts. Enforced by `tests/test_milestone14_csp.py` and verified interactively in Chromium under the strict policy.

**Goal:** Eliminate `'unsafe-inline'` from both `script-src` and `style-src` in the Content-Security-Policy header by extracting all inline CSS and JavaScript to external static files.

**Current state:**
- CSP in `main.py` lines 136–145: `script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'`
- `app/static/` directory does **not exist**.
- `base.html` lines 20–738: 717-line `<style>` block (full design system).
- `base.html` lines 8–18 + 784–837: Two `<script>` blocks (theme persistence + form submit handler).
- `calculate.html` line 234–287: `<script>` block (dynamic form row generation).
- `whatif.html` lines 274–326: `<script>` block (dynamic form row generation, near-identical to calculate).
- `runs.html` lines 112–148: `<script>` block (run comparison checkbox logic).
- `rule_editor.html` line 249+: `<script>` block (rule type switching).
- 40+ `style=""` inline attributes scattered across `dashboard.html`, `home.html`, `import_csv.html`, `legal.html`, `run_compare.html`, `runs.html`, `whatif.html`.

**What to build:**

1. **Create `app/static/` directory** with:
   - `app/static/css/main.css` — Move all 717 lines from `base.html <style>` block. Add utility classes to replace every `style=""` attribute (e.g., `.mb-4 { margin-bottom: 4px; }`, `.text-red { color: var(--red); }`, `.text-2xl { font-size: 2rem; }`, etc.).
   - `app/static/js/theme.js` — Theme persistence logic from `base.html` lines 8–18 + toggle handler from lines 784–827.
   - `app/static/js/forms.js` — Dynamic form row add/remove from `calculate.html` and `whatif.html` (deduplicate — these are nearly identical).
   - `app/static/js/submit-guard.js` — Form double-submit prevention from `base.html` lines 829–836.
   - `app/static/js/compare.js` — Run comparison checkbox logic from `runs.html` lines 112–148.
   - `app/static/js/rule-editor.js` — Rule type switching from `rule_editor.html`.

2. **Mount static files** in `main.py`:
   ```python
   from fastapi.staticfiles import StaticFiles
   app.mount("/static", StaticFiles(directory="app/static"), name="static")
   ```

3. **Update all templates:**
   - `base.html`: Replace `<style>...</style>` with `<link rel="stylesheet" href="/static/css/main.css">`. Replace all `<script>...</script>` blocks with `<script src="/static/js/theme.js"></script>`, etc.
   - Replace every `style="..."` attribute in page templates with the corresponding utility class.
   - Ensure `theme.js` runs early (in `<head>`) to prevent flash of wrong theme.

4. **Update CSP** to remove `'unsafe-inline'`:
   ```
   script-src 'self'; style-src 'self';
   ```

5. **Add CSP nonce support (if needed):** If any template truly requires per-request inline content (e.g., Jinja2-generated `<script>` with dynamic data), use a CSP nonce:
   - Generate a random nonce per request in the security headers middleware.
   - Add `'nonce-{value}'` to `script-src`.
   - Set `nonce="{{ csp_nonce }}"` on the `<script>` tag.
   - **Preferred alternative:** Pass dynamic data via `data-*` attributes on HTML elements and read them in external JS, avoiding inline scripts entirely.

**Acceptance criteria:**
- `app/static/css/main.css` exists and contains the full design system.
- `app/static/js/` contains all extracted scripts.
- Zero `<style>` blocks remain in any template.
- Zero `style=""` attributes remain in any template.
- Zero `<script>` blocks with inline code remain in any template (all use `src=""`).
- CSP header no longer contains `'unsafe-inline'`.
- Visual appearance is identical (verify by manual inspection of home, calculate, dashboard, runs, whatif, rule-packs pages).
- Theme toggle still works (dark/light mode persists across page loads).
- Dynamic form rows still work on calculate and whatif pages.
- Run comparison checkboxes still work on runs page.
- `ruff check . && mypy . && pytest` clean.

---

### M15: Paginate Run Listings

**Status:** Complete on 2026-07-02. `list_return_runs()` returns `(runs, total_count)` with clamped `page`/`page_size`; `count_return_runs()` and `list_all_return_runs()` cover the count-only and export-all callers; `/runs?page=N` renders windowed pagination controls with a "Showing X–Y of Z runs" summary. Version promoted to `0.2.0` (Phase 1 complete).

**Goal:** Add server-side pagination to `list_return_runs()` and the `/runs` page so the system handles thousands of saved runs without degrading.

**Current state:**
- `database.py:390-400` — `list_return_runs()` executes `SELECT * FROM return_runs ORDER BY created_at DESC` with `.fetchall()`. No LIMIT or OFFSET.
- `main.py` (post-M12: `routes/runs.py`) — passes entire list to template.
- `runs.html` — iterates `{% for r in runs %}` with no pagination UI.

**What to build:**

1. **Update `list_return_runs()` in `app/services/database.py`:**
   ```python
   def list_return_runs(
       tax_year: int | None = None,
       *,
       page: int = 1,
       page_size: int = 25,
   ) -> tuple[list[dict], int]:
       """Return (runs, total_count) with pagination."""
   ```
   - Add a `SELECT COUNT(*)` query (with optional `WHERE tax_year = ?`) to get total count.
   - Add `LIMIT ? OFFSET ?` to the data query. Offset = `(page - 1) * page_size`.
   - Return `(rows, total_count)` tuple.
   - Keep backward compatibility: default `page=1, page_size=25` produces same-as-before behavior for callers that don't pass args.

2. **Update the `/runs` route** to accept `?page=N` query parameter:
   - Parse `page` from query string (default 1, minimum 1).
   - Pass `page` and `page_size` to `list_return_runs()`.
   - Compute `total_pages = ceil(total_count / page_size)`.
   - Pass `page`, `total_pages`, `total_count` to template context.

3. **Update `runs.html` template:**
   - Below the table, add pagination controls: Previous / page numbers / Next.
   - Show "Showing X–Y of Z runs" summary.
   - Preserve comparison checkbox state within a single page (cross-page comparison is out of scope).

4. **Update callers of `list_return_runs()`** that don't need pagination:
   - `GET /` (home page) — only needs run count, not full list. Add a `count_return_runs()` function or use the `total_count` from `list_return_runs(page=1, page_size=0)`.
   - `GET /export-all` — needs all runs (no pagination). Keep calling with a large `page_size` or add a `list_all_return_runs()` variant.

**Acceptance criteria:**
- `/runs` shows 25 runs per page by default.
- `/runs?page=2` shows the second page.
- Pagination controls render correctly (disabled Previous on page 1, disabled Next on last page).
- `GET /export-all` still exports all runs.
- Home page run count is correct without loading all rows.
- `ruff check . && mypy . && pytest` clean.
- Add tests: paginated query returns correct subset, total count is accurate, page=0 and page=-1 handled gracefully.

---

## Phase 2 — Capability Expansion

These milestones add missing engine capabilities that unlock blocked features.

### M16: Multi-Dimensional Rule Lookups

**Status:** Complete on 2026-07-02. `matrix_lookup` is the fifth rule type: `keys` (2+ reference entries) index a nested `table` validated to the exact key depth with numeric-string leaves; numeric key values are canonicalized (a `2.00` result indexes key `"2"`); `{ref: ...}` keys participate in topological ordering and bare-string keys resolve lazily; unknown key paths fail with the dimension, key, and available options; the trace records the full lookup path. Documented in `docs/RULE_PACK_AUTHORING.md` §4.5. The web rule editor intentionally rejects `matrix_lookup` edits (no form section yet — edit the YAML); version promoted to `0.3.0` (Phase 2 complete).

**Goal:** Add a `matrix_lookup` rule type to the engine so rules can index by two or more keys simultaneously. This unblocks EITC and any future credit/deduction with multi-dimensional phase-in/phase-out tables.

**Current state:**
- `rule_loader.py` supports 4 rule types: `sum`, `formula`, `lookup`, `bracket_table`.
- `lookup` indexes by a single key (e.g., filing status → value).
- `bracket_table` indexes by a single key (filing status) into a bracket array.
- EITC requires: filing_status × number_of_children → (phase_in_rate, phase_in_end, phase_out_start, phase_out_rate, max_credit).

**What to build:**

1. **Add `matrix_lookup` rule type** to `app/engine/rule_loader.py`:
   - YAML schema:
     ```yaml
     - id: fed.2024.credits.eic.max_credit
       type: matrix_lookup
       description: "EIC maximum credit by filing status and children"
       keys: [filing_status, num_children]
       table:
         single:
           "0": "632"
           "1": "4213"
           "2": "6960"
           "3": "7830"
         mfj:
           "0": "632"
           "1": "4213"
           "2": "6960"
           "3": "7830"
         # ... etc
     ```
   - Validation: `keys` must be a list of 2+ strings. `table` must be a nested dict matching the key depth. All leaf values must be numeric strings.
   - Expression whitelist: no change (matrix_lookup doesn't use expressions).

2. **Add `_evaluate_matrix_lookup()` to `app/engine/calculator.py`:**
   - Resolve each key from the resolved namespace (e.g., `filing_status` resolves to `"single"`, `num_children` resolves to `"2"`).
   - Traverse the nested dict level by level.
   - Return the leaf `Decimal` value.
   - Produce a `TraceNode` with all key values and the lookup path.

3. **Register the new type** in `rule_loader.py` validation (add to the rule type enum) and in `calculator.py` dispatch (add to `_evaluate_rule()`).

4. **Add dependency extraction** for `matrix_lookup` rules — the `keys` list may reference rule IDs or input fields, so `_extract_refs()` must handle them.

5. **Add tests:**
   - Load a rule pack with a `matrix_lookup` rule, verify it evaluates correctly for multiple key combinations.
   - Verify that invalid key paths (missing dimension, unknown key value) produce clear errors.
   - Verify topological sort includes `matrix_lookup` dependencies.

**Acceptance criteria:**
- A `matrix_lookup` rule can be defined in YAML and evaluates correctly.
- Existing rule types are unaffected.
- `ruff check . && mypy . && pytest` clean.

---

## Phase 3 — Tax Correctness

These milestones fix known calculation inaccuracies.

### M17: Long-Term Capital Gains Preferential Rates

**Status:** Complete on 2026-07-02. The 2023/2024/2025 federal packs (v1.2.0) implement the Qualified Dividends and Capital Gain Tax Worksheet: Schedule D short/long netting, preferential income capped at taxable income, year-correct 0%/15% ceilings, 0%/15%/20% stacking on top of ordinary income, and the worksheet's final smaller-of comparison against all-ordinary tax (which binds in the narrow band where 15% exceeds the ordinary marginal rate). `fed.YYYY.tax.total_before_credits` now owns 1040 Line 16; `ReturnOutput.tax_before_credits` falls back to the bracket tax for older custom packs. 16 hand-verified golden vectors in `tests/test_ltcg_rates.py`.

**Goal:** Tax long-term capital gains and qualified dividends at the correct preferential rates (0%/15%/20%) instead of ordinary income rates.

**Current state:**
- `Form1099BData.is_long_term` exists in the model but is unused in calculation.
- All capital gains are summed into gross income and taxed at ordinary rates via `fed.2024.tax.brackets`.
- Qualified dividends (`Form1099DIVData.qualified_dividends`) are similarly taxed at ordinary rates.

**What to build:**

1. **Add input resolution** in `calculator.py` for:
   - `resolved[input.total_long_term_capital_gains]` — sum of `1099_b.net_gain` where `is_long_term=True`
   - `resolved[input.total_short_term_capital_gains]` — sum of `1099_b.net_gain` where `is_long_term=False`
   - `resolved[input.total_qualified_dividends]` — already exists, verify it's resolved

2. **Add helper methods** to `TaxReturnInput` in `domain.py`:
   - `total_long_term_capital_gains() -> Decimal`
   - `total_short_term_capital_gains() -> Decimal`
   - These iterate all taxpayers' 1099-B records, filtering by `is_long_term`.

3. **Add LTCG bracket constants** to `federal_2024_rules.yaml`:
   ```yaml
   ltcg_brackets:
     single:
       - { up_to: "47025", rate: "0" }
       - { up_to: "518900", rate: "0.15" }
       - { up_to: "Infinity", rate: "0.20" }
     mfj:
       - { up_to: "94050", rate: "0" }
       - { up_to: "583750", rate: "0.15" }
       - { up_to: "Infinity", rate: "0.20" }
     mfs:
       - { up_to: "47025", rate: "0" }
       - { up_to: "291850", rate: "0.15" }
       - { up_to: "Infinity", rate: "0.20" }
     hoh:
       - { up_to: "63000", rate: "0" }
       - { up_to: "551350", rate: "0.15" }
       - { up_to: "Infinity", rate: "0.20" }
     qss:
       - { up_to: "94050", rate: "0" }
       - { up_to: "583750", rate: "0.15" }
       - { up_to: "Infinity", rate: "0.20" }
   ```

4. **Add LTCG tax rules:**
   - `fed.2024.income.preferential` — sum of long-term capital gains + qualified dividends (the "preferential income" amount)
   - `fed.2024.income.ordinary` — taxable income minus preferential income
   - `fed.2024.tax.ordinary` — bracket table on ordinary income only
   - `fed.2024.tax.ltcg` — bracket table on preferential income at LTCG rates (stacked on top of ordinary income for bracket positioning)
   - `fed.2024.tax.total_before_credits` — sum of ordinary tax + LTCG tax
   - Update `fed.2024.tax.after_credits` to reference the new total

5. **Update 2023 rules** with 2023 LTCG thresholds.

6. **Add golden test vectors:**
   - Single filer, $50k wages, $20k LTCG → LTCG taxed at 0%/15% split, not 22%
   - MFJ, $80k wages, $30k LTCG → all LTCG at 0%
   - Single filer, $500k wages, $100k LTCG → LTCG at 15%/20% split
   - Mixed: short-term gains taxed at ordinary, long-term at preferential
   - Qualified dividends get preferential treatment

**Acceptance criteria:**
- Long-term capital gains are taxed at 0%/15%/20% based on taxable income and filing status.
- Short-term capital gains remain taxed at ordinary rates.
- Qualified dividends receive preferential rate treatment.
- All existing golden tests updated to reflect correct LTCG treatment (some expected values may change if they included capital gains).
- `ruff check . && mypy . && pytest` clean.

---

### M18: Self-Employment Tax Auto-Calculation

**Status:** Complete on 2026-07-02. The 2023/2024/2025 federal packs (v1.3.0) implement Schedule SE: the 92.35% factor, the $400 net-earnings floor, the SS portion capped at the year's wage base reduced by W-2 wages, and the uncapped Medicare portion. The employer-half deduction flows into AGI automatically (manual field remains the fallback when no NEC income exists), the refund settles against `fed.YYYY.tax.total_liability` (1040 Line 24), `ReturnOutput.self_employment_tax` is exposed, and the calculate/what-if pages gained 1099-NEC entry rows. 15 golden vectors in `tests/test_se_tax.py`. (The 0.9% Additional Medicare Tax remains unmodeled — tracked alongside NIIT in M22-era work.)

**Goal:** Automatically compute self-employment tax and the above-the-line SE tax deduction from 1099-NEC income, instead of requiring manual input.

**Current state:**
- `Form1099NECData` exists in the model with `nonemployee_compensation`.
- `TaxReturnInput.total_self_employment_income()` sums NEC amounts.
- `AdjustmentsData.self_employment_tax_deduction` is a manual Decimal input.
- The adjustment rule `fed.2024.adjustments.se_tax_deduction` reads this manual input.

**What to build:**

1. **Add SE tax constants** to `federal_2024_rules.yaml`:
   ```yaml
   se_tax_rate: "0.153"
   se_income_factor: "0.9235"
   ss_wage_base_2024: "168600"
   ss_rate: "0.124"
   medicare_rate: "0.029"
   additional_medicare_threshold:
     single: "200000"
     mfj: "250000"
     mfs: "125000"
     hoh: "200000"
     qss: "250000"
   additional_medicare_rate: "0.009"
   ```

2. **Add SE tax rules:**
   - `fed.2024.se.net_earnings` — `total_self_employment_income * 0.9235`
   - `fed.2024.se.ss_taxable` — `max(min(se_net, ss_wage_base - total_wages), 0)` (reduce SS wage base by W-2 wages already subject to SS)
   - `fed.2024.se.ss_tax` — `ss_taxable * 0.124`
   - `fed.2024.se.medicare_tax` — `se_net * 0.029`
   - `fed.2024.se.total` — `ss_tax + medicare_tax`
   - `fed.2024.se.deduction` — `se_total * 0.5` (employer-equivalent half)

3. **Wire SE deduction into adjustments:**
   - Change `fed.2024.adjustments.se_tax_deduction` from reading manual input to referencing `fed.2024.se.deduction`.
   - Keep the manual `self_employment_tax_deduction` field on `AdjustmentsData` as a fallback/override. If the user provides a non-zero manual value AND has no 1099-NEC income, use the manual value. If 1099-NEC income exists, use the calculated value.

4. **Add input resolution** for `total_wages` (sum of all W-2 wages across taxpayers) if not already resolved — needed for SS wage base reduction.

5. **Add to `ReturnOutput`:** `self_employment_tax: Decimal` field.

6. **Update 2023 rules** with 2023 SS wage base ($160,200).

7. **Add test vectors:**
   - $100k NEC income, no W-2 → SE tax = $14,130 (92.35% × $100k × 15.3%), deduction = $7,065
   - $200k W-2 wages + $50k NEC → SS portion capped (wage base already mostly used by W-2), Medicare applies to all
   - Zero NEC income → no SE tax, manual deduction field still works
   - $50k NEC + manual override → calculated value wins when NEC exists

**Acceptance criteria:**
- SE tax is auto-calculated when 1099-NEC income exists.
- SE deduction flows into AGI adjustments automatically.
- SS wage base reduction accounts for W-2 wages.
- Manual SE deduction override works when no NEC income is present.
- `ruff check . && mypy . && pytest` clean.

---

### M19: Earned Income Tax Credit (EITC)

**Status:** Complete on 2026-07-02. The 2023/2024/2025 packs (v1.4.0) implement IRC §32 with `matrix_lookup` parameter tables (filing status × children capped at 3; MFS ineligible via a zero column; MFJ gets the higher phaseout thresholds), Pub 596 Worksheet B earned income (wages + SE net profit − half-SE-tax deduction), phaseout on the greater of AGI or earned income, and the per-year investment income limit. Deviation from the sketch below: the EIC is refundable, so it flows into total payments (1040 Line 27) instead of `tax.after_credits` — refundability is preserved and golden-tested. Parameter dollar amounts were corrected to each year's Revenue Procedure (the figures below are TY2023 values). 18 golden vectors in `tests/test_eitc.py`.

**Goal:** Implement EITC using the `matrix_lookup` rule type from M16.

**Depends on:** M16 (multi-dimensional lookups), M18 (SE income for earned income calculation).

**What to build:**

1. **Add EITC parameter tables** to `federal_2024_rules.yaml` as `matrix_lookup` rules:
   - `fed.2024.credits.eic.max_credit` — filing_status × num_children → max credit
   - `fed.2024.credits.eic.phase_in_rate` — filing_status × num_children → phase-in percentage
   - `fed.2024.credits.eic.phase_in_end` — filing_status × num_children → earned income where phase-in ends
   - `fed.2024.credits.eic.phase_out_start` — filing_status × num_children → AGI where phase-out begins
   - `fed.2024.credits.eic.phase_out_rate` — filing_status × num_children → phase-out percentage

2. **Add EITC calculation rules:**
   - `fed.2024.credits.eic.earned_income` — wages + net SE earnings (earned income for EITC purposes)
   - `fed.2024.credits.eic.phase_in_amount` — `min(earned_income * phase_in_rate, max_credit)`
   - `fed.2024.credits.eic.phase_out_amount` — `max(0, (max(agi, earned_income) - phase_out_start) * phase_out_rate)`
   - `fed.2024.credits.eic.tentative` — `max(0, phase_in_amount - phase_out_amount)`
   - `fed.2024.credits.eic.final` — `tentative` (with investment income limit check: disqualified if investment income > $11,600)

3. **Add `number_of_qualifying_children_eic`** to `TaxReturnInput` if different from existing `number_of_qualifying_children` for CTC (EITC has different age rules). Or reuse if the UI treats them as the same field.

4. **Wire into total credits:** Update `fed.2024.tax.after_credits` to subtract EIC.

5. **Add to `ReturnOutput`:** `earned_income_credit: Decimal`.

6. **2024 EITC parameters** (verify against IRS Rev. Proc. 2023-34):
   - 0 children: max $632, phase-in 7.65%, phase-out 7.65%, phase-out start $9,800 single / $16,370 MFJ
   - 1 child: max $4,213, phase-in 34%, phase-out 15.98%, phase-out start $21,560 single / $28,120 MFJ
   - 2 children: max $6,960, phase-in 40%, phase-out 21.06%, phase-out start $21,560 single / $28,120 MFJ
   - 3+ children: max $7,830, phase-in 45%, phase-out 21.06%, phase-out start $21,560 single / $28,120 MFJ

7. **Add test vectors:**
   - Single, 1 child, $15k wages → receives EIC (in phase-in range)
   - MFJ, 2 children, $25k wages → receives max EIC
   - Single, 0 children, $60k wages → no EIC (above phase-out)
   - Investment income > $11,600 → disqualified

**Acceptance criteria:**
- EITC calculated correctly for all filing statuses and child counts.
- Phase-in and phase-out computed correctly.
- Investment income disqualification enforced.
- EIC flows into total credits and reduces tax owed.
- `ruff check . && mypy . && pytest` clean.

---

## Phase 4 — Additional Tax Features

### M20: Education Credits (AOTC / LLC)

**Status:** Complete on 2026-07-02. The 2023/2024/2025 packs (v1.5.0) implement Form 8863: per-student AOTC tiers (100% of the first $2,000 + 25% of the next $2,000) via input aggregation, the 40% refundable / 60% nonrefundable split (refundable portion flows to 1040 Line 29 in payments; nonrefundable joins the credit total), the per-return LLC (20% of up to $10,000, nonrefundable), the shared MAGI phaseout ($80k–$90k, doubled for MFJ; AGI used as MAGI), and MFS ineligibility (IRC §25A(g)(6)). New `education_students`/`llc_expenses` inputs with dynamic web-form rows. 19 golden vectors in `tests/test_education_credits.py`.

**Goal:** Add American Opportunity Tax Credit and Lifetime Learning Credit.

- AOTC: 100% of first $2,000 + 25% of next $2,000 per student, max $2,500. Phaseout at $80k/$160k. 40% refundable.
- LLC: 20% of first $10,000 expenses per return, max $2,000. Phaseout at $80k/$160k.
- Add `education_expenses` input fields per student.
- Add rules and trace.

### M21: Dependent Care Credit

**Status:** Complete on 2026-07-03. The 2023/2024/2025 packs (v1.6.0) implement Form 2441: $3,000/$6,000 expense caps, the earned-income limit (lesser spouse for MFJ; both spouses must have earned income — the student/disabled deemed-income exception is unmodeled), and the 35%→20% sliding rate matching the IRS table boundaries. Nonrefundable. 15 golden vectors in `tests/test_dependent_care.py`.

**Goal:** Add Credit for Child and Dependent Care Expenses (Form 2441).

- 20–35% of up to $3,000 (one dependent) or $6,000 (two+) in care expenses.
- Percentage scales with AGI.

### M22: Net Investment Income Tax (NIIT)

**Status:** Complete on 2026-07-03. The 2023/2024/2025 packs (v1.7.0) implement Form 8960 / IRC §1411: 3.8% of the smaller of net investment income (interest + dividends + capital gains after the Schedule D loss limitation, floored at zero) or the MAGI excess over the statutory thresholds ($200k single/HoH, $250k MFJ/QSS, $125k MFS — not inflation-indexed; AGI used as MAGI). A new `fed.YYYY.tax.other_taxes` rule (Schedule 2 → 1040 Line 23) aggregates SE tax + NIIT into `tax.total_liability`. 12 golden vectors in `tests/test_niit.py`.

**Goal:** Add the 3.8% NIIT on investment income above $200k single / $250k MFJ.

- Simple formula rule: `max(0, min(net_investment_income, agi - threshold)) * 0.038`

### M23: Additional State Credits & Deductions

**Status:** Complete on 2026-07-03 (with one documented exclusion). GA packs (2023/2024/2025 → 1.2.0) implement the §48-7A-3 low income credit (per-exemption AGI bands, nonrefundable, capped at tax; age-65 extra exemption unmodeled). The NY 2024 pack (→ 1.2.0) implements the NYC resident income tax (2024 rate schedule, verified against published cumulative amounts) and the 16.75% Yonkers resident surcharge behind mutually-exclusive full-year residency flags. The CA 2024 pack (→ 1.2.0) implements the nonrefundable renter's credit ($60/$120, AGI ceilings $52,421/$104,842). **CalEITC excluded:** the FTB publishes its two-segment phaseout only as worksheet tables that cannot be verified into a closed-form rule from official sources; revisit if the FTB publishes the underlying parameters. 29 tests in `tests/test_state_credits.py`.

**Goal:** Add state-specific credits beyond the basic tax calculation for CA, NY, and GA.

- CA: Renter's credit, CA EITC
- NY: NYC income tax, Yonkers surcharge
- GA: Low-income credit

### M24: Military-Specific Tax Calculations

**Status:** Complete on 2026-07-03. The 2023/2024/2025 packs (v1.8.0) implement the IRC §112 combat pay exclusion (informational trace — Box 12 Q is already absent from Box 1 and never re-subtracted), the officer monthly cap with warning trace ($10,011.00 / $10,519.80 / $10,983.00 = highest enlisted basic pay + $225 IDP, verified against Pub 3 and DoD pay tables — the sketch's 2024 figure of $9,736.50 below was wrong), Form 3903 moving expenses and reservist travel as Schedule 1 adjustments, and the EITC combat pay election as a parallel elected chain with `credits.eic.final` taking the better result. What-if gains a scenario selector with `compare_combat_pay_election`. 17 tests in `tests/test_military.py`.

**Goal:** Model the federal tax treatment of U.S. armed forces members: the combat zone pay exclusion and the military-only deductions that survive TCJA. Verify every parameter against IRS Publication 3 (Armed Forces' Tax Guide) for the target tax year.

**Depends on:** M12 (routes split). The EITC combat-pay election additionally depends on M19 (EITC).

**What to build:**

1. **Domain model inputs** (`app/models/domain.py`) — per-taxpayer military service data:
   - `nontaxable_combat_pay: Decimal` — W-2 Box 12 code Q amount (already excluded from Box 1 wages by the employer; the engine must *not* re-subtract it from wages).
   - `is_commissioned_officer: bool` — officers' monthly exclusion is capped; enlisted members and warrant officers exclude all pay for qualifying months (IRC §112(a)–(b)).
   - `combat_zone_months: int` — months (or part-months, which count as full months) served in a designated combat zone.
   - `active_duty_moving_expenses: Decimal` — unreimbursed PCS moving expenses (Form 3903). Military moves remain deductible post-TCJA (IRC §217(g)).
   - `reservist_travel_expenses: Decimal` — overnight travel >100 miles for reserve duty (above-the-line, IRC §62(a)(2)(E)).

2. **Officer exclusion cap validation** — commissioned officers' monthly exclusion is limited to the highest enlisted pay rate plus hostile fire / imminent danger pay for that month (2024: $9,736.50 + $225 per month; confirm against the year's rate tables). Add a `fed.YYYY.military.officer_exclusion_cap` constant per year pack and flag (in trace output) when the reported Box 12 Q amount exceeds `cap × combat_zone_months` for an officer.

3. **Rules** (`fed.YYYY.military.*` namespace in the federal rule packs):
   - `fed.YYYY.adjustments.military_moving` — Form 3903 amount flows into the AGI adjustments sum.
   - `fed.YYYY.adjustments.reservist_travel` — above-the-line adjustment.
   - Trace entries must show the exclusion, caps applied, and form-line mapping (1040 Schedule 1).

4. **EITC combat pay election (with M19):** taxpayers may elect to *include* nontaxable combat pay in earned income when it increases EITC (IRC §32(c)(2)(B)(vi)). Compute EITC both ways (with and without the election, all-or-nothing per taxpayer) and take the higher credit; record the election in the trace.

5. **What-if integration:** expose the EITC election as a scenario in `WhatIfEngine` so members can see both outcomes.

6. **Out of scope (document explicitly):** filing-deadline extensions for combat service (IRC §7508 — administrative, not computational), veterans' disability compensation (never on a W-2), state military pay exemptions and SCRA residency rules (follow-on state milestone).

**Acceptance criteria:**
- Combat pay reported via Box 12 Q stays excluded from federal wages and taxable income, with a trace node documenting the exclusion.
- Officer cap warnings appear when Q exceeds the monthly cap × qualifying months.
- Military moving expenses and reservist travel expenses reduce AGI as adjustments.
- With M19 in place, the EITC combat-pay election picks whichever treatment yields the larger credit.
- Golden test vectors sourced from IRS Pub 3 examples.
- `ruff check . && mypy . && pytest` clean.

---

## Versioning & Release Trajectory

- ~~Promote to `0.2.0` after Phase 1 (structural hardening) is complete.~~ Done 2026-07-02.
- ~~Promote to `0.3.0` after Phase 2 (capability expansion) is complete.~~ Done 2026-07-02.
- Promote to `0.4.0` after Phase 4 (M20–M24) is complete.
- Promote to `0.5.0` after closing the remaining common-household gaps (the "missing 10%": e.g. additional standard deduction for age 65+/blind, refundable ACTC, $500 credit for other dependents, Additional Medicare Tax, dependent exemptions in state packs).
- Promote to `0.9.0` after a deep review of the entire codebase plus testing and patching of well-known/common edge cases.
- Promote to `1.0.0` after the codebase is packaged for easy installation on Linux and Windows.

---

## Milestone Dependency Graph

```
Phase 1 (sequential — each builds on the last):
  M12 (split main.py) → M13 (logging) → M14 (CSP fix) → M15 (pagination)

Phase 2 (after M12):
  M16 (matrix_lookup)

Phase 3 (after applicable dependencies):
  M17 (LTCG rates)           — independent, can start after M12
  M18 (SE tax)               — independent, can start after M12
  M19 (EITC)                 — depends on M16 + M18

Phase 4 (after Phase 1; M20 depends on M16):
  M20 (education credits)    — depends on M16 (matrix_lookup for phaseout tables)
  M21 (dependent care)       — independent, can start after M12
  M22 (NIIT)                 — independent, can start after M12 (simple formula rule)
  M23 (state credits)        — independent, can start after M12
  M24 (military provisions)  — core exclusion/adjustments after M12;
                               EITC combat-pay election depends on M19
```
