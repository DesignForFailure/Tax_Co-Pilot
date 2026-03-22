<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Hardening, QA & Auditability — Design Spec

**Goal:** Fix known bugs, harden input validation, close test coverage gaps, fix code quality issues, and complete the remaining Milestone 4 security/auditability items — in a single combined pass.

**Scope:** This is a hardening pass, not a feature milestone. Phases 1 and 2 add no new user-facing features — the app behaves identically except that invalid/malicious inputs now produce clean error responses instead of 500s or exploitable behavior. Phase 3 completes the remaining Milestone 4 (Security Hardening) items from ROADMAP.md, which includes two new internal endpoints (`GET /audit/verify`, `POST /rotate-key`) that are operational/admin tools, not end-user features.

**Priority order:** Bugs & errors > Quality > Auditability > Security hardening.

---

## Phase 1: Bug Fixes & Input Hardening

### 1a. SQL Injection in Encryption PRAGMA Statements

**Problem:** `encryption.py:340` and `:557` interpolate the user's password directly into SQL strings via f-strings (`f"PRAGMA key = '{password}'"` and `f"ATTACH DATABASE '{path}' AS encrypted KEY '{password}'"`). A password containing a single quote breaks execution or enables injection.

**Fix:** Encode the password as a hex key string. SQLCipher accepts `PRAGMA key = "x'<hex>'"` which avoids all quoting issues. Specifically:

```python
hex_key = password.encode("utf-8").hex()
conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
```

Apply the same pattern to the `ATTACH DATABASE ... KEY` statement in `_migrate_to_sqlcipher`.

**Files:** `app/services/encryption.py` (lines 340, 557)

### 1b. `tax_year` Validation Against Available Years

**Problem:** `calculate_submit` and `whatif_submit` accept any integer as `tax_year` and pass it directly to `_get_federal_pack(year)`, which constructs a filesystem path. An invalid year causes an unhandled `RulePackError` (500) and allows probing for directory existence. Separately, `calculate_form` calls `max(available_years)` which crashes with `ValueError` if the list is empty (fresh install with no rule packs).

**Fix:**
- In `calculate_submit` (line ~493) and `whatif_submit` (line ~677): after parsing `tax_year`, validate `tax_year in available_years` and raise `ValueError` if not.
- In `calculate_form` (line ~348): guard `max(available_years)` with a fallback: `default_year = max(available_years) if available_years else 2024`.

**Files:** `main.py` (lines 348, 493, 677)

### 1c. Unary Negation in Rule Expression Parser

**Problem:** `_eval_atom` in `calculator.py` does not handle a leading `-` on variable names. An expression like `"-x"` or `"-wages"` tries `Decimal("-wages")` which raises `InvalidOperation`. This blocks rule authors from writing negation expressions and produces opaque errors.

**Fix:** In `_eval_atom`, detect a leading `-` and return `-1 * self._eval_atom(expr[1:], variables)`. Similarly handle leading `+` (strip it). This is the standard recursive-descent approach for unary operators.

**Files:** `app/engine/calculator.py` (`_eval_atom` method, around line 582)

### 1d. `hybrid_factory` Consistency Across All DB Connections

**Problem:** Unencrypted connections use `sqlite3.Row` while encrypted connections use `hybrid_factory`. The `dict(row)` calls in `list_return_runs` and `get_return_run` produce integer-keyed dicts under `hybrid_factory` because `HybridRow.__iter__` yields values, not `(key, value)` pairs. This means enabling SQLCipher silently breaks the entire persistence layer.

**Fix:**
- Set `conn.row_factory = hybrid_factory` on **all** connection paths (unencrypted included), replacing `sqlite3.Row`.
- Change `PRAGMA table_info` access from `row[1]` to `row["name"]` (line 189).
- Verify `dict(row)` works correctly with `hybrid_factory` by adding a `__iter__` that yields `(key, value)` pairs, or change all `dict(row)` calls to `{k: row[k] for k in row.keys()}`.

**Files:** `app/services/database.py` (lines 130, 148, 158, 189), `app/services/encryption.py` (`HybridRow` class)

### 1e. URL-Encode Error Messages in `/unlock` Redirects

**Problem:** Exception messages in the `/unlock` POST handler are embedded in redirect URLs with only space-to-`+` substitution. Characters like `&`, `#`, `"`, or newlines in exception messages can corrupt the URL or enable header injection.

