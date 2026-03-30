<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Implementation Plan: Phase 1 — Structural Hardening (M12–M15)

**Created:** 2026-03-29
**Scope:** M12 (split main.py), M13 (logging), M14 (CSP/inline removal), M15 (pagination)
**Execution order:** Sequential — each milestone builds on the prior.

---

## M12: Break Up `main.py` Monolith

### Step 1: Create package structure

Create the following empty files:

```
app/routes/__init__.py
app/routes/calculate.py
app/routes/navigation.py
app/routes/runs.py
app/routes/import_export.py
app/routes/encryption.py
app/routes/rule_packs.py
app/route_helpers/__init__.py
app/route_helpers/csrf.py
app/route_helpers/db_state.py
app/route_helpers/form_parsing.py
app/route_helpers/pack_cache.py
```

All files get SPDX header + module docstring per governance rules.

### Step 2: Extract `route_helpers/form_parsing.py`

Move from `main.py`:
- **Constants** (lines 472–477, 483): `_MAX_TEXT`, `_MAX_INDEXED_ENTRIES`, `_MAX_IMPORT_BYTES`, `_MAX_RESTORE_BYTES`, `_MAX_IMPORT_ENTRIES`, `_MAX_NOTES`, `_IDX_RE`
- **`_parse_money()`** (lines 239–294)
- **`_sanitize_filename()`** (lines 480–482)
- **`_form_str()`** (lines 486–491)
- **`_form_money()`** (lines 494–495)
- **`_collect_indices()`** (lines 567–578)
- **`_parse_w2s()`** (lines 581–612)
- **`_parse_1099ints()`** (lines 615–633)
- **`_parse_1099divs()`** (lines 634–654)
- **`_parse_1099bs()`** (lines 655–676)
- **`_parse_taxpayer()`** (lines 677–698)
- **`_taxpayer_has_form_data()`** (lines 699–708)
- **`_parse_tax_input_from_form()`** (lines 711–761)
- **`_parse_rule_form()`** (lines 498–564)

Imports needed in this module:
- `decimal.Decimal`, `re`, `collections.abc.Mapping`
- `starlette.datastructures.FormData`
- Domain models: `W2Data`, `Form1099INTData`, `Form1099DIVData`, `Form1099BData`, `Taxpayer`, `TaxpayerRole`, `TaxReturnInput`, `FilingStatus`, `AdjustmentsData`, `ItemizedDeductionData`

Make all function names **public** (drop leading underscore) since they're now a module API. Update all call sites.

**Critical dependency:** `_parse_tax_input_from_form()` at line 714 directly references the module-level `available_years` global to validate `tax_year`. After extraction, this function must either:
- Accept `available_years` as a parameter (preferred — keeps `form_parsing` free of cross-module state), or
- Import `available_years` from `pack_cache.py` (creates a coupling between form parsing and cache)

Choose the parameter approach: change the signature to `parse_tax_input_from_form(fd: FormData, available_years: Sequence[int]) -> TaxReturnInput` and pass the value from the calling route.

### Step 3: Extract `route_helpers/csrf.py`

Move from `main.py`:
- **`_get_csrf_token()`** (lines 297–306)
- **`_verify_csrf()`** (lines 309–318)

Imports: `secrets`, `fastapi.Request`, `starlette.datastructures.FormData`

Make public: `get_csrf_token()`, `verify_csrf()`.

### Step 4: Extract `route_helpers/pack_cache.py`

Move from `main.py`:
- **`_federal_cache`** (line 178) — module-level dict
- **`_state_cache`** (line 179) — module-level dict
- **`available_years`** (line 231) — module-level list, populated at startup
- **`FEDERAL_PACKS_DIR`** (line 174)
- **`STATE_PACKS_DIR`** (line 175)
- **`_bust_pack_cache()`** (lines 182–188)
- **`_discover_available_years()`** (lines 191–199)
- **`_get_federal_pack()`** (lines 202–207)
- **`_get_state_packs()`** (lines 210–222)
- **`_available_states_by_year()`** (lines 225–228)
- **Pre-warm logic** (lines 234–236) — expose as `warm_caches()` function

