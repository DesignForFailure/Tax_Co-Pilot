# Hardening, QA & Auditability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix known bugs, harden input validation, close test coverage gaps, and complete remaining Milestone 4 security/auditability items in a single combined pass.

**Architecture:** Three sequential phases. Phase 1 fixes critical bugs and input validation. Phase 2 adds test coverage and code quality improvements. Phase 3 adds tamper-evident audit traces, key rotation, and security hardening. Each task is independently committable.

**Tech Stack:** Python 3.11+, FastAPI, SQLite, pysqlcipher3, Pydantic v2, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/services/encryption.py` | Modify | Fix PRAGMA injection, add `HybridRow` dict support, add cipher params, add `rotate_key()` |
| `app/services/database.py` | Modify | Fix `hybrid_factory` usage, add `closing()`, add `clear_cached_password()`, hash chain columns, `verify_chain()` |
| `app/engine/calculator.py` | Modify | Add unary negation support in `_eval_atom` |
| `main.py` | Modify | Fix `tax_year` validation, URL-encode errors, upload limits, sanitize inputs, lifespan migration, new routes (`/audit/verify`, `/rotate-key`) |
| `app/models/domain.py` | Modify | Add `integrity_hash` and `previous_hash` fields to `ReturnRun` |
| `app/templates/pages/rotate_key.html` | Create | Key rotation form template |
| `tests/test_route_coverage.py` | Create | Tests for untested routes + security headers |
| `tests/test_error_paths.py` | Create | Tests for error branches and edge cases |
| `tests/test_parse_money.py` | Create | Unit tests for `_parse_money` |
| `.github/workflows/ci.yml` | Modify | Make `pip-audit` blocking |

---

## Phase 1: Bug Fixes & Input Hardening

### Task 1: Fix SQL Injection in Encryption PRAGMA Statements

**Files:**
- Modify: `app/services/encryption.py:340,557`

- [ ] **Step 1: Write test for password with special characters**

In `tests/test_encryption.py`, add a test that a password containing a single quote can be used (this exercises the PRAGMA path without needing a real encrypted DB — just verify the hex encoding helper):

```python
def test_hex_key_encoding() -> None:
    """Password with special chars encodes cleanly for PRAGMA key."""
    from app.services.encryption import _hex_encode_key

    assert _hex_encode_key("simple") == "73696d706c65"
    assert _hex_encode_key("it's a secret") == "69742773206120736563726574"
    # No quotes in hex output
    result = _hex_encode_key("pass'word\"test")
    assert "'" not in result
    assert '"' not in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_encryption.py::test_hex_key_encoding -v`
Expected: FAIL with `ImportError: cannot import name '_hex_encode_key'`

- [ ] **Step 3: Add `_hex_encode_key` helper and fix PRAGMA statements**

In `app/services/encryption.py`, add the helper function after the `hybrid_factory` function (around line 78):

```python
def _hex_encode_key(password: str) -> str:
    """Encode password as hex for SQLCipher PRAGMA key.

    SQLCipher accepts hex-encoded keys via: PRAGMA key = "x'<hex>'"
    This avoids SQL injection from passwords containing quotes.
    """
    return password.encode("utf-8").hex()
```

In `SQLCipherProvider.create_connection` (line 340), replace:
```python
conn.execute(f"PRAGMA key = '{password}'")
```
with:
```python
hex_key = _hex_encode_key(password)
conn.execute(f"PRAGMA key = \"x'{hex_key}'\"")
```

In `_migrate_to_sqlcipher` (line 557), replace:
```python
conn.execute(f"ATTACH DATABASE '{encrypted_path}' AS encrypted KEY '{password}'")
```
with:
```python
hex_key = _hex_encode_key(password)
conn.execute(f"ATTACH DATABASE '{encrypted_path}' AS encrypted KEY \"x'{hex_key}'\"")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_encryption.py::test_hex_key_encoding -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/services/encryption.py tests/test_encryption.py
git commit -m "fix: prevent SQL injection in SQLCipher PRAGMA key statements"
```

---

### Task 2: Validate `tax_year` and Guard Empty `available_years`

**Files:**
- Modify: `main.py:348,492,677`

- [ ] **Step 1: Fix `calculate_form` empty-list guard**

In `main.py` line 348, replace:
```python
{"request": request, "csrf": csrf, "available_years": available_years, "available_states": sorted(_get_state_packs(max(available_years)).keys())},
```
with:
```python
{"request": request, "csrf": csrf, "available_years": available_years, "available_states": sorted(_get_state_packs(max(available_years)).keys()) if available_years else []},
```

- [ ] **Step 2: Add `tax_year` validation in `_parse_tax_input_from_form`**

In `main.py`, in `_parse_tax_input_from_form` (line 492), after parsing `tax_year`:
```python
tax_year = int(str(fd.get("tax_year", "2024") or "2024"))
```
add:
```python
if tax_year not in available_years:
    raise ValueError(f"Unsupported tax year: {tax_year}")
```

- [ ] **Step 3: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass (existing tests use valid years)

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "fix: validate tax_year against available years, guard empty list"
```

---

### Task 3: Add Unary Negation Support in Expression Parser

**Files:**
- Modify: `app/engine/calculator.py:584-603`
- Test: `tests/test_calculator_resolve_ref.py`