**Fix:** Replace all manual space-to-`+` substitutions and hardcoded `+`-delimited error strings with `urllib.parse.quote_plus(str(e)[:100])`. There are three redirect paths to fix: the `PasswordValidationError` handler (`.replace(" ", "+")`), the `ValueError` handler (hardcoded `f"Unlock+failed:+{str(e)[:50]}"`), and the generic `Exception` handler (same pattern). Import `urllib.parse` at the top of `main.py`.

**Files:** `main.py` (all three error redirect paths in `unlock_submit`, approximately lines 876-884)

### 1f. Upload Size Limits on `/import-returns` and `/restore`

**Problem:** Both endpoints call `await upload.read()` with no size check, allowing multi-gigabyte uploads that exhaust memory. The `/restore` SQLite magic-byte check is trivially bypassable (prepend 16 bytes to any payload). The `/import-returns` endpoint has no cap on entry count.

**Fix:**
- Add constants: `_MAX_IMPORT_BYTES = 10 * 1024 * 1024` (10 MB), `_MAX_RESTORE_BYTES = 100 * 1024 * 1024` (100 MB), `_MAX_IMPORT_ENTRIES = 1000`.
- In both endpoints, after `await upload.read()`, check `len(content) > limit` and return 400 if exceeded.
- In `/import-returns`, after parsing the JSON array, check `len(entries) > _MAX_IMPORT_ENTRIES`.
- In `/restore`, after the magic-byte check, write the uploaded bytes to a temp file and open it with `sqlite3.connect(temp_path)` + `PRAGMA integrity_check` to verify it's a real SQLite database, not just bytes starting with the magic header. If the integrity check fails, return 400 and delete the temp file. (Note: `sqlite3.Connection.deserialize()` requires Python 3.11.4+ with `SQLITE_ENABLE_DESERIALIZE`; the temp-file approach is more portable.)

**Files:** `main.py` (lines 914-947, 961-981)

### 1g. Input Sanitization Gaps

**Problem:** Multiple small input validation gaps:
- `tags` and `notes` in `/annotate` have no length cap (other text fields use `_form_str` with `_MAX_TEXT = 200`).
- `run_id` in `Content-Disposition` headers is embedded unsanitized.
- `/export-all` silently falls back to raw DB rows on deserialization failure, potentially leaking `_json` suffixed internal fields.

**Fix:**
- Cap `tags` via `_form_str(fd, "tags")` (200 chars). Cap `notes` at 2000 chars with a dedicated check.
- Sanitize `run_id` in all `Content-Disposition` headers: `re.sub(r"[^a-zA-Z0-9_-]", "", run_id)`.
- In `/export-all`, replace the silent `except Exception: hydrated.append(r)` fallback with: skip the corrupt entry and append an error marker `{"error": f"Failed to hydrate run {r.get('id', '?')}", "id": r.get("id")}`. Log a warning.

**Files:** `main.py` (lines 747, 761, 799, 891-893, 902-906)

---

## Phase 2: Test Coverage & Quality

### 2a. Route Coverage for Untested Endpoints

**Problem:** 6 routes have zero test coverage: `GET /` (dashboard), `GET /runs`, `GET /runs/{run_id}`, `GET /legal`, `GET /unlock`, `POST /unlock`.

**Fix:** Create `tests/test_route_coverage.py` with the sync `TestClient` pattern. Tests:
- `test_dashboard_empty` — `GET /` with no runs returns 200.
- `test_dashboard_with_run` — Create a run, `GET /` returns 200 with run data in body.
- `test_runs_list` — `GET /runs` returns 200.
- `test_run_detail_valid` — Create a run, `GET /runs/{id}` returns 200.
- `test_run_detail_invalid` — `GET /runs/nonexistent` returns 404 or handles gracefully.
- `test_legal_page` — `GET /legal` returns 200.
- `test_unlock_get` — `GET /unlock` returns 200.
- `test_unlock_post_empty_password` — `POST /unlock` with empty password redirects with error.

**Files:** Create `tests/test_route_coverage.py`

### 2b. Error Path Tests

**Problem:** Error branches on import, restore, annotate, delete, and calculate routes are untested. CSRF missing-cookie path (distinct from wrong-token) is not exercised.

**Fix:** Create `tests/test_error_paths.py`. Tests:
- `test_import_no_file` — `POST /import-returns` without file upload returns 400.
- `test_import_invalid_json` — Upload non-JSON content returns 400 with "Invalid JSON".
- `test_import_non_array` — Upload `{}` returns 400 with "Expected a JSON array".
- `test_restore_success` — Upload a real SQLite file, verify 303 redirect.
- `test_csrf_missing_cookie` — `POST /calculate` with form token but no cookie returns 400.
- `test_annotate_nonexistent_run` — `POST /runs/fake/annotate` doesn't crash (303 or 404).
- `test_delete_nonexistent_run` — `POST /runs/fake/delete` doesn't crash.
- `test_calculate_invalid_filing_status` — Submit `filing_status=invalid` returns 400.
- `test_import_size_limit` — Upload oversized content returns 400 (after Phase 1 fix).