Imports: `pathlib.Path`, `app.engine.rule_loader.RulePack`

Make public (drop underscores).

### Step 5: Extract `route_helpers/db_state.py`

Move from `main.py`:
- **`_startup()`** (lines 331–363)
- **`_database_locked()`** (lines 366–378)
- **`_locked_database_response()`** (lines 381–388)
- **`_load_run_from_row()`** (lines 321–328)
- **`_load_latest_run()`** (lines 391–396)

Imports: `json`, `decimal.Decimal`, `app.services.database.*`, `app.services.encryption.*`, `app.models.domain.ReturnRun`, `app.config.encryption_config`

Make public. `startup()` will be called from the lifespan in `main.py`.

### Step 6: Extract route modules

Each route module follows this pattern:

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""<Module description>."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
# ... other imports

from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.db_state import locked_database_response, load_run_from_row
# ... other helper imports

router = APIRouter()

@router.get("/path", response_class=HTMLResponse)
def handler(request: Request) -> Response:
    ...
```

**`app/routes/calculate.py`** — router prefix: none (paths: `/`, `/dashboard`, `/calculate`, `/whatif`)

Handlers to move:
- `home()` (lines 399–429) — `GET /`
- `dashboard()` (lines 432–445) — `GET /dashboard`
- `calculate_form()` (lines 448–468) — `GET /calculate`
- `calculate_submit()` (lines 767–836) — `POST /calculate`
- `whatif_form()` (lines 950–958) + `whatif_submit()` (lines 961–989) — `GET /whatif`, `POST /whatif`

Dependencies: `pack_cache` (get_federal_pack, get_state_packs, available_years, available_states_by_year), `form_parsing` (parse_tax_input_from_form, form_str), `db_state` (locked_database_response, load_run_from_row, load_latest_run, database_locked), `csrf` (get_csrf_token, verify_csrf), `CalculationEngine`, `WhatIfEngine`, `save_return_run`, `list_return_runs`, `list_rule_packs`.

Template access: Store `templates` and `BASE_DIR` on `app.state` during lifespan, access via `request.app.state.templates`.

**`app/routes/navigation.py`** — router prefix: none (paths: `/legal`)

Handlers to move:
- `legal_notices()` (lines 1131–1134) — `GET /legal`

Dependencies: templates only. This is a static page with no service dependencies.

**`app/routes/runs.py`** — router prefix: none

Handlers to move:
- `past_runs()` (lines 838–851) — `GET /runs`
- `compare_runs()` (lines 858–912) — `GET /runs/compare`
- `view_run()` (lines 915–930) — `GET /runs/{run_id}`
- `view_run_audit()` (lines 933–944) — `GET /runs/{run_id}/audit`
- `view_run_forms()` (lines 1073–1089) — `GET /runs/{run_id}/forms`
- `delete_run()` (lines 1119–1128) — `POST /runs/{run_id}/delete`
- `annotate_run()` (lines 1203–1218) — `POST /runs/{run_id}/annotate`

Dependencies: `db_state` (locked_database_response, load_run_from_row), `csrf`, `list_return_runs`, `get_return_run`, `delete_return_run`, `update_run_annotation`, `generate_audit_html`, `map_return_run`.

**`app/routes/import_export.py`** — router prefix: none

Handlers to move:
- `import_csv_form()` (lines 995–1002) — `GET /import-csv`
- `import_csv_submit()` (lines 1005–1025) — `POST /import-csv`
- `export_run_json()` (lines 1031–1049) — `GET /runs/{run_id}/export/json`
- `export_run_html()` (lines 1052–1067) — `GET /runs/{run_id}/export/html`
- `export_run_forms()` (lines 1092–1113) — `GET /runs/{run_id}/export/forms`
- `export_all_runs()` (lines 1221–1239) — `GET /export-all`
- `import_returns()` (lines 1242–1292) — `POST /import-returns`
- `backup_database()` (lines 1295–1309) — `GET /backup`
- `restore_database()` (lines 1312–1359) — `POST /restore`

Dependencies: `db_state`, `csrf`, `form_parsing` (sanitize_filename, MAX constants), `_import_csv`, `generate_audit_html`, `map_return_run`, database functions, `pack_cache` (federal_cache for checksum verification).

**`app/routes/encryption.py`** — router prefix: none

Handlers to move:
- `unlock_form()` (lines 1137–1145) — `GET /unlock`
- `unlock_submit()` (lines 1148–1200) — `POST /unlock`
- `rotate_key_form()` (lines 1362–1371) — `GET /rotate-key`
- `rotate_key_submit()` (lines 1374–1419) — `POST /rotate-key`
- `audit_verify()` (lines 1422–1434) — `GET /audit/verify`

Dependencies: `csrf`, `db_state`, encryption service functions, `verify_chain`.

**`app/routes/rule_packs.py`** — router prefix: none

Handlers to move (all 16 handlers from lines 1443–1739):
- `rule_packs_list()`, `rule_packs_create()`, `rule_packs_import_form()`, `rule_packs_import_post()`
- `rule_pack_detail()`, `rule_pack_validate()`, `rule_pack_clone()`, `rule_pack_delete()`, `rule_pack_export()`
- `rule_add_form()`, `rule_add_submit()`, `rule_edit_form()`, `rule_save_submit()`, `rule_delete_submit()`

**Important ordering note** (from main.py lines 1437–1440): Literal routes (`/rule-packs/create`, `/rule-packs/import`) must be registered before parameterized routes (`/rule-packs/{jurisdiction}/...`). Maintain this order in the module.

Dependencies: `csrf`, `form_parsing` (parse_rule_form, form_str), `pack_cache` (bust_pack_cache, available_years, get_federal_pack, get_state_packs), rule_pack_editor service functions.

### Step 7: Rewrite `main.py`

After extraction, `main.py` should contain only:
1. SPDX header + docstring
2. Imports: FastAPI, middleware, lifespan
3. `_lifespan()` async context manager — calls `startup()` from `db_state`, `warm_caches()` from `pack_cache`, stores `templates` and `BASE_DIR` on `app.state`
4. `app = FastAPI(lifespan=_lifespan)`
5. `TrustedHostMiddleware`
6. `security_headers` middleware
7. `app.include_router()` calls for all 6 route modules
8. ValueError exception handler

Target: under 100 lines.

### Step 8: Update `app/routes/__init__.py`

Export all routers for clean importing:
```python
from app.routes.calculate import router as calculate_router
from app.routes.navigation import router as navigation_router
from app.routes.runs import router as runs_router
from app.routes.import_export import router as import_export_router
from app.routes.encryption import router as encryption_router
from app.routes.rule_packs import router as rule_packs_router
```

### Step 9: Run quality gates

```bash
ruff check . && mypy . && pytest
```

All 307 tests must pass. Fix any import errors, missing references, or type issues.

### Step 10: Verify every route manually

Start the app with `./run.sh` and verify:
- Home page loads
- Calculate form renders, submit works
- Dashboard shows result
- Runs list works
- Run detail, audit trace, forms view work
- What-if form and submit work
- CSV import page works
- Export JSON/HTML downloads work
- Rule packs list, detail, editor work
- Unlock page renders (if encrypted)
- Rotate key page renders

### Step 11: Update README.md repository structure tree

Run the find command from CLAUDE.md and update the tree to include all new files.

---

## M13: Structured Logging

**Depends on:** M12 complete (routes are split, so logging is added to the right modules).

### Step 1: Create `app/log.py`

```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Centralized logging configuration."""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

def configure(*, log_dir: Path | None = None) -> None:
    """Configure application-wide logging.

    Uses a structured plaintext format: ``timestamp level module message``.
    All modules should use ``logging.getLogger("tax_copilot.<module>")``.
    """
    level_name = os.environ.get("TAX_COPILOT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger("tax_copilot")
    if root.handlers:
        return  # Already configured (guard against double-init in tests)
    root.setLevel(level)

    # Console handler (stderr) — structured plaintext
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-8s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    console = logging.StreamHandler()
    console.setFormatter(fmt)
    root.addHandler(console)

    # Optional rotating file handler
    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            log_dir / "tax_copilot.log",
            maxBytes=10 * 1024 * 1024,  # 10 MB
            backupCount=3,
        )
        fh.setFormatter(fmt)
        root.addHandler(fh)
```

**Note:** The format is structured plaintext, not JSON. This keeps the log human-readable for a local-first desktop app. If JSON logging is needed later (e.g., for log aggregation), swap the `Formatter` for `python-json-logger` or similar — the logger hierarchy stays the same.

### Step 2: Wire into startup

In `app/route_helpers/db_state.py` `startup()`:
```python
import app.log
app.log.configure(log_dir=BASE_DIR / "data")
logger = logging.getLogger("tax_copilot.startup")
logger.info("Tax Co-Pilot starting, version=%s", __version__)
```

### Step 3: Add loggers to service modules

**`app/services/encryption.py`:**
- Top of file: `logger = logging.getLogger("tax_copilot.encryption")`
- `get_password_from_keyring()` line 276: `except Exception:` → `logger.warning("Keyring read failed", exc_info=True); return None`
- `set_password_in_keyring()` line 299: `except Exception:` → `logger.warning("Keyring write failed", exc_info=True); return False`
- `detect_encryption_state()`: `logger.debug("Database encryption state: %s", state.name)`
- `rotate_key()`: `logger.info("Key rotation started")` / `logger.info("Key rotation complete")` / `logger.error("Key rotation failed", exc_info=True)`
- `migrate_to_encrypted()`: `logger.info("Migration to encrypted started")` / success / failure

**`app/services/database.py`:**
- Top of file: `logger = logging.getLogger("tax_copilot.database")`
- `init_db()`: `logger.info("Database initialized at %s", DB_PATH)`
- `save_return_run()`: `logger.info("Run saved: id=%s year=%d status=%s", run_id, tax_year, filing_status)`
- `delete_return_run()`: `logger.info("Run deleted: id=%s", run_id)`
- `verify_chain()`: `logger.info("Hash chain verification: %s", "pass" if ok else "FAIL at row %s")`
- JSON decode errors in hash verification: `logger.error("Hash verification JSON error at row %s", row_id, exc_info=True)`

**`app/services/csv_import.py`:**
- `logger = logging.getLogger("tax_copilot.csv_import")`
- After parsing: `logger.info("CSV import: type=%s records=%d errors=%d", record_type, len(records), len(errors))`

### Step 4: Add loggers to route modules

**`app/routes/encryption.py`:**
- `unlock_submit()`: `logger.info("Database unlock attempt")` / `logger.info("Database unlocked successfully")` / `logger.warning("Database unlock failed: %s", reason)`
- `rotate_key_submit()`: `logger.info("Key rotation requested")` / success / failure

**`app/routes/import_export.py`:**
- `backup_database()`: `logger.info("Database backup downloaded")`
- `restore_database()`: `logger.info("Database restore: started")` / success / failure
- `import_returns()`: `logger.info("Bulk import: imported=%d skipped=%d errors=%d", ...)`

**`app/route_helpers/csrf.py`:**
- `verify_csrf()` on failure: `logger.warning("CSRF validation failed for %s %s", request.method, request.url.path)`

### Step 5: Fix all silent exception swallowing

Search the entire codebase for `except Exception` and `except:` — every occurrence must have a `logger` call. No silent swallowing.

Specific locations from research:
- `encryption.py:276` — already covered above
- `encryption.py:299` — already covered above
- `encryption.py:211-224` — already covered above
- `database.py` hash paths — already covered above
- Route handlers with `except Exception as e` — add `logger.exception("...")` before returning error response

### Step 6: Run quality gates

```bash
ruff check . && mypy . && pytest
```

### Step 7: Verify logging output

Start app, perform these actions, verify log lines appear:
1. App startup → version + encryption state logged
2. Run a calculation → run saved log
3. Delete a run → run deleted log
4. Trigger a CSRF failure (e.g., curl POST without token) → warning logged

### Step 8: Update README.md tree

Add `app/log.py` and `data/` directory to tree.

---

## M14: Remove `unsafe-inline` from CSP

**Depends on:** M12 complete (templates reference stable paths), M13 complete (logging available for CSP violation debugging).

### Step 1: Create static directory structure

```
app/static/
├── css/
│   └── main.css
└── js/
    ├── theme.js
    ├── forms.js
    ├── submit-guard.js
    ├── compare.js
    └── rule-editor.js
```

### Step 2: Extract CSS

**Source:** `app/templates/layouts/base.html` lines 20–738 (the entire `<style>...</style>` block).

1. Copy the CSS content (between the `<style>` and `</style>` tags) into `app/static/css/main.css`.

2. Add utility classes at the end of `main.css` for every `style=""` attribute found in templates:

   ```css
   /* Utility classes — replace inline style="" attributes */
   .mb-0 { margin-bottom: 0; }
   .mb-4 { margin-bottom: 4px; }
   .mb-8 { margin-bottom: 8px; }
   .mb-10 { margin-bottom: 10px; }
   .mb-12 { margin-bottom: 12px; }
   .mb-14 { margin-bottom: 14px; }
   .mt-8 { margin-top: 8px; }
   .mt-10 { margin-top: 10px; }
   .mt-12 { margin-top: 12px; }
   .mt-18 { margin-top: 18px; }
   .mt-20 { margin-top: 20px; }
   .mt-22 { margin-top: 22px; }
   .mt-28 { margin-top: 28px; }
   .m-0 { margin: 0; }
   .text-red { color: var(--red); }
   .text-green { color: var(--green); }
   .text-accent { color: var(--accent); }
   .text-2xl { font-size: 2rem; }
   .text-xs { font-size: 12px; }
   .text-sm-alt { font-size: 13px; }
   .max-w-220 { max-width: 220px; }
   .w-52 { width: 52px; }
   .flex-between { display: flex; justify-content: space-between; gap: 16px; flex-wrap: wrap; }
   .flex-end { justify-content: flex-end; }
   .inline { display: inline; }
   .resize-v { resize: vertical; }
   .border-dim { border-color: var(--border); }
   .hr-dim { border-color: var(--border); margin: 20px 0; }
   .recommendation-box { margin-top: 20px; border-left: 4px solid var(--accent); padding-left: 12px; }
   .text-1rem { font-size: 1rem; }
   .pl-20 { padding-left: 20px; }
   ```

   Exact classes depend on the inline styles found. Create only the classes actually needed.

3. Replace the `<style>...</style>` block in `base.html` with:
   ```html
   <link rel="stylesheet" href="/static/css/main.css">
   ```

### Step 3: Extract JavaScript

**`app/static/js/theme.js`:**
- Source: `base.html` lines 8–18 (early theme init) + lines 784–827 (toggle handler)
- The early init script must run before body paint. Place a synchronous `<script src="/static/js/theme.js"></script>` in `<head>` (no `defer` or `async` attributes) so the browser blocks rendering until the script executes.
- In `theme.js`, the first lines execute immediately (read `localStorage` and set `data-theme` on `<html>` to prevent flash of wrong theme). The toggle handler wraps in `DOMContentLoaded`.

**`app/static/js/submit-guard.js`:**
- Source: `base.html` lines 829–836 (form submit button disable)
- Wrap in `DOMContentLoaded` listener.

**`app/static/js/forms.js`:**
- Source: `calculate.html` lines 234–287 AND `whatif.html` lines 274–326
- These are nearly identical dynamic form row generators. Deduplicate into one module.
- Functions: `addRow(prefix, section)`, `removeRow(button)`, `updateIndices(section)`
- Read configuration from `data-*` attributes on the section containers instead of inline template variables.

**`app/static/js/compare.js`:**
- Source: `runs.html` lines 112–148
- Functions: `updateCompare()`, `compareSelected()`

**`app/static/js/rule-editor.js`:**
- Source: `rule_editor.html` line 249+
- Function: toggle visibility of rule-type-specific form sections.

### Step 4: Update all templates

**`base.html`:**
- Remove `<style>` block → replaced by `<link>` (Step 2)
- Remove all `<script>` blocks → replaced by `<script src="">` tags
- Place `theme.js` in `<head>` (must run before paint)
- Place `submit-guard.js` before `</body>`
- Add `{% block extra_scripts %}{% endblock %}` before `</body>` for page-specific scripts

**`calculate.html`:**
- Remove `<script>` block
- Add in `{% block extra_scripts %}`: `<script src="/static/js/forms.js"></script>`
- Replace `style="color: var(--red);"` → `class="text-red"`
- Replace `style="margin-bottom:12px;"` → `class="mb-12"`

**`whatif.html`:**
- Remove `<script>` block
- Add `<script src="/static/js/forms.js"></script>` in extra_scripts
- Replace all inline styles with utility classes

**`runs.html`:**
- Remove `<script>` block
- Add `<script src="/static/js/compare.js"></script>` in extra_scripts
- Replace all inline styles with utility classes

**`rule_editor.html`:**
- Remove `<script>` block
- Add `<script src="/static/js/rule-editor.js"></script>` in extra_scripts

**`dashboard.html`:**
- Replace all `style=""` attributes (lines 44, 137, 189, 196, 223) with utility classes

**`home.html`:**
- Replace `style="margin-bottom: 4px;"` → `class="mb-4"`

**`import_csv.html`:**
- Replace all 7 inline style attributes with utility classes

**`legal.html`:**
- Replace all inline styles with utility classes

**`run_compare.html`:**
- Replace all inline styles with utility classes

### Step 5: Mount static files in `main.py`

```python
from fastapi.staticfiles import StaticFiles
app.mount("/static", StaticFiles(directory=BASE_DIR / "app" / "static"), name="static")
```

Place this **after** router includes but **before** the app is served, so static files don't shadow route paths.

### Step 6: Update CSP

In `main.py` (the `_CSP` constant or security headers middleware):

Change:
```
script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';
```

To:
```
script-src 'self'; style-src 'self';
```

### Step 7: Handle dynamic template data in JS

Some `<script>` blocks contain Jinja2 template variables (e.g., `{{ available_years }}`). These must be passed via `data-*` attributes instead:

```html
<!-- In template -->
<div id="form-config" data-years="{{ available_years | tojson }}" data-states="{{ states | tojson }}"></div>

<!-- In JS -->
const config = document.getElementById('form-config');
const years = JSON.parse(config.dataset.years);
```

Audit each extracted script for Jinja2 template variables and convert them to this pattern.

### Step 8: Run quality gates

```bash
ruff check . && mypy . && pytest
```

### Step 9: Visual verification

Start app and verify every page:
- [ ] Home — layout, nav, footer correct
- [ ] Dashboard — styling matches pre-change
- [ ] Calculate — form renders, dynamic rows work, submit works
- [ ] What-if — form renders, dynamic rows work, submit works
- [ ] Runs — table renders, comparison checkboxes work, delete works
- [ ] Audit trace — trace table renders
- [ ] Forms view — form mapping renders
- [ ] Rule packs — list, detail, editor all render
- [ ] Import CSV — form renders
- [ ] Unlock — form renders
- [ ] Rotate key — form renders
- [ ] Legal — page renders
- [ ] Theme toggle — dark/light mode persists across page loads
- [ ] No browser console errors (check DevTools)

### Step 10: Update README.md tree

Add `app/static/` directory and all files.

---

## M15: Paginate Run Listings

**Depends on:** M12 complete (routes split, so changes go to `app/routes/runs.py`).

### Step 1: Add pagination to `list_return_runs()`

In `app/services/database.py`, modify:

```python
def list_return_runs(
    tax_year: int | None = None,
    *,
    page: int = 1,
    page_size: int = 25,
) -> tuple[list[dict], int]:
    """Return (runs, total_count) with server-side pagination.

    Args:
        tax_year: Optional filter by tax year.
        page: 1-based page number.
        page_size: Runs per page. Use 0 for count-only (returns empty list).

    Returns:
        Tuple of (list of run dicts, total count of matching runs).
    """
    page = max(1, page)
    page_size = max(0, page_size)
    offset = (page - 1) * page_size

    where = "WHERE tax_year = ?" if tax_year is not None else ""
    params: tuple = (tax_year,) if tax_year is not None else ()

    with closing(get_connection()) as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM return_runs {where}", params
        ).fetchone()
        total = count_row[0] if count_row else 0

        if page_size == 0:
            return [], total

        rows = conn.execute(
            f"SELECT * FROM return_runs {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, page_size, offset),
        ).fetchall()
        return [dict(r) for r in rows], total
```

### Step 2: Add `count_return_runs()` convenience function

```python
def count_return_runs(tax_year: int | None = None) -> int:
    """Return total number of saved runs."""
    _, total = list_return_runs(tax_year=tax_year, page_size=0)
    return total
```

### Step 3: Update `/runs` route

In `app/routes/runs.py`:

```python
import math

@router.get("/runs", response_class=HTMLResponse)
def past_runs(request: Request) -> Response:
    locked = locked_database_response()
    if locked is not None:
        return locked

    page_str = request.query_params.get("page", "1")
    try:
        page = max(1, int(page_str))
    except ValueError:
        page = 1

    page_size = 25
    runs, total = list_return_runs(page=page, page_size=page_size)
    total_pages = max(1, math.ceil(total / page_size))
    page = min(page, total_pages)  # Clamp to valid range

    csrf = get_csrf_token(request)
    resp = templates.TemplateResponse(request, "pages/runs.html", {
        "runs": runs,
        "csrf": csrf,
        "page": page,
        "total_pages": total_pages,
        "total_count": total,
    })
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp
```

### Step 4: Update home page

In `app/routes/calculate.py` (or wherever `home()` lives), replace `len(list_return_runs())` with `count_return_runs()`.

### Step 5: Update `export_all_runs()`

In `app/routes/import_export.py`, `export_all_runs()` needs all runs. Use a direct query or call with a very large page_size:

```python
def export_all_runs(...):
    # Need all runs for export — use direct query
    all_runs, _ = list_return_runs(page=1, page_size=999_999)
    ...
```

Or add a `list_all_return_runs()` that omits LIMIT (wrapper that calls the old behavior).

### Step 6: Update `runs.html` template

Add pagination controls below the table:

```html
{% if total_pages > 1 %}
<nav class="pagination" aria-label="Run list pages">
    <span class="text-dim">Showing {{ (page - 1) * 25 + 1 }}–{{ [page * 25, total_count] | min }} of {{ total_count }} runs</span>
    <div class="pagination-controls">
        {% if page > 1 %}
            <a href="/runs?page={{ page - 1 }}" class="btn btn-sm btn-outline">← Previous</a>
        {% else %}
            <span class="btn btn-sm btn-outline" aria-disabled="true" style="opacity:0.4;">← Previous</span>
        {% endif %}

        <span class="pagination-info">Page {{ page }} of {{ total_pages }}</span>

        {% if page < total_pages %}
            <a href="/runs?page={{ page + 1 }}" class="btn btn-sm btn-outline">Next →</a>
        {% else %}
            <span class="btn btn-sm btn-outline" aria-disabled="true" style="opacity:0.4;">Next →</span>
        {% endif %}
    </div>
</nav>
{% endif %}
```

Note: after M14, replace the inline `style="opacity:0.4;"` with a utility class (e.g., `.opacity-40`).

Add pagination CSS to `main.css`:
```css
.pagination { display: flex; justify-content: space-between; align-items: center; margin-top: 16px; padding-top: 16px; border-top: 1px solid var(--border); }
.pagination-controls { display: flex; align-items: center; gap: 12px; }
.pagination-info { font-size: 14px; color: var(--text-dim); }
```

### Step 7: Update tests

Add to test suite (new file `tests/test_pagination.py` or extend existing):

```python
def test_list_return_runs_pagination():
    """Paginated query returns correct subset."""
    # Create 30 runs
    # Query page=1, page_size=10 → 10 results, total=30
    # Query page=3, page_size=10 → 10 results, total=30
    # Query page=4, page_size=10 → 0 results, total=30

def test_list_return_runs_count_only():
    """page_size=0 returns count without data."""
    # Create 5 runs
    # Query page_size=0 → [], 5

def test_list_return_runs_default_unchanged():
    """Default call returns first page of 25."""
    # Backward compatibility

def test_runs_route_pagination():
    """GET /runs?page=N returns correct page."""
    # Integration test with httpx TestClient

def test_runs_route_invalid_page():
    """GET /runs?page=abc defaults to page 1."""

def test_runs_route_negative_page():
    """GET /runs?page=-1 defaults to page 1."""
```

### Step 8: Update callers

The return type changes from `list[dict]` to `tuple[list[dict], int]`. Every call site must be updated. Known callers (as of 2026-03-29):

**Application code (in `main.py`, post-M12 in route modules):**
- `_load_latest_run()` (line 393) — `runs = list_return_runs()` → `runs, _ = list_return_runs(page=1, page_size=1)`; only needs the newest run
- `home()` (line 410) — `recent_runs = list_return_runs()` → use `count_return_runs()` for count, `list_return_runs(page=1, page_size=5)` for the 5 recent runs shown on home
- `past_runs()` (line 844) — already covered in Step 3 above
- `export_all_runs()` (line 1227) — already covered in Step 5 above

**Test files:**
- `tests/test_route_coverage.py` lines 80, 344, 361, 387, 400 — all do `runs = list_return_runs()` or `{run["id"] for run in list_return_runs()}`; update to `runs, _ = list_return_runs()` or `runs, _ = list_return_runs(); {run["id"] for run in runs}`
- `tests/test_milestone6_routes.py` lines 64, 307 — `runs = list_return_runs()` → `runs, _ = list_return_runs()`
- `tests/test_multi_year.py` line 284 — same pattern
- `tests/test_forms.py` lines 474, 491 — same pattern
- `tests/test_data_mgmt.py` lines 40, 90 — same pattern

### Step 9: Run quality gates

```bash
ruff check . && mypy . && pytest
```

### Step 10: Update README.md tree

If any new test files were added.

---

## Verification Checklist (All of Phase 1)

After all four milestones are complete:

- [ ] `main.py` is under 100 lines
- [ ] All routes respond identically to pre-refactor behavior
- [ ] `app/log.py` exists and logging is active
- [ ] No `except Exception` without a logger call
- [ ] `app/static/css/main.css` exists, zero inline `<style>` blocks in templates
- [ ] `app/static/js/` exists, zero inline `<script>` blocks in templates
- [ ] CSP header contains no `'unsafe-inline'`
- [ ] `/runs` shows 25 per page with pagination controls
- [ ] `ruff check . && mypy . && pytest` — all tests pass, zero lint, zero type errors
- [ ] README.md tree is updated
- [ ] Theme toggle, dynamic form rows, comparison checkboxes all work
- [ ] No circular imports between route modules, helpers, or services