- [ ] **Step 1: Write failing test**

In `tests/test_calculator_resolve_ref.py`, add:

```python
def test_unary_negation_in_expression() -> None:
    """Engine handles unary minus in formula expressions."""
    from decimal import Decimal

    from app.engine.calculator import CalculationEngine

    # Use _safe_eval directly via a minimal engine instance
    engine = CalculationEngine.__new__(CalculationEngine)
    variables = {"x": Decimal("100"), "y": Decimal("50")}

    assert engine._safe_eval("-x", variables) == Decimal("-100")
    assert engine._safe_eval("-x + y", variables) == Decimal("-50")
    assert engine._safe_eval("+x", variables) == Decimal("100")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_calculator_resolve_ref.py::test_unary_negation_in_expression -v`
Expected: FAIL with `RulePackError: Cannot evaluate expression atom: '-x'`

- [ ] **Step 3: Add unary operator handling in `_eval_atom`**

In `app/engine/calculator.py`, in `_eval_atom` (line 584), after `expr = expr.strip()`, add:

```python
        # Handle unary operators
        if expr.startswith("-") and len(expr) > 1:
            return -self._eval_atom(expr[1:], variables)
        if expr.startswith("+") and len(expr) > 1:
            return self._eval_atom(expr[1:], variables)
```

Place this **before** the `for func in ("max", "min"):` block, so unary operators are stripped before function parsing.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_calculator_resolve_ref.py::test_unary_negation_in_expression -v`
Expected: PASS

- [ ] **Step 5: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add app/engine/calculator.py tests/test_calculator_resolve_ref.py
git commit -m "fix: support unary negation in rule expression parser"
```

---

### Task 4: Fix `hybrid_factory` Consistency and `dict(row)` Support

**Files:**
- Modify: `app/services/encryption.py:49-78` (`HybridRow` class)
- Modify: `app/services/database.py:130,148,158,189`

- [ ] **Step 1: Write test for `HybridRow` iteration and dict behavior**

In `tests/test_encrypted_database.py`, add:

```python
def test_hybrid_row_iteration_yields_columns() -> None:
    """HybridRow iteration yields column names (not values) for sqlite3.Row compat."""
    from app.services.encryption import HybridRow

    class FakeCursor:
        description = [("id",), ("name",), ("value",)]

    row = HybridRow(FakeCursor(), ("abc", "test", 42))
    # __iter__ should yield column names (like sqlite3.Row)
    assert list(row) == ["id", "name", "value"]
    # dict() should produce name-keyed dict
    assert dict(row) == {"id": "abc", "name": "test", "value": 42}
    # values() should give raw values
    assert row.values() == ("abc", "test", 42)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_encrypted_database.py::test_hybrid_row_iteration_yields_columns -v`
Expected: FAIL — `list(row)` produces `['abc', 'test', 42]` (values, not column names) and `row.values()` raises `AttributeError`

- [ ] **Step 3: Fix `HybridRow.__iter__` to yield column names and add `values()`**

In `app/services/encryption.py`, replace the `__iter__` method in `HybridRow` (line 66-67):

```python
    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)
```

with:

```python
    def __iter__(self) -> Iterator[str]:
        return iter(self._columns)
```

And add a `values()` method after `keys()`:

```python
    def values(self) -> tuple[Any, ...]:
        return self._values
```

This makes `list(row)` yield column names and `dict(row)` produce name-keyed dicts, matching `sqlite3.Row` semantics. The `values()` method provides access to raw values when needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_encrypted_database.py::test_hybrid_row_iteration_yields_columns -v`
Expected: PASS

- [ ] **Step 5: Replace `sqlite3.Row` with `hybrid_factory` on all unencrypted paths**

In `app/services/database.py`, add import at top:

```python
from app.services.encryption import hybrid_factory
```

Replace all three occurrences of `conn.row_factory = sqlite3.Row` (lines 130, 148, 158) with:

```python
conn.row_factory = hybrid_factory
```

- [ ] **Step 6: Fix `PRAGMA table_info` column access**

In `app/services/database.py` line 189, replace:

```python
columns = {row[1] for row in conn.execute("PRAGMA table_info(return_runs)").fetchall()}
```

with:

```python
columns = {row["name"] for row in conn.execute("PRAGMA table_info(return_runs)").fetchall()}
```

- [ ] **Step 7: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 8: Commit**

```bash
git add app/services/encryption.py app/services/database.py tests/test_encrypted_database.py
git commit -m "fix: consistent hybrid_factory on all DB connections, fix dict(row)"
```

---

### Task 5: URL-Encode Error Messages in `/unlock` Redirects

**Files:**
- Modify: `main.py:837,876,880,883`

- [ ] **Step 1: Add `urllib.parse` import**

In `main.py`, add to the stdlib imports section (after `import secrets`):

```python
import urllib.parse
```

- [ ] **Step 2: Fix all redirect error messages**

In `main.py` line 837, replace:
```python
return RedirectResponse(url="/unlock?error=Password+is+required", status_code=303)
```
with:
```python
return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus('Password is required')}", status_code=303)
```

In line 876, replace:
```python
error_msg = str(e).replace(" ", "+")
return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)
```
with:
```python
return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus(str(e)[:100])}", status_code=303)
```

In line 880, replace:
```python
error_msg = "Incorrect+password+or+corrupted+database"
return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)
```
with:
```python
return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus('Incorrect password or corrupted database')}", status_code=303)
```

In line 883, replace:
```python
error_msg = f"Unlock+failed:+{str(e)[:50]}"
return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)
```
with:
```python
return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus(f'Unlock failed: {str(e)[:50]}')}", status_code=303)
```

- [ ] **Step 3: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "fix: URL-encode error messages in /unlock redirects"
```