**Files:** Create `tests/test_error_paths.py`

### 2c. `_parse_money` Unit Tests

**Problem:** `_parse_money` is the monetary input boundary for every dollar amount in the app. It has explicit rejection logic for scientific notation, excessive decimals, values over $1B, and leading `+`. None of this is tested.

**Fix:** Create `tests/test_parse_money.py`. Tests:
- Valid: `"75000"`, `"75000.00"`, `"0"`, `"-500"` (if negative allowed), `"999999999"`.
- Rejected: `"1e9"` (scientific notation), `"12.345"` (>2 decimals), `"1500000000"` (>$1B), `"+100"` (leading plus), `""` (empty), `"abc"` (non-numeric), `"12.34.56"` (multiple dots).

**Files:** Create `tests/test_parse_money.py`

### 2d. Security Header Regression Test

**Problem:** The `security_headers` middleware is never tested. A regression removing any header would go undetected.

**Fix:** Add a test in `test_route_coverage.py`:
- `test_security_headers_present` — `GET /legal` (simplest route), assert presence of: `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy`, `Content-Security-Policy`, `Cache-Control: no-store`.

**Files:** `tests/test_route_coverage.py`

### 2e. Deprecation Fix — `on_event("startup")` to Lifespan

**Problem:** `@app.on_event("startup")` is deprecated since FastAPI 0.93.0. It generates `DeprecationWarning` in every test run (visible in the 13 warnings).

**Fix:** Convert to the `lifespan` async context manager:

```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    _startup()
    yield

app = FastAPI(title="Tax Copilot", version="0.1.0", lifespan=lifespan)
```

Move the body of the current `startup()` function into `_startup()` (a plain sync function called from the lifespan). Remove the `@app.on_event("startup")` decorator.

**Note:** `TestClient` used as a context manager (`with TestClient(app) as c:`) triggers lifespan events automatically. Tests that instantiate `TestClient(app)` without the context manager still work because the `_ensure_db` fixture calls `init_db()` directly. Verify all existing tests pass after the migration.

**Files:** `main.py` (lines 275-309, and the `app = FastAPI(...)` declaration)

### 2f. DB Connection Safety

**Problem:** Every function in `database.py` follows `conn = get_connection(); conn.execute(...); conn.close()`. If any statement raises, `conn.close()` is never called, leaking file descriptors.

**Fix:** Wrap all function bodies with `contextlib.closing`:

```python
from contextlib import closing

def list_return_runs(...):
    with closing(get_connection()) as conn:
        ...
```

Apply to: `init_db`, `save_return_run`, `list_return_runs`, `get_return_run`, `delete_return_run`, `update_run_annotation`.

**Files:** `app/services/database.py` (all public functions)

---

## Phase 3: Auditability & Security Hardening

### 3a. Tamper-Evident Audit Traces (Hash Chaining)

**Problem:** `ReturnRun` is described as an "immutable sealed artifact" but there is no mechanism to detect post-hoc tampering. A modified database row would be indistinguishable from the original.

**Fix:**
- Add an `integrity_hash` field to `ReturnRun` (str, computed at creation time).
- The hash is `SHA-256(run_id + tax_year + input_snapshot_json + output_json + trace_json + rule_pack_checksum)`. This covers all substantive content.
- Add a `previous_hash` field (str, nullable) that references the `integrity_hash` of the chronologically previous run (ordered by `created_at` ASC, with `rowid` as tiebreaker), creating a hash chain. The first run has `previous_hash = ""`.
- Add a `verify_integrity(run: ReturnRun) -> bool` function that recomputes the hash and compares.
- Add a `GET /audit/verify` route that walks the chain and reports any broken links.
- Store `integrity_hash` and `previous_hash` in the DB schema (new columns with migration).

**Files:**
- `app/models/domain.py` — Add `integrity_hash` and `previous_hash` to `ReturnRun`.
- `app/services/database.py` — Schema migration for new columns. Update `save_return_run` to compute and store hashes. Add `verify_chain()` function.
- `main.py` — Add `GET /audit/verify` route.

### 3b. Key Rotation Procedure

