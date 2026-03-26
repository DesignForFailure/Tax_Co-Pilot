# UI/UX Beta Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all UI/UX bugs, add missing form fields, harden error handling, and push the project to a stable beta state.

**Architecture:** Server-rendered Jinja2 templates with vanilla JS. All fixes are in templates (HTML/CSS/JS) and main.py route handlers. No engine changes needed — the engine already handles all fields; the UI just wasn't exposing them all.

**Tech Stack:** FastAPI, Jinja2, vanilla JS, pytest with httpx TestClient

---

### Task 1: Fix CSP to Allow Inline Scripts

The `script-src 'self'` CSP policy blocks ALL inline `<script>` tags and `onclick=` handlers. Every interactive page is broken in CSP-compliant browsers.

**Files:**
- Modify: `main.py:135-144`
- Test: `tests/test_route_coverage.py` (existing test checks headers)

- [ ] **Step 1: Update CSP policy**

In `main.py`, change line 137 from:
```python
"script-src 'self'; "
```
to:
```python
"script-src 'self' 'unsafe-inline'; "
```

This matches the existing `style-src 'self' 'unsafe-inline'` pattern and is appropriate for a localhost-first app with no external scripts.

- [ ] **Step 2: Update the existing security headers test**

In `tests/test_route_coverage.py`, find the test that checks `script-src 'self'` and update it to expect `script-src 'self' 'unsafe-inline'`.

- [ ] **Step 3: Run tests**

Run: `pytest tests/test_route_coverage.py -v -k security`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add main.py tests/test_route_coverage.py
git commit -m "fix: CSP blocks all inline JS — add unsafe-inline to script-src"
```

---

### Task 2: Fix rotate_key.html Styling

This page uses raw CSS (`color: #c00`, bare `<button>`, `margin-bottom: 1rem`) instead of the design system. It looks like a different app.

**Files:**
- Modify: `app/templates/pages/rotate_key.html`

- [ ] **Step 1: Rewrite rotate_key.html to use the design system**

Replace the entire template with one that matches the unlock.html styling pattern — centered card, CSS variables, `.btn` classes, `.card` container, proper error/success styling.

Key changes:
- Wrap in centered `max-width: 500px; margin: 80px auto` container (like unlock.html)
- Error div: use `var(--red)` background with white text and `border-radius: 10px` (like unlock.html)
- Success div: use `var(--green)` background with white text and same radius
- All inputs: remove `<br>` tags, use `<label>` block styling from base.html
- Submit button: add `class="btn"` with `width: 100%` and proper padding
- Add back-link to dashboard or nav context

- [ ] **Step 2: Run lint and tests**

Run: `ruff check . && pytest tests/test_route_coverage.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/rotate_key.html
git commit -m "fix: rotate-key page now uses design system variables and classes"
```

---

### Task 3: Add Missing Fields to What-If Form

The What-If page only collects W-2s and 1099s. It's missing above-the-line deductions, itemized deductions, dependents, other income, and estimated payments. The engine already handles all these via `_parse_tax_input_from_form()` — the template just doesn't have the fields.

Additionally, the What-If W-2 template is missing state fields (Box 15/16/17) and the 1099-B template is missing the federal_withheld field and long-term checkbox.

**Files:**
- Modify: `app/templates/pages/whatif.html`

- [ ] **Step 1: Add missing form sections to whatif.html**

After the Spouse card and before the submit button, add these sections (copy from calculate.html, they are identical):
1. Other Income card (Schedule 1 field)
2. Above-the-Line Deductions card (student loan, educator, HSA, IRA, SE tax)
3. Itemized Deductions card (medical, SALT, property tax, mortgage, charitable cash/noncash)
4. Dependents card (qualifying children)
5. Estimated Tax Payments card

- [ ] **Step 2: Fix W-2 template in whatif.html JS**

Update the `getTemplate` function's W-2 section to include the state fields (Box 15, Box 16, Box 17) — matching the calculate.html W-2 template which has a `form-row-3` with state, state_wages, state_withheld.

- [ ] **Step 3: Fix 1099-B template in whatif.html JS**

Update the `getTemplate` function's 1099-B section to include federal_withheld and the long-term checkbox — matching calculate.html.

- [ ] **Step 4: Run existing What-If tests**

Run: `pytest tests/test_milestone6_routes.py -v -k whatif`
Expected: PASS (existing tests still work — the new fields are optional with zero defaults)