---

### Task 6: Upload Size Limits and SQLite Validation

**Files:**
- Modify: `main.py:914-981`

- [ ] **Step 1: Add size limit constants**

In `main.py`, after `_MAX_INDEXED_ENTRIES = 50` (line 357), add:

```python
_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_RESTORE_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_IMPORT_ENTRIES = 1000
```

- [ ] **Step 2: Add size check to `/import-returns`**

In `main.py` in `import_returns`, after `content = (await upload.read()).decode("utf-8")` (line 921), add:

```python
    if len(content.encode("utf-8")) > _MAX_IMPORT_BYTES:
        return HTMLResponse(f"File too large (max {_MAX_IMPORT_BYTES // (1024*1024)} MB)", status_code=400)
```

After `if not isinstance(entries, list):` block (line 928), add:

```python
    if len(entries) > _MAX_IMPORT_ENTRIES:
        return HTMLResponse(f"Too many entries (max {_MAX_IMPORT_ENTRIES})", status_code=400)
```

- [ ] **Step 3: Add size check and integrity validation to `/restore`**

In `main.py` in `restore_database`, after `content = await upload.read()` (line 968), add:

```python
    if len(content) > _MAX_RESTORE_BYTES:
        return HTMLResponse(f"File too large (max {_MAX_RESTORE_BYTES // (1024*1024)} MB)", status_code=400)
```

Replace the simple magic-byte check (line 969) with a temp-file integrity check. Add `import sqlite3 as _sqlite3` and `import tempfile` to the stdlib imports at the top of `main.py`. Then replace:

```python
    if not content[:16].startswith(b"SQLite format 3"):
        return HTMLResponse("Not a valid SQLite database file", status_code=400)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_bytes(content)
```

with:

```python
    if not content[:16].startswith(b"SQLite format 3"):
        return HTMLResponse("Not a valid SQLite database file", status_code=400)
    # Verify it's a real SQLite database, not just matching magic bytes
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        test_conn = _sqlite3.connect(tmp_path)
        result = test_conn.execute("PRAGMA integrity_check").fetchone()
        test_conn.close()
        if not result or result[0] != "ok":
            return HTMLResponse("Uploaded file is not a valid SQLite database", status_code=400)
    except Exception:
        return HTMLResponse("Uploaded file is not a valid SQLite database", status_code=400)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_bytes(content)
```

- [ ] **Step 4: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add main.py
git commit -m "fix: add upload size limits and SQLite integrity validation"
```

---

### Task 7: Input Sanitization Gaps

**Files:**
- Modify: `main.py:747,761,799,891-893,902-906`

- [ ] **Step 1: Add `_MAX_NOTES` constant and `_sanitize_filename` helper**

In `main.py`, after `_MAX_IMPORT_ENTRIES` constant, add:

```python
_MAX_NOTES = 2000


def _sanitize_filename(raw: str) -> str:
    """Strip non-alphanumeric chars from a string for safe Content-Disposition."""
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw)
```

- [ ] **Step 2: Fix `/annotate` input caps**

In `main.py` in `annotate_run` (lines 891-893), replace:
```python
    tags = str(fd.get("tags", "")).strip()
    notes = str(fd.get("notes", "")).strip()
```
with:
```python
    tags = _form_str(fd, "tags")
    notes = str(fd.get("notes", "")).strip()
    if len(notes) > _MAX_NOTES:
        raise ValueError(f"Notes exceed {_MAX_NOTES} characters")
```

- [ ] **Step 3: Sanitize `run_id` in Content-Disposition headers**

In `main.py`, update all three `Content-Disposition` headers that embed `run_id`:

Line 747 — replace:
```python
headers={"Content-Disposition": f'attachment; filename="run_{run_id}.json"'},
```
with:
```python
headers={"Content-Disposition": f'attachment; filename="run_{_sanitize_filename(run_id)}.json"'},
```

Line 761 — replace:
```python
headers={"Content-Disposition": f'attachment; filename="audit_{run_id}.html"'},
```
with:
```python
headers={"Content-Disposition": f'attachment; filename="audit_{_sanitize_filename(run_id)}.html"'},
```

Line 799 — replace:
```python
headers={"Content-Disposition": f'attachment; filename="forms_{run_id}.json"'},
```
with:
```python
headers={"Content-Disposition": f'attachment; filename="forms_{_sanitize_filename(run_id)}.json"'},
```

- [ ] **Step 4: Fix `/export-all` silent fallback**

In `main.py` in `export_all_runs` (lines 902-906), replace:
```python
        except Exception:
            hydrated.append(r)  # fallback: raw row
```
with:
```python
        except Exception:
            hydrated.append({"error": f"Failed to hydrate run {r.get('id', '?')}", "id": r.get("id")})