**Problem:** There is no way to change the encryption password without manually re-encrypting the database. ROADMAP.md lists "key-management workflow and rotation procedures" as an open M4 item.

**Fix:**
- Add `GET /rotate-key` that renders a form with fields: `current_password`, `new_password`, `confirm_new_password`. Standard HTML form with CSRF token.
- Add `POST /rotate-key` that:
  1. Validates CSRF token.
  2. Verifies `new_password == confirm_new_password`.
  3. Verifies `current_password` matches `_cached_password`.
  4. Calls `rotate_key(current_password, new_password)`.
  5. Updates `_cached_password` via `set_cached_password(new_password)`.
  6. Redirects to `/` with a success flash (or query param `?rotated=1`).
- On any failure, redirect back to `GET /rotate-key?error=<url-encoded message>`.
- The `rotate_key` function in `encryption.py` uses SQLCipher's `PRAGMA rekey = "x'<hex>'"` for single-step re-encryption. If `PRAGMA rekey` is not available (non-SQLCipher build), return an error — Python Fernet encryption does not support in-place rotation.
- No two-phase token needed — the form is a single POST with CSRF protection (consistent with all other POST routes in the app). The password confirmation field prevents accidental mistyped keys.

**Files:**
- `app/services/encryption.py` — Add `rotate_key(old_password, new_password)` function.
- `main.py` — Add `GET /rotate-key` and `POST /rotate-key` routes.
- `app/templates/pages/rotate_key.html` — New template for the key rotation form.

### 3c. Password Cache Clearing

**Problem:** `_cached_password` in `database.py` is a module-level global that persists the plaintext password for the entire process lifetime. There is no way to clear it.

**Fix:**
- Add `clear_cached_password()` function that sets `_cached_password = None`.
- Call it on application shutdown (in the `lifespan` context manager's teardown phase).
- Document the trade-off: the password is in-memory during the session for functional reasons, but is cleared on shutdown.

**Files:** `app/services/database.py`, `main.py` (lifespan teardown)

### 3d. Explicit Cipher Parameters

**Problem:** `PRAGMA cipher_page_size` and `PRAGMA cipher` are never set. SQLCipher 4 defaults differ from SQLCipher 3. If the linked library version changes, the DB may become unreadable without explicitly pinned parameters.

**Fix:**
- After `PRAGMA key` and `PRAGMA kdf_iter`, explicitly set:
  - `PRAGMA cipher_page_size = 4096`
  - `PRAGMA cipher_compatibility = 4` (or appropriate version)
- Add a comment block documenting the parameter order requirement (key → kdf_iter → cipher params → first read).

**Files:** `app/services/encryption.py` (lines 340-352)

### 3e. CSRF Token Rotation After Authentication

**Problem:** The CSRF token minted before `/unlock` persists across the privilege boundary (locked → unlocked). Standard practice is to rotate on authentication events.

**Fix:** In the success path of `unlock_submit`, set a new CSRF cookie on the redirect response:

```python
resp = RedirectResponse(url="/", status_code=303)
resp.set_cookie("csrf", secrets.token_urlsafe(32), httponly=True, samesite="strict")
return resp
```

**Files:** `main.py` (line ~873)

### 3f. Make `pip-audit` Blocking in CI

**Problem:** `pip-audit` runs with `continue-on-error: true`, so known-vulnerable dependencies don't fail the build.

**Fix:** Remove `continue-on-error: true` from the `pip-audit` step in `.github/workflows/ci.yml`. Add `--desc` flag for human-readable output. If there are legitimate exceptions (e.g., a vulnerability with no fix yet), use `pip-audit --ignore-vuln PYSEC-XXXX` with a comment explaining why.

**Files:** `.github/workflows/ci.yml` (line 57-59)

---

## Out of Scope

These were identified during the audit but are deferred to future passes:

- **EITC support** — Requires multi-dimensional lookup engine changes.
- **`main.py` decomposition** — The file is ~1000 lines; splitting into route modules is valuable but is a refactor, not a bug fix.
- **CI Python version matrix** — CI tests 3.11/3.12 but local dev uses 3.14. Aligning this is a CI task.
- **Coverage threshold enforcement** — Adding `--cov-fail-under` to pytest is valuable but is a process change.
- **Rule expression dot-notation validation** — The validator tokenizes on dots while the evaluator uses full dotted keys. Low-severity precision issue for a future pass.
- **`_migrate_to_python_encryption` dead code** — `PythonEncryptionProvider.create_connection` raises unconditionally; the migration path is unreachable. Cleanup deferred.