- [ ] **Step 5: Commit**

```bash
git add app/templates/pages/whatif.html
git commit -m "fix: what-if form now includes deductions, dependents, and full W-2/1099-B fields"
```

---

### Task 4: Preserve csv_text on Import Submission

After submitting CSV, the textarea is cleared because `csv_text` isn't passed back to the template. If there are partial errors, the user loses their input.

**Files:**
- Modify: `main.py` (the `import_csv_submit` route, around line 892-912)
- Test: `tests/test_milestone6_routes.py`

- [ ] **Step 1: Write failing test**

In `tests/test_milestone6_routes.py`, add a test that submits CSV via POST and checks that the response HTML contains the original CSV text in the textarea.

```python
def test_import_csv_preserves_input_text(client):
    csv = "employer_name,wages,federal_withheld\nAcme,50000,8000"
    resp = client.post("/import-csv", data={"csrf_token": CSRF, "record_type": "W2", "csv_text": csv})
    assert "Acme,50000,8000" in resp.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_milestone6_routes.py::test_import_csv_preserves_input_text -v`
Expected: FAIL (csv text not in response)

- [ ] **Step 3: Fix the route**

In `main.py`, in the `import_csv_submit` function, add `"csv_text": csv_text` to the template context dict (around line 904-909).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_milestone6_routes.py::test_import_csv_preserves_input_text -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add main.py tests/test_milestone6_routes.py
git commit -m "fix: CSV import preserves input text on submission"
```

---

### Task 5: Add Nav Active State

The current page isn't highlighted in the navigation bar. All links look identical.

**Files:**
- Modify: `app/templates/layouts/base.html`
- Modify: All page templates that extend base.html (to pass active nav info)

- [ ] **Step 1: Add active nav CSS to base.html**

In the `<style>` section, add:
```css
nav a.active { color: var(--accent); font-weight: 600; }
```

- [ ] **Step 2: Add nav active logic to base.html**

Replace the hardcoded nav links with links that check a `nav_active` variable:
```html
<a href="/" {% if nav_active == "dashboard" %}class="active"{% endif %}>Dashboard</a>
<a href="/calculate" {% if nav_active == "calculate" %}class="active"{% endif %}>Calculate</a>
...
```

- [ ] **Step 3: Pass nav_active from every route handler**

In `main.py`, add `"nav_active": "dashboard"` (or "calculate", "whatif", etc.) to every template context dict. To keep this DRY, create a small helper:

```python
def _ctx(request: Request, nav: str, **extra: Any) -> dict[str, Any]:
    return {"request": request, "nav_active": nav, "csrf": _get_csrf_token(request), **extra}
```

Then use it in each route. This replaces the repeated `{"csrf": csrf, ...}` pattern.

- [ ] **Step 4: Run all tests**

Run: `pytest`
Expected: All 270+ tests pass

- [ ] **Step 5: Commit**

```bash
git add app/templates/layouts/base.html main.py
git commit -m "feat: highlight active page in navigation bar"
```

---

### Task 6: Add Error Handling to POST /calculate

POST /calculate has no try/except. If input parsing or calculation fails, the global ValueError handler returns a plaintext 400 — not a user-friendly HTML page with the form. Compare with POST /whatif which correctly catches ValueError and re-renders with an error message.

**Files:**
- Modify: `main.py` (the `calculate_submit` route, around line 716-752)
- Test: `tests/test_error_paths.py`

- [ ] **Step 1: Write failing test**

Add a test that submits invalid data to POST /calculate and expects an HTML response (not plaintext) containing an error message.

```python
def test_calculate_validation_error_renders_form(client):
    resp = client.post("/calculate", data={"csrf_token": CSRF, "tax_year": "9999", ...})
    assert resp.status_code == 400
    assert "text/html" in resp.headers["content-type"]
    assert "Enter Tax Data" in resp.text  # re-renders calculate form
```

- [ ] **Step 2: Run test to verify it fails**

Expected: FAIL (currently returns text/plain from global handler)

- [ ] **Step 3: Wrap calculate_submit in try/except**

Add try/except ValueError around the parse and calculation logic. On error, re-render calculate.html with the error message in context, matching the whatif pattern:

```python
try:
    inputs = _parse_tax_input_from_form(fd)
    # ... run engine, save ...
    return RedirectResponse("/", status_code=303)