```

- [ ] **Step 5: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add main.py
git commit -m "fix: cap tags/notes length, sanitize filenames, fix export fallback"
```

---

## Phase 2: Test Coverage & Quality

### Task 8: Route Coverage Tests and Security Header Regression

**Files:**
- Create: `tests/test_route_coverage.py`

- [ ] **Step 1: Create the test file**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Route coverage tests for previously untested endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db, list_return_runs
from main import app

CSRF = "test-csrf-token"

_BASE_FORM = {
    "csrf_token": CSRF,
    "tax_year": "2024",
    "filing_status": "single",
    "p_first": "Test",
    "p_last": "User",
    "p_w2_0_employer": "Acme",
    "p_w2_0_wages": "75000",
    "p_w2_0_federal_withheld": "10000",
}


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def _create_run() -> str:
    c = _client()
    c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    runs = list_return_runs()
    assert runs
    return str(runs[0]["id"])


# ─── Dashboard ────────────────────────────────────────────────


def test_dashboard_empty() -> None:
    """GET / with no runs returns 200."""
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200


def test_dashboard_with_run() -> None:
    """GET / with a saved run returns 200 and shows run data."""
    _create_run()
    c = _client()
    resp = c.get("/")
    assert resp.status_code == 200
    assert "2024" in resp.text


# ─── Runs List ────────────────────────────────────────────────


def test_runs_list() -> None:
    """GET /runs returns 200."""
    c = _client()
    resp = c.get("/runs")
    assert resp.status_code == 200


# ─── Run Detail ───────────────────────────────────────────────


def test_run_detail_valid() -> None:
    """GET /runs/{id} for a valid run returns 200."""
    run_id = _create_run()
    c = _client()
    resp = c.get(f"/runs/{run_id}")
    assert resp.status_code == 200


def test_run_detail_invalid() -> None:
    """GET /runs/{id} for a nonexistent run returns 404."""
    c = _client()
    resp = c.get("/runs/nonexistent-id")
    assert resp.status_code == 404


# ─── Legal ────────────────────────────────────────────────────


def test_legal_page() -> None:
    """GET /legal returns 200."""
    c = _client()
    resp = c.get("/legal")
    assert resp.status_code == 200


# ─── Unlock ───────────────────────────────────────────────────


def test_unlock_get() -> None:
    """GET /unlock returns 200."""
    c = _client()
    resp = c.get("/unlock")
    assert resp.status_code == 200


