# QA & Compliance Remediation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all QA and compliance findings from the 2026-03-18 codebase audit so the project meets its own documented standards.

**Architecture:** Surgical fixes across existing files — no new modules or features. SPDX headers, README tree, CHANGELOG formatting, deprecated API updates, and one hardcoded string fix.

**Tech Stack:** Python 3.11+, FastAPI, ruff, mypy, pytest

---

## Chunk 1: Important Findings (I-1 through I-5)

### Task 1: Fix hybrid_factory Consistency in database.py and encryption.py (I-1)

**Files:**
- Modify: `app/services/database.py` (lines ~125, ~143, ~153)
- Modify: `app/services/encryption.py` (line ~435)

**Context:** The project mandates that all DB rows support both `row[0]` (index) and `row["field"]` (key) access via `hybrid_factory`. Several queries bypass this by using `sqlite3.Row` or bare tuples directly.

- [ ] **Step 1: Read database.py and identify all cursor/row-factory assignments**

Run: `grep -n 'row_factory\|\.Row\|fetchone\|fetchall' app/services/database.py`

Identify every place where `sqlite3.Row` is set or where `hybrid_factory` should be used but isn't.

- [ ] **Step 2: Read encryption.py and identify the same pattern**

Run: `grep -n 'row_factory\|\.Row\|fetchone\|fetchall' app/services/encryption.py`

- [ ] **Step 3: Replace sqlite3.Row assignments with hybrid_factory**

In `database.py`, anywhere `conn.row_factory = sqlite3.Row` appears, replace with:
```python
conn.row_factory = hybrid_factory
```

In `encryption.py`, do the same at line ~435 or wherever `sqlite3.Row` is used.

- [ ] **Step 4: Run tests to verify nothing breaks**

Run: `python -m pytest tests/ -v`
Expected: All tests pass. The hybrid_factory returns objects that support both index and key access, so existing code using either pattern should continue to work.

- [ ] **Step 5: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add app/services/database.py app/services/encryption.py
git commit -m "fix: use hybrid_factory consistently for all DB row access (I-1)"
```

---

### Task 2: Fix SPDX License Headers — GPL → AGPL (I-2, M-5)

**Files:**
- Modify: `app/models/forms.py`
- Modify: `app/services/form_mapper.py`
- Modify: `tests/test_forms.py`
- Modify: `tests/test_golden_m1.py`
- Modify: `tests/test_state_expansion.py`

**Context:** The project license is AGPL-3.0-or-later. Five newer files have SPDX one-liners that incorrectly say `GPL-3.0-or-later`. These must be corrected to `AGPL-3.0-or-later`.

- [ ] **Step 1: Fix each file's SPDX header**

In each of the five files, change:
```python
# SPDX-License-Identifier: GPL-3.0-or-later
```
to:
```python
# SPDX-License-Identifier: AGPL-3.0-or-later
```

- [ ] **Step 2: Verify no other files have the wrong header**

Run: `grep -rn 'GPL-3.0-or-later' --include='*.py' . | grep -v AGPL`

Expected: No results (all Python files should say AGPL, not GPL).

- [ ] **Step 3: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass (header comments don't affect linting/typing).

- [ ] **Step 4: Commit**

```bash
git add app/models/forms.py app/services/form_mapper.py tests/test_forms.py tests/test_golden_m1.py tests/test_state_expansion.py
git commit -m "fix: correct SPDX headers from GPL to AGPL on 5 files (I-2, M-5)"
```

---

### Task 3: Update README File Tree (I-3)

**Files:**
- Modify: `README.md`

**Context:** The README's "Actual Current Repository Structure" tree is missing ~30 files and directories added since it was last updated. This includes state rule pack stubs (TX, FL, WA, NV, WY, SD, AK, NH, TN), `.agent_tools/`, `CLAUDE.md`, `docs/superpowers/`, and several test files.

- [ ] **Step 1: Generate current tree**

Run: `find . -not -path './.git/*' -not -path './.git' -not -path './__pycache__/*' -not -path '*/__pycache__/*' -not -path './.mypy_cache/*' -not -path '*/.mypy_cache/*' -not -path './.pytest_cache/*' -not -path '*/.pytest_cache/*' -not -path './.ruff_cache/*' -not -path '*/.ruff_cache/*' -not -name '*.pyc' -not -name '*.egg-info' -not -path '*/.egg-info/*' -not -path './tax_copilot.db*' | sort`

Use this output to build the updated tree.

- [ ] **Step 2: Replace the tree block in README.md**

Replace everything between the ` ```text ` and ` ``` ` fences under "Actual Current Repository Structure" with the updated tree. Include:
- `.agent_tools/` directory and its files
- `CLAUDE.md`
- `docs/superpowers/` and plan files
- All state rule pack directories under `rule_packs/state/`
- All test files under `tests/`
- Any other missing files

- [ ] **Step 3: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: update README file tree to reflect current structure (I-3)"
```

---

### Task 4: Fix CHANGELOG Formatting (I-4)

**Files:**
- Modify: `CHANGELOG.md`

**Context:** The `[Unreleased]` section has orphan bullet points (items not under any `### Added/Changed/Fixed` heading) and some items placed under the wrong heading. The Keep a Changelog format requires every item to be under a type heading.