except ValueError as exc:
    context["error"] = str(exc)
    status_code = 400
```

Also add an error display block at the top of `app/templates/pages/calculate.html` (matching whatif.html's pattern):
```html
{% if error %}
<div class="card" style="border-color: var(--red); margin-bottom: 20px;">
    <h2 style="color: var(--red);">Calculation Error</h2>
    <p style="margin-top: 8px;">{{ error }}</p>
</div>
{% endif %}
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_error_paths.py -v`
Expected: PASS

Note: The existing test `test_calculate_validation_error_is_plain_text` may need updating since the response format changed. If it asserts `text/plain`, update it to expect `text/html`.

- [ ] **Step 5: Commit**

```bash
git add main.py app/templates/pages/calculate.html tests/test_error_paths.py
git commit -m "fix: POST /calculate returns friendly HTML error instead of plaintext"
```

---

### Task 7: Add Submit Loading State and Client-Side Validation

No visual feedback during form submission. Users can double-submit. Also, no client-side validation on money fields.

**Files:**
- Modify: `app/templates/layouts/base.html` (add global submit handler CSS/JS)
- Modify: `app/templates/pages/calculate.html` (add form onsubmit)
- Modify: `app/templates/pages/whatif.html` (add form onsubmit)

- [ ] **Step 1: Add loading state CSS to base.html**

```css
.btn[disabled] { opacity: 0.6; cursor: not-allowed; }
```

- [ ] **Step 2: Add a small inline script to base.html for form submit handling**

```html
<script>
document.addEventListener('submit', function(e) {
    var btn = e.target.querySelector('button[type="submit"], .btn[type="submit"]');
    if (btn && !btn.disabled) {
        btn.disabled = true;
        btn.dataset.originalText = btn.textContent;
        btn.textContent = 'Working…';
    }
});
</script>
```

This prevents double-submit globally and provides visual feedback. It goes in base.html so it applies to ALL forms site-wide.

- [ ] **Step 3: Run tests**

Run: `pytest`
Expected: All pass (JS doesn't affect server-side tests)

- [ ] **Step 4: Commit**

```bash
git add app/templates/layouts/base.html
git commit -m "feat: disable submit button and show loading state during form submission"
```

---

### Task 8: Add Dashboard "View All Runs" Link

Dashboard only shows the latest run with no indication other runs exist.

**Files:**
- Modify: `app/templates/pages/dashboard.html`

- [ ] **Step 1: Add a link to /runs on the dashboard**

After the export buttons div (around line 9-13), add:
```html
<a href="/runs" class="btn btn-sm btn-outline">All Runs</a>
```

Also add a "New Calculation" link:
```html
<a href="/calculate" class="btn btn-sm btn-outline">New Calculation</a>
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_route_coverage.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add app/templates/pages/dashboard.html
git commit -m "feat: add 'All Runs' and 'New Calculation' links to dashboard"
```

---

### Task 9: Add Test for POST /rotate-key

This route has zero test coverage.

**Files:**
- Test: `tests/test_route_coverage.py`

- [ ] **Step 1: Write tests for rotate-key**

Add tests covering:
1. GET /rotate-key renders form (200, contains "Rotate Encryption Key")
2. POST /rotate-key with mismatched passwords returns error
3. POST /rotate-key with empty passwords returns error

```python
def test_rotate_key_get(client):
    resp = client.get("/rotate-key")
    assert resp.status_code == 200
    assert "Rotate" in resp.text

def test_rotate_key_mismatch(client):
    resp = client.post("/rotate-key", data={
        "csrf_token": CSRF,
        "current_password": "oldpassword123",
        "new_password": "newpassword123",
        "confirm_new_password": "differentpassword",
    }, follow_redirects=False)
    assert resp.status_code == 303
    assert "error" in resp.headers.get("location", "")
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_route_coverage.py -v -k rotate`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_route_coverage.py
git commit -m "test: add coverage for POST /rotate-key endpoint"
```

---

### Task 10: Final Verification

- [ ] **Step 1: Run full suite**

Run: `ruff check . && mypy . && pytest`
Expected: All pass, no new warnings

- [ ] **Step 2: Commit any fixups**

- [ ] **Step 3: Update README.md tree if any new files were created**

Only needed if new files were added to the repo (not expected for this plan since we're modifying existing files).