def test_unlock_post_empty_password() -> None:
    """POST /unlock with empty password redirects with error."""
    c = _client()
    resp = c.post(
        "/unlock",
        data={"csrf_token": CSRF, "password": ""},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "error=" in resp.headers.get("location", "")


# ─── Security Headers ────────────────────────────────────────


def test_security_headers_present() -> None:
    """All security headers are set on responses."""
    c = _client()
    resp = c.get("/legal")
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("Referrer-Policy") == "no-referrer"
    assert "Permissions-Policy" in resp.headers
    assert "Content-Security-Policy" in resp.headers
    assert resp.headers.get("Cache-Control") == "no-store"
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_route_coverage.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_route_coverage.py
git commit -m "test: add route coverage for dashboard, runs, legal, unlock, headers"
```

---

### Task 9: Error Path Tests

**Files:**
- Create: `tests/test_error_paths.py`

- [ ] **Step 1: Create the test file**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for error handling paths: bad input, missing files, CSRF edge cases."""

import json

import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db, list_return_runs
from main import app

CSRF = "test-csrf-token"

_BASE_FORM = {
    "csrf_token": CSRF,
    "tax_year": "2024",
    "filing_status": "single",
    "p_first": "Test",
    "p_last": "User",
    "p_w2_0_employer": "Acme",
    "p_w2_0_wages": "75000",
    "p_w2_0_federal_withheld": "10000",
}


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


# ─── Import Error Paths ──────────────────────────────────────


def test_import_no_file() -> None:
    """POST /import-returns without a file returns 400."""
    c = _client()
    resp = c.post("/import-returns", data={"csrf_token": CSRF})
    assert resp.status_code == 400
    assert "No file" in resp.text


def test_import_invalid_json() -> None:
    """POST /import-returns with non-JSON returns 400."""
    c = _client()
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("bad.json", b"not json", "application/json")},
    )
    assert resp.status_code == 400
    assert "Invalid JSON" in resp.text


def test_import_non_array() -> None:
    """POST /import-returns with a JSON object (not array) returns 400."""
    c = _client()
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("obj.json", b'{"key": "val"}', "application/json")},
    )
    assert resp.status_code == 400
    assert "array" in resp.text.lower()


# ─── CSRF Edge Cases ─────────────────────────────────────────


def test_csrf_missing_cookie() -> None:
    """POST with form token but no CSRF cookie returns 400."""
    c = TestClient(app, base_url="http://localhost")
    # Deliberately do NOT set the csrf cookie
    resp = c.post(
        "/calculate",
        data=_BASE_FORM,
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "CSRF" in resp.text


# ─── Calculate Validation ────────────────────────────────────


def test_calculate_invalid_filing_status() -> None:
    """POST /calculate with unknown filing status returns 400."""
    c = _client()
    form = {**_BASE_FORM, "filing_status": "invalid"}
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 400


def test_calculate_invalid_tax_year() -> None:
    """POST /calculate with unsupported tax year returns 400."""
    c = _client()
    form = {**_BASE_FORM, "tax_year": "1999"}
    resp = c.post("/calculate", data=form, follow_redirects=False)
    assert resp.status_code == 400
    assert "tax year" in resp.text.lower() or "Unsupported" in resp.text


# ─── Annotate / Delete Nonexistent Runs ──────────────────────


def test_annotate_nonexistent_run() -> None:
    """POST /runs/fake/annotate on a missing run doesn't crash."""
    c = _client()
    resp = c.post(
        "/runs/fake-id/annotate",
        data={"csrf_token": CSRF, "tags": "test", "notes": "test"},
        follow_redirects=False,
    )
    # Should redirect (303) — the UPDATE affects 0 rows but doesn't error
    assert resp.status_code == 303


def test_delete_nonexistent_run() -> None:
    """POST /runs/fake/delete on a missing run doesn't crash."""
    c = _client()
    resp = c.post(
        "/runs/fake-id/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert resp.status_code == 303


# ─── Restore Success Path ────────────────────────────────────


def test_restore_valid_sqlite() -> None:
    """POST /restore with a valid SQLite file succeeds."""
    import sqlite3
    import tempfile

    # Create a minimal valid SQLite database
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        conn = sqlite3.connect(tmp.name)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.commit()
        conn.close()
        tmp.seek(0)
        db_bytes = open(tmp.name, "rb").read()

    c = _client()
    resp = c.post(
        "/restore",
        data={"csrf_token": CSRF},
        files={"file": ("backup.db", db_bytes, "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    import os
    os.unlink(tmp.name)
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_error_paths.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_error_paths.py
git commit -m "test: add error path coverage for import, CSRF, validation, restore"
```

---

### Task 10: `_parse_money` Unit Tests

**Files:**
- Create: `tests/test_parse_money.py`

- [ ] **Step 1: Create the test file**

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for _parse_money monetary input boundary."""

from decimal import Decimal

import pytest

from main import _parse_money


class TestValidInputs:
    def test_integer(self) -> None:
        assert _parse_money("75000") == Decimal("75000.00")

    def test_with_decimals(self) -> None:
        assert _parse_money("75000.50") == Decimal("75000.50")

    def test_zero(self) -> None:
        assert _parse_money("0") == Decimal("0.00")

    def test_with_commas(self) -> None:
        assert _parse_money("1,234,567.89") == Decimal("1234567.89")

    def test_empty_uses_default(self) -> None:
        assert _parse_money("") == Decimal("0.00")

    def test_just_below_billion(self) -> None:
        assert _parse_money("999999999") == Decimal("999999999.00")


class TestRejectedInputs:
    def test_scientific_notation(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("1e9")

    def test_too_many_decimals(self) -> None:
        with pytest.raises(ValueError, match="decimal places"):
            _parse_money("12.345")

    def test_over_billion(self) -> None:
        with pytest.raises(ValueError, match="too large"):
            _parse_money("1500000000")

    def test_leading_plus(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("+100")

    def test_non_numeric(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("abc")

    def test_multiple_dots(self) -> None:
        with pytest.raises(ValueError, match="Invalid money"):
            _parse_money("12.34.56")

    def test_negative_disallowed_by_default(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            _parse_money("-500")

    def test_negative_allowed_when_opted_in(self) -> None:
        assert _parse_money("-500", allow_negative=True) == Decimal("-500.00")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_parse_money.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_parse_money.py
git commit -m "test: add _parse_money unit tests for monetary input boundary"
```

---

### Task 11: Deprecation Fix — `on_event("startup")` to Lifespan

**Files:**
- Modify: `main.py:90,275-309`

- [ ] **Step 1: Add `asynccontextmanager` import**

In `main.py`, add to stdlib imports:

```python
from contextlib import asynccontextmanager
```

- [ ] **Step 2: Rename `startup()` to `_startup()` and add lifespan**

Replace lines 275-309 (the `@app.on_event("startup")` block):

```python
@app.on_event("startup")
def startup() -> None:
```

with:

```python
def _startup() -> None:
```

(Keep the function body and docstring identical, just remove the decorator and rename.)

Then, above the `app = FastAPI(...)` line (currently line 90), add:

```python
@asynccontextmanager
async def _lifespan(a: FastAPI):  # noqa: ARG001
    _startup()
    yield
```

And change line 90 from:
```python
app = FastAPI(title="Tax Copilot", version="0.1.0")
```
to:
```python
app = FastAPI(title="Tax Copilot", version="0.1.0", lifespan=_lifespan)
```

**Note:** The `_startup` function is defined later in the file (after imports and helpers), but since `_lifespan` only references it at runtime (when called), not at import time, this forward reference is fine.

- [ ] **Step 3: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass. The `on_event` DeprecationWarning should no longer appear.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "fix: migrate from deprecated on_event to lifespan context manager"
```

---

### Task 12: DB Connection Safety with `contextlib.closing`

**Files:**
- Modify: `app/services/database.py`

- [ ] **Step 1: Add `closing` import**

In `app/services/database.py`, add to the imports:

```python
from contextlib import closing
```

- [ ] **Step 2: Wrap all functions with `closing()`**

Replace each function body to use `with closing(get_connection()) as conn:`.

`init_db` (line 171):
```python
def init_db() -> None:
    """Create tables if they do not exist."""
    with closing(get_connection()) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS return_runs (
                id TEXT PRIMARY KEY,
                tax_year INTEGER NOT NULL,
                filing_status TEXT NOT NULL,
                scenario_name TEXT NOT NULL DEFAULT 'baseline',
                rule_pack_version TEXT NOT NULL,
                rule_pack_checksum TEXT NOT NULL,
                input_snapshot_json TEXT NOT NULL,
                output_json TEXT NOT NULL,
                trace_json TEXT NOT NULL,
                state_outputs_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL
            );
            """
        )
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(return_runs)").fetchall()}
        if "state_outputs_json" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN state_outputs_json TEXT NOT NULL DEFAULT '[]'"
            )
        if "tags" not in columns:
            conn.execute("ALTER TABLE return_runs ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
        if "notes" not in columns:
            conn.execute("ALTER TABLE return_runs ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
```

Apply the same pattern to `save_return_run`, `list_return_runs`, `get_return_run`, `delete_return_run`, and `update_run_annotation` — each wraps the body in `with closing(get_connection()) as conn:` and removes the explicit `conn.close()` call.

- [ ] **Step 3: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add app/services/database.py
git commit -m "fix: wrap DB functions in contextlib.closing for leak-safe connections"
```

---

## Phase 3: Auditability & Security Hardening

### Task 13: Tamper-Evident Audit Traces (Hash Chaining)

**Files:**
- Modify: `app/models/domain.py:299-316`
- Modify: `app/services/database.py`
- Modify: `main.py`
- Create test in: `tests/test_route_coverage.py` (append)

- [ ] **Step 1: Add `integrity_hash` and `previous_hash` to `ReturnRun`**

In `app/models/domain.py`, add to `ReturnRun` after `notes`:

```python
    integrity_hash: str = ""
    previous_hash: str = ""
```

- [ ] **Step 2: Add hash computation function to `database.py`**

In `app/services/database.py`, add after the imports:

```python
import hashlib


def _compute_integrity_hash(run_data: dict) -> str:
    """Compute SHA-256 integrity hash over substantive run content."""
    payload = (
        str(run_data.get("id", ""))
        + str(run_data.get("tax_year", ""))
        + json.dumps(run_data.get("input_snapshot", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("output", {}), sort_keys=True, ensure_ascii=False)
        + json.dumps(run_data.get("trace", []), sort_keys=True, ensure_ascii=False)
        + str(run_data.get("rule_pack_checksum", ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _get_latest_hash() -> str:
    """Get the integrity_hash of the most recent run (for chain linking)."""
    with closing(get_connection()) as conn:
        row = conn.execute(
            "SELECT integrity_hash FROM return_runs ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
    return row["integrity_hash"] if row else ""
```

- [ ] **Step 3: Add schema migration for new columns**

In `init_db`, after the `notes` migration block, add:

```python
        if "integrity_hash" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN integrity_hash TEXT NOT NULL DEFAULT ''"
            )
        if "previous_hash" not in columns:
            conn.execute(
                "ALTER TABLE return_runs ADD COLUMN previous_hash TEXT NOT NULL DEFAULT ''"
            )
```

- [ ] **Step 4: Update `save_return_run` to compute hashes**

In `save_return_run`, before the INSERT, add:

```python
    integrity_hash = _compute_integrity_hash(run_data)
    previous_hash = _get_latest_hash()
```

Update the INSERT to include the two new columns (15 columns, 15 placeholders):

```python
        conn.execute(
            """INSERT INTO return_runs
               (id, tax_year, filing_status, scenario_name,
                rule_pack_version, rule_pack_checksum,
                input_snapshot_json, output_json, trace_json, state_outputs_json,
                created_at, tags, notes, integrity_hash, previous_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                run_data["id"],
                run_data["tax_year"],
                run_data["filing_status"],
                run_data.get("scenario_name", "baseline"),
                run_data["rule_pack_version"],
                run_data["rule_pack_checksum"],
                json.dumps(run_data["input_snapshot"], ensure_ascii=False),
                json.dumps(run_data["output"], ensure_ascii=False),
                json.dumps(run_data["trace"], ensure_ascii=False),
                json.dumps(run_data.get("state_outputs", []), ensure_ascii=False),
                run_data["created_at"],
                run_data.get("tags", ""),
                run_data.get("notes", ""),
                integrity_hash,
                previous_hash,
            ),
        )
```

- [ ] **Step 5: Add `verify_chain` function**

In `app/services/database.py`, add:

```python
def verify_chain() -> list[dict]:
    """Walk the hash chain and return a list of broken links.

    Returns an empty list if the chain is intact.
    """
    with closing(get_connection()) as conn:
        rows = conn.execute(
            "SELECT id, integrity_hash, previous_hash, created_at, "
            "tax_year, rule_pack_checksum, input_snapshot_json, output_json, trace_json "
            "FROM return_runs ORDER BY created_at ASC, rowid ASC"
        ).fetchall()

    errors: list[dict] = []
    prev_hash = ""
    for row in rows:
        run_id = row["id"]
        stored_hash = row["integrity_hash"]
        stored_prev = row["previous_hash"]

        # Verify chain link
        if stored_prev != prev_hash:
            errors.append({
                "id": run_id,
                "error": "chain_break",
                "expected_previous": prev_hash,
                "actual_previous": stored_prev,
            })

        # Recompute integrity hash
        run_data = {
            "id": run_id,
            "tax_year": row["tax_year"],
            "input_snapshot": json.loads(row["input_snapshot_json"]),
            "output": json.loads(row["output_json"]),
            "trace": json.loads(row["trace_json"]),
            "rule_pack_checksum": row["rule_pack_checksum"],
        }
        expected_hash = _compute_integrity_hash(run_data)
        if stored_hash and stored_hash != expected_hash:
            errors.append({
                "id": run_id,
                "error": "tampered",
                "expected_hash": expected_hash,
                "actual_hash": stored_hash,
            })

        prev_hash = stored_hash

    return errors
```

- [ ] **Step 6: Add `GET /audit/verify` route**

In `main.py`, add the import:
```python
from app.services.database import verify_chain
```
(add `verify_chain` to the existing import block)

Add the route:
```python
@app.get("/audit/verify")
def audit_verify() -> Response:
    """Walk the hash chain and report integrity status."""
    errors = verify_chain()
    status = "ok" if not errors else "integrity_errors"
    return Response(
        content=json.dumps({"status": status, "errors": errors}, indent=2),
        media_type="application/json",
    )
```

- [ ] **Step 7: Write tests**

Append to `tests/test_route_coverage.py`:

```python
# ─── Audit Verification ──────────────────────────────────────


def test_audit_verify_empty_db() -> None:
    """GET /audit/verify on empty DB returns ok."""
    c = _client()
    resp = c.get("/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["errors"] == []


def test_audit_verify_after_runs() -> None:
    """GET /audit/verify after creating runs returns ok (chain intact)."""
    _create_run()
    _create_run()
    c = _client()
    resp = c.get("/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
```

- [ ] **Step 8: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add app/models/domain.py app/services/database.py main.py tests/test_route_coverage.py
git commit -m "feat(m4): tamper-evident audit traces with SHA-256 hash chaining"
```

---

### Task 14: Key Rotation, Password Cache Clearing, Cipher Params, CSRF Rotation

**Files:**
- Modify: `app/services/encryption.py`
- Modify: `app/services/database.py`
- Modify: `main.py`
- Create: `app/templates/pages/rotate_key.html`

- [ ] **Step 1: Add `clear_cached_password` to `database.py`**

In `app/services/database.py`, after `set_cached_password`:

```python
def clear_cached_password() -> None:
    """Clear the in-memory password cache.

    Called on application shutdown to avoid leaving plaintext
    passwords in process memory longer than necessary.
    """
    global _cached_password
    _cached_password = None
```

- [ ] **Step 2: Add `rotate_key` to `encryption.py`**

In `app/services/encryption.py`, add after `_hex_encode_key`:

```python
def rotate_key(old_password: str, new_password: str) -> None:
    """Re-encrypt the database with a new password using SQLCipher PRAGMA rekey.

    Requires SQLCipher. The database must already be encrypted.
    """
    try:
        from pysqlcipher3 import dbapi2 as sqlcipher
    except ImportError as e:
        raise ImportError("pysqlcipher3 is required for key rotation") from e

    from app.services.database import DB_PATH

    conn = sqlcipher.connect(str(DB_PATH), timeout=10.0, isolation_level=None)
    old_hex = _hex_encode_key(old_password)
    conn.execute(f"PRAGMA key = \"x'{old_hex}'\"")
    # Verify old key works
    conn.execute("SELECT count(*) FROM sqlite_master")
    # Rotate to new key
    new_hex = _hex_encode_key(new_password)
    conn.execute(f"PRAGMA rekey = \"x'{new_hex}'\"")
    # Verify new key works
    conn.execute("SELECT count(*) FROM sqlite_master")
    conn.close()
```

- [ ] **Step 3: Add explicit cipher parameters**

In `app/services/encryption.py`, in `SQLCipherProvider.create_connection`, after the `PRAGMA kdf_iter` line (343), add:

```python
            # Pin cipher parameters for cross-version compatibility.
            # Order matters: key → kdf_iter → cipher params → first read.
            conn.execute("PRAGMA cipher_page_size = 4096")
            conn.execute("PRAGMA cipher_compatibility = 4")
```

- [ ] **Step 4: Add CSRF rotation in `/unlock` success path**

In `main.py`, in `unlock_submit`, replace the success redirect (line 873):
```python
        return RedirectResponse(url="/", status_code=303)
```
with:
```python
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie("csrf", secrets.token_urlsafe(32), httponly=True, samesite="strict")
        return resp
```

- [ ] **Step 5: Add `clear_cached_password` to lifespan teardown**

In `main.py`, update the `_lifespan` function:

```python
@asynccontextmanager
async def _lifespan(a: FastAPI):  # noqa: ARG001
    _startup()
    yield
    # Cleanup: clear in-memory password cache on shutdown
    from app.services.database import clear_cached_password
    clear_cached_password()
```

- [ ] **Step 6: Create `rotate_key.html` template**

Create `app/templates/pages/rotate_key.html`:

```html
{% extends "layouts/base.html" %}
{% block title %}Rotate Encryption Key{% endblock %}
{% block content %}
<div style="max-width: 500px; margin: 2rem auto;">
  <h2>Rotate Encryption Key</h2>
  {% if error %}
  <div style="color: #c00; border: 1px solid #c00; padding: 0.5rem; margin-bottom: 1rem;">
    {{ error }}
  </div>
  {% endif %}
  {% if success %}
  <div style="color: #060; border: 1px solid #060; padding: 0.5rem; margin-bottom: 1rem;">
    Key rotated successfully.
  </div>
  {% endif %}
  <form method="post" action="/rotate-key">
    <input type="hidden" name="csrf_token" value="{{ csrf }}">
    <div style="margin-bottom: 1rem;">
      <label for="current_password">Current Password</label><br>
      <input type="password" id="current_password" name="current_password" required style="width: 100%;">
    </div>
    <div style="margin-bottom: 1rem;">
      <label for="new_password">New Password</label><br>
      <input type="password" id="new_password" name="new_password" required style="width: 100%;">
    </div>
    <div style="margin-bottom: 1rem;">
      <label for="confirm_new_password">Confirm New Password</label><br>
      <input type="password" id="confirm_new_password" name="confirm_new_password" required style="width: 100%;">
    </div>
    <button type="submit">Rotate Key</button>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 7: Add `/rotate-key` routes**

In `main.py`, add imports (to existing import block from `app.services.database`):
```python
clear_cached_password,
```

Add import from encryption:
```python
from app.services.encryption import rotate_key
```

Add the routes:

```python
@app.get("/rotate-key", response_class=HTMLResponse)
def rotate_key_form(request: Request, error: str | None = None, success: str | None = None) -> Response:
    """Show key rotation form."""
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/rotate_key.html",
        {"request": request, "csrf": csrf, "error": error, "success": success},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rotate-key")
async def rotate_key_submit(request: Request) -> RedirectResponse:
    """Handle key rotation."""
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))

    current_password = str(fd.get("current_password", ""))
    new_password = str(fd.get("new_password", ""))
    confirm = str(fd.get("confirm_new_password", ""))

    if not current_password or not new_password:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('All fields are required')}",
            status_code=303,
        )
    if new_password != confirm:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('New passwords do not match')}",
            status_code=303,
        )

    from app.services.database import get_cached_password

    if current_password != get_cached_password():
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('Current password is incorrect')}",
            status_code=303,
        )

    try:
        validate_password(new_password)
        rotate_key(current_password, new_password)
        set_cached_password(new_password)
        set_password_in_keyring(new_password)
        return RedirectResponse(
            url=f"/rotate-key?success={urllib.parse.quote_plus('Key rotated successfully')}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus(str(e)[:100])}",
            status_code=303,
        )
```

- [ ] **Step 8: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 9: Commit**

```bash
git add app/services/encryption.py app/services/database.py main.py app/templates/pages/rotate_key.html
git commit -m "feat(m4): key rotation, password cache clearing, cipher params, CSRF rotation"
```

---

### Task 15: Make `pip-audit` Blocking in CI

**Files:**
- Modify: `.github/workflows/ci.yml:57-59`

- [ ] **Step 1: Update CI config**

In `.github/workflows/ci.yml`, replace:

```yaml
      - name: pip-audit (non-blocking)
        continue-on-error: true
        run: pip-audit
```

with:

```yaml
      - name: pip-audit
        run: pip-audit --desc
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: make pip-audit blocking with descriptive output"
```

---

### Task 16: Final Cleanup — README Tree, CHANGELOG, Session Log

**Files:**
- Modify: `README.md`, `CHANGELOG.md`, `.agent_tools/05_session_log.md`

- [ ] **Step 1: Update README tree**

Run: `find . -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -path '*/.mypy_cache/*' -not -path '*/.ruff_cache/*' | sort`

Update the "Actual Current Repository Structure" section in `README.md` with the complete tree including any new files (`rotate_key.html`, new test files).

- [ ] **Step 2: Add CHANGELOG entry**

Add under `## [Unreleased]` → `### Added`:

```markdown
- **Hardening, QA & Auditability pass (complete):** Fixed SQL injection in SQLCipher PRAGMA, `tax_year` validation, unary negation in rule expressions, `hybrid_factory` consistency, URL-encoded error redirects, upload size limits with SQLite integrity validation, input sanitization (tags/notes caps, filename sanitization, export fallback). Added tamper-evident hash chain (`integrity_hash`, `previous_hash`) with `GET /audit/verify`. Key rotation via `POST /rotate-key` with `PRAGMA rekey`. Password cache clearing on shutdown. Explicit cipher parameters. CSRF token rotation after authentication. Made `pip-audit` blocking in CI.
```

Under `### Changed`:
```markdown
- Migrated from deprecated `@app.on_event("startup")` to lifespan context manager.
- All DB functions now use `contextlib.closing` for leak-safe connections.
```

- [ ] **Step 3: Append session log entry**

- [ ] **Step 4: Run final verification**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md .agent_tools/05_session_log.md
git commit -m "docs: update README tree, CHANGELOG, session log for hardening pass"
```