- [ ] **Step 1: Read the current CHANGELOG**

Read `CHANGELOG.md` and identify:
1. Bullets that aren't under any `### Added/Changed/Fixed` heading
2. Items under the wrong category (e.g., additions listed under Changed)
3. Duplicate or near-duplicate entries

- [ ] **Step 2: Reorganize the [Unreleased] section**

Group all entries correctly:
- `### Added` — new features, new files, new routes, new tests
- `### Changed` — modifications to existing behavior
- `### Fixed` — bug fixes

Remove any duplicate entries. Ensure no orphan bullets exist between headings.

- [ ] **Step 3: Verify formatting**

Visually inspect that every bullet under `[Unreleased]` is nested under exactly one `### Type` heading.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs: fix CHANGELOG formatting — group all entries under correct headings (I-4)"
```

---

### Task 5: Remove Hardcoded "Georgia" in audit_export.py (I-5)

**Files:**
- Modify: `app/services/audit_export.py` (line ~60)

**Context:** The audit export HTML has a hardcoded `"Georgia"` label for the state tax section. With state expansion adding 9+ new states, this needs to dynamically use the state name from the run data.

- [ ] **Step 1: Read audit_export.py and find the hardcoded string**

Run: `grep -n 'Georgia' app/services/audit_export.py`

- [ ] **Step 2: Replace with dynamic state name**

The state pack key (e.g., `GA`, `TX`, `FL`) should be available from the run's trace or state results. Replace the hardcoded `"Georgia"` with the state abbreviation or full name derived from the run data.

If the state name isn't available in the function's parameters, derive it from the state pack keys present in the output/trace data.

- [ ] **Step 3: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add app/services/audit_export.py
git commit -m "fix: replace hardcoded 'Georgia' with dynamic state name in audit export (I-5)"
```

---

## Chunk 2: Minor Findings (M-1 through M-4)

### Task 6: Replace Deprecated @app.on_event("startup") (M-1)

**Files:**
- Modify: `main.py` (line ~236)

**Context:** FastAPI deprecated `@app.on_event("startup")` in favor of lifespan context managers. This generates a deprecation warning.

- [ ] **Step 1: Read the startup handler in main.py**

Find the `@app.on_event("startup")` block and understand what it does (likely calls `init_db()`).

- [ ] **Step 2: Convert to lifespan context manager**

Replace:
```python
@app.on_event("startup")
async def startup():
    init_db()
```

With a lifespan at the top of the app definition:
```python
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(..., lifespan=lifespan)
```

Remove the old `@app.on_event("startup")` function.

- [ ] **Step 3: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass. The lifespan pattern is the modern FastAPI approach.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: replace deprecated on_event('startup') with lifespan (M-1)"
```

---

### Task 7: Fix Deprecated TemplateResponse Signature (M-2)

**Files:**
- Modify: `main.py` (12 occurrences)

**Context:** The two-argument `TemplateResponse(name, context)` signature is deprecated. The modern form is `TemplateResponse(request=request, name=name, context=context)` or using keyword arguments.

- [ ] **Step 1: Find all TemplateResponse calls**

Run: `grep -n 'TemplateResponse' main.py`

- [ ] **Step 2: Update each call to use keyword arguments**

Change each:
```python
templates.TemplateResponse("pages/foo.html", {"request": request, ...})
```
to:
```python
templates.TemplateResponse(name="pages/foo.html", request=request, context={...})
```

Note: The `request` is pulled out of the context dict and passed as a keyword argument. Remaining context items stay in the `context` dict (without `"request"`).

- [ ] **Step 3: Run quality gates**

Run: `ruff check . && mypy . && python -m pytest`
Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: update TemplateResponse calls to non-deprecated signature (M-2)"
```

---

### Task 8: Update ROADMAP to Mark Completed Milestones (M-4)

**Files:**
- Modify: `ROADMAP.md`

**Context:** Milestones 1, 3, and 6 are implemented but the ROADMAP still shows them as pending/future.

- [ ] **Step 1: Read ROADMAP.md**

Identify the milestone entries for M1, M3, and M6.

- [ ] **Step 2: Mark them as complete**

Add a completion indicator (e.g., checkmark, "DONE" label, or strikethrough) to Milestones 1, 3, and 6, following whatever formatting convention the ROADMAP already uses.

- [ ] **Step 3: Commit**

```bash
git add ROADMAP.md
git commit -m "docs: mark Milestones 1, 3, 6 as complete in ROADMAP (M-4)"
```

---

### Task 9: Final Validation

- [ ] **Step 1: Run full quality gate suite**

```bash
ruff check . && mypy . && python -m pytest -v
```

Expected: All pass with zero warnings related to the fixed items.

- [ ] **Step 2: Verify no remaining GPL headers**

```bash
grep -rn 'GPL-3.0-or-later' --include='*.py' . | grep -v AGPL
```

Expected: No results.

- [ ] **Step 3: Verify no remaining "Georgia" hardcoding**

```bash
grep -rn 'Georgia' app/
```

Expected: No results (or only in comments/docs that are appropriate).
