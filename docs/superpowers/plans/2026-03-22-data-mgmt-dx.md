# Data Management & Developer Experience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add data portability (export/import all return runs), database backup/restore, a rule pack validation CLI, a rule pack authoring guide, GitHub contribution templates, and run tagging/notes — completing Milestone 11.

**Architecture:** New routes in `main.py` for export/import/backup/restore/annotate. The DB schema gets two nullable columns (`tags`, `notes`). The validation CLI is a standalone script wrapping `RulePack.load()`. Docs and templates are markdown files. All features are independent — no cross-dependencies.

**Tech Stack:** Python 3.13, FastAPI, SQLite, Pydantic v2, argparse, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `app/services/database.py` | Modify | Add `tags`/`notes` columns, `update_run_annotation()` function |
| `app/models/domain.py` | Modify | Add `tags`/`notes` fields to `ReturnRun` |
| `main.py` | Modify | Add 5 new routes: `/export-all`, `/import-returns`, `/backup`, `/restore`, `/runs/{id}/annotate` |
| `app/templates/pages/runs.html` | Modify | Show tags/notes, add inline edit, add export/import nav buttons |
| `scripts/validate_rule_pack.py` | Create | CLI tool wrapping `RulePack.load()` with argparse |
| `tests/test_data_mgmt.py` | Create | Tests for export/import round-trip, backup, annotation, CLI |
| `docs/RULE_PACK_AUTHORING.md` | Create | Authoring guide for rule packs |
| `.github/ISSUE_TEMPLATE/new_state.md` | Create | Issue template for new state requests |
| `.github/PULL_REQUEST_TEMPLATE.md` | Create | PR checklist template |
| `README.md` | Modify | Update repository structure tree |
| `CHANGELOG.md` | Modify | Add M11 entry |

---

### Task 1: Add Tags/Notes to Database Schema and Domain Model

**Files:**
- Modify: `app/services/database.py:165-194` (init_db, save_return_run)
- Modify: `app/models/domain.py:299-314` (ReturnRun)

- [ ] **Step 1: Add `tags` and `notes` fields to ReturnRun model**

In `app/models/domain.py`, add two optional fields to the `ReturnRun` class, after the `created_at` field:

```python
    tags: str = ""
    notes: str = ""
```

- [ ] **Step 2: Add columns to init_db schema migration**

In `app/services/database.py` `init_db()`, after the existing `state_outputs_json` migration block (around line 189-193), add:

```python
    if "tags" not in columns:
        conn.execute("ALTER TABLE return_runs ADD COLUMN tags TEXT NOT NULL DEFAULT ''")
    if "notes" not in columns:
        conn.execute("ALTER TABLE return_runs ADD COLUMN notes TEXT NOT NULL DEFAULT ''")
```

- [ ] **Step 3: Update save_return_run to persist tags/notes**

Replace the entire INSERT in `save_return_run()` with this complete statement (adds `tags, notes` columns and two more `?` placeholders):

```python
    conn.execute(
        """INSERT INTO return_runs
           (id, tax_year, filing_status, scenario_name,
            rule_pack_version, rule_pack_checksum,
            input_snapshot_json, output_json, trace_json, state_outputs_json,
            created_at, tags, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
        ),
    )
```

- [ ] **Step 4: Add update_run_annotation function**

Add to `app/services/database.py`:

```python
def update_run_annotation(run_id: str, tags: str, notes: str) -> None:
    """Update tags and notes for an existing run."""
    conn = get_connection()
    conn.execute(
        "UPDATE return_runs SET tags = ?, notes = ? WHERE id = ?",
        (tags, notes, run_id),
    )
    conn.close()
```

- [ ] **Step 5: Update _load_run_from_row in main.py**

In `main.py` `_load_run_from_row()` (around line 264), the existing hydration code strips `_json` suffix keys. The `tags` and `notes` columns don't end in `_json`, so they'll pass through automatically. No change needed — just verify by reading the function.

- [ ] **Step 6: Run existing tests**

Run: `ruff check . && mypy . && pytest`
Expected: All pass (schema migration is backward-compatible)

- [ ] **Step 7: Commit**

```bash
git add app/models/domain.py app/services/database.py
git commit -m "feat(m11): add tags/notes fields to ReturnRun and DB schema"
```

---

### Task 2: Add Annotate Route and Update Runs List UI

**Files:**
- Modify: `main.py` (add POST /runs/{run_id}/annotate route)
- Modify: `app/templates/pages/runs.html` (show tags/notes, add inline edit form)

- [ ] **Step 1: Add annotate route to main.py**

Add before the exception handler (around line 886):

```python
@app.post("/runs/{run_id}/annotate")
async def annotate_run(request: Request, run_id: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    tags = str(fd.get("tags", "")).strip()
    notes = str(fd.get("notes", "")).strip()
    update_run_annotation(run_id, tags, notes)
    return RedirectResponse(url="/runs", status_code=303)
```

Add import for `update_run_annotation` — it's in `app.services.database`, which is already imported. Just add the function name to the existing import.

- [ ] **Step 2: Update runs.html to show tags/notes columns and inline edit**

Add two new columns ("Tags", "Notes") to the table header. In each row, show the tag/note values. Add a small "Edit" link per row that toggles a hidden inline form with text inputs for tags and notes plus a Save button.

Add a Tags column header after "Rule Pack":
```html
<th style="text-align:left;padding:8px;border-bottom:1px solid var(--border);">Tags</th>
<th style="text-align:left;padding:8px;border-bottom:1px solid var(--border);">Notes</th>
```

Add tag/note cells per row after the rule_pack_version cell:
```html
<td style="padding:8px;border-bottom:1px solid var(--border);">{{ r.tags or "—" }}</td>
<td style="padding:8px;border-bottom:1px solid var(--border);">
    {{ r.notes or "—" }}
    <form method="POST" action="/runs/{{ r.id }}/annotate" style="display:inline;margin-left:8px;">
        <input type="hidden" name="csrf_token" value="{{ csrf }}">
        <input type="text" name="tags" value="{{ r.tags }}" placeholder="tags" style="width:80px;font-size:11px;">
        <input type="text" name="notes" value="{{ r.notes }}" placeholder="notes" style="width:120px;font-size:11px;">
        <button type="submit" class="btn btn-sm btn-outline" style="font-size:10px;padding:2px 6px;">Save</button>
    </form>
</td>
```

Note: the `runs` list is passed from `main.py` — the runs list route needs to ensure `tags` and `notes` are available in the template. Since `list_return_runs()` returns `dict(row)` which includes all columns, and `_load_run_from_row` is only used for detail views, the runs list template receives raw dicts. The `tags` and `notes` fields will be present after the schema migration.

- [ ] **Step 3: Run tests**

Run: `ruff check . && mypy . && pytest`

- [ ] **Step 4: Commit**

```bash
git add main.py app/templates/pages/runs.html
git commit -m "feat(m11): add run annotation route and tags/notes on runs list"
```

---

### Task 3: Export/Import All Returns

**Files:**
- Modify: `main.py` (add GET /export-all, POST /import-returns routes)

- [ ] **Step 1: Add export-all route**

Add to `main.py`. IMPORTANT: The raw DB rows contain `*_json` string columns (e.g., `input_snapshot_json`). We must hydrate each row through `_load_run_from_row` and then serialize via `model_dump()` to produce proper nested JSON — not double-encoded strings. The import side will then receive objects keyed by model field names (`input_snapshot`, not `input_snapshot_json`).

```python
@app.get("/export-all")
def export_all_runs() -> Response:
    rows = list_return_runs()
    hydrated = []
    for r in rows:
        try:
            run = _load_run_from_row(r)
            hydrated.append(json.loads(run.model_dump_json()))
        except Exception:
            hydrated.append(r)  # fallback: raw row
    return Response(
        content=json.dumps(hydrated, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=tax_copilot_runs.json"},
    )
```

- [ ] **Step 2: Add import-returns route**

The import receives hydrated ReturnRun-shaped dicts (with `input_snapshot` as an object, not `input_snapshot_json` as a string). We must convert them to the format `save_return_run` expects (which takes `input_snapshot` as an object and calls `json.dumps` internally). We also verify the `rule_pack_checksum` matches if the corresponding pack is loaded.

```python
@app.post("/import-returns", response_class=HTMLResponse)
async def import_returns(request: Request) -> HTMLResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    upload = fd.get("file")
    if not upload or not hasattr(upload, "read"):
        return HTMLResponse("No file uploaded", status_code=400)
    content = (await upload.read()).decode("utf-8")
    try:
        entries = json.loads(content)
    except json.JSONDecodeError as e:
        return HTMLResponse(f"Invalid JSON: {e}", status_code=400)
    if not isinstance(entries, list):
        return HTMLResponse("Expected a JSON array", status_code=400)
    imported = 0
    errors: list[str] = []
    for i, entry in enumerate(entries):
        try:
            # Validate structure via Pydantic
            run = ReturnRun(**entry)
            # Checksum verification: if we have the pack loaded, compare
            year = run.tax_year
            if year in _federal_cache:
                expected = _federal_cache[year].checksum
                if run.rule_pack_checksum and run.rule_pack_checksum != expected:
                    errors.append(f"Entry {i}: checksum mismatch (pack may differ)")
                    continue
            run_dict = json.loads(run.model_dump_json())
            save_return_run(run_dict)
            imported += 1
        except Exception as e:
            errors.append(f"Entry {i}: {e}")
    result = f"Imported {imported} run(s)."
    if errors:
        result += f" {len(errors)} error(s): " + "; ".join(errors[:5])
    return HTMLResponse(result, status_code=200)
```

Note: `_federal_cache` is the module-level dict in `main.py` that maps year -> RulePack. `ReturnRun` is already imported.

- [ ] **Step 3: Add nav buttons for export/import on runs page**

In `app/templates/pages/runs.html`, after the Compare button div (around line 11), add data portability buttons. The restore form uses `onsubmit="return confirm(...)"` to satisfy the ROADMAP's two-step confirmation requirement:

```html
<div style="margin-bottom: 12px;">
    <a href="/export-all" class="btn btn-sm btn-outline">Export All Runs (JSON)</a>
    <a href="/backup" class="btn btn-sm btn-outline">Backup Database</a>
</div>
<div style="margin-bottom: 12px;">
    <form method="POST" action="/import-returns" enctype="multipart/form-data" style="display:inline;">
        <input type="hidden" name="csrf_token" value="{{ csrf }}">
        <input type="file" name="file" accept=".json" style="font-size:12px;">
        <button type="submit" class="btn btn-sm btn-outline">Import Runs</button>
    </form>
    &nbsp;
    <form method="POST" action="/restore" enctype="multipart/form-data" style="display:inline;"
          onsubmit="return confirm('This will REPLACE your entire database. All current runs will be lost. Continue?')">
        <input type="hidden" name="csrf_token" value="{{ csrf }}">
        <input type="file" name="file" accept=".db,.sqlite" style="font-size:12px;">
        <button type="submit" class="btn btn-sm btn-danger" style="font-size:11px;">Restore Database</button>
    </form>
</div>
```

- [ ] **Step 4: Run tests**

Run: `ruff check . && mypy . && pytest`

- [ ] **Step 5: Commit**

```bash
git add main.py app/templates/pages/runs.html
git commit -m "feat(m11): add export-all and import-returns routes"
```

---

### Task 4: Database Backup/Restore

**Files:**
- Modify: `main.py` (add GET /backup, POST /restore routes)

- [ ] **Step 1: Add backup route**

```python
@app.get("/backup")
def backup_database() -> Response:
    if not DB_PATH.exists():
        return HTMLResponse("No database file found", status_code=404)
    return Response(
        content=DB_PATH.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={DB_PATH.name}"},
    )
```

Note: `DB_PATH` is already imported from `app.services.database` — check the existing imports. If not, add it.

- [ ] **Step 2: Add restore route**

The ROADMAP requires a confirmation step. We use a JavaScript `confirm()` on the form submission (in the runs template) for the first gate. The route itself also validates the SQLite magic bytes. Note: if the database is encrypted and the backup was encrypted with a different password, `init_db()` may fail — we wrap it in a try/except and return a meaningful error.

```python
@app.post("/restore", response_class=HTMLResponse)
async def restore_database(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    upload = fd.get("file")
    if not upload or not hasattr(upload, "read"):
        return HTMLResponse("No file uploaded", status_code=400)
    content = await upload.read()
    # Basic SQLite validation: check file header magic bytes
    if not content[:16].startswith(b"SQLite format 3"):
        return HTMLResponse("Not a valid SQLite database file", status_code=400)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_bytes(content)
    try:
        init_db()
    except Exception as e:
        return HTMLResponse(
            f"Database restored but failed to initialize: {e}. "
            "If the backup is encrypted, ensure the same password is active.",
            status_code=500,
        )
    return RedirectResponse(url="/runs", status_code=303)
```

Add `DB_PATH` to the existing import from `app.services.database` if not already there.

- [ ] **Step 3: Run tests**

Run: `ruff check . && mypy . && pytest`

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "feat(m11): add database backup and restore routes"
```

---

### Task 5: Write Tests for Data Management Features

**Files:**
- Create: `tests/test_data_mgmt.py`

- [ ] **Step 1: Write the test file**

Uses the established sync `TestClient` pattern from `test_milestone6_routes.py` — not async.

```python
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for data management features: export/import, backup, annotations."""

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


def _create_run() -> str:
    c = _client()
    c.post("/calculate", data=_BASE_FORM, follow_redirects=False)
    runs = list_return_runs()
    assert runs
    return str(runs[0]["id"])


def test_export_all_returns_json() -> None:
    """GET /export-all returns a JSON array."""
    c = _client()
    resp = c.get("/export-all")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert isinstance(data, list)


def test_backup_returns_sqlite_file() -> None:
    """GET /backup returns a downloadable file."""
    c = _client()
    resp = c.get("/backup")
    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")


def test_export_import_round_trip() -> None:
    """Exported runs can be re-imported."""
    c = _client()
    # Create a run first
    _create_run()

    # Export
    export_resp = c.get("/export-all")
    assert export_resp.status_code == 200
    exported = export_resp.json()
    assert len(exported) >= 1

    # Delete the run so re-import doesn't hit a unique constraint
    from app.services.database import delete_return_run
    for entry in exported:
        delete_return_run(entry["id"])

    # Import the exported data back
    resp = c.post(
        "/import-returns",
        data={"csrf_token": CSRF},
        files={"file": ("runs.json", json.dumps(exported).encode(), "application/json")},
    )
    assert resp.status_code == 200
    assert "Imported" in resp.text

    # Verify the run is back
    runs_after = list_return_runs()
    assert len(runs_after) >= 1


def test_annotate_run() -> None:
    """POST /runs/{id}/annotate updates tags and notes."""
    run_id = _create_run()
    c = _client()

    resp = c.post(
        f"/runs/{run_id}/annotate",
        data={"csrf_token": CSRF, "tags": "final", "notes": "reviewed"},
        follow_redirects=False,
    )
    assert resp.status_code == 303


def test_restore_rejects_non_sqlite() -> None:
    """POST /restore rejects non-SQLite files."""
    c = _client()
    resp = c.post(
        "/restore",
        data={"csrf_token": CSRF},
        files={"file": ("bad.db", b"not a sqlite file", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "valid SQLite" in resp.text
```

- [ ] **Step 2: Run tests**

Run: `pytest tests/test_data_mgmt.py -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_data_mgmt.py
git commit -m "test(m11): add data management route tests"
```

---

### Task 6: Rule Pack Validation CLI

**Files:**
- Create: `scripts/validate_rule_pack.py`

- [ ] **Step 1: Create the scripts directory and CLI tool**

```python
#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate a Tax Co-Pilot rule pack directory.

Usage:
    python scripts/validate_rule_pack.py rule_packs/state/CA/2024
    python scripts/validate_rule_pack.py rule_packs/federal/2024

Exit codes:
    0 — Pack is valid
    1 — Validation failed
"""

import argparse
import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.rule_loader import RulePack, RulePackError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a Tax Co-Pilot rule pack directory."
    )
    parser.add_argument(
        "pack_dir",
        type=Path,
        help="Path to the rule pack directory (e.g., rule_packs/state/CA/2024)",
    )
    args = parser.parse_args()

    pack_dir: Path = args.pack_dir
    if not pack_dir.is_dir():
        print(f"ERROR: {pack_dir} is not a directory", file=sys.stderr)
        return 1

    try:
        pack = RulePack.load(pack_dir)
    except RulePackError as e:
        print(f"VALIDATION FAIL: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    print(f"OK: {pack.jurisdiction} {pack.tax_year} v{pack.version}")
    print(f"    Rules: {len(pack.rules)}")
    print(f"    Checksum: {pack.checksum}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Verify it works on existing packs**

Run: `python scripts/validate_rule_pack.py rule_packs/federal/2024`
Expected: `OK: federal 2024 v1.0.0` (or similar)

Run: `python scripts/validate_rule_pack.py rule_packs/state/CA/2024`
Expected: `OK: CA 2024 v1.0.0`

- [ ] **Step 3: Verify it fails on a bad path**

Run: `python scripts/validate_rule_pack.py /tmp/nonexistent; echo "exit: $?"`
Expected: Exit code 1, error message

- [ ] **Step 4: Commit**

```bash
git add scripts/validate_rule_pack.py
git commit -m "feat(m11): add rule pack validation CLI"
```

---

### Task 7: Rule Pack Authoring Guide

**Files:**
- Create: `docs/RULE_PACK_AUTHORING.md`

- [ ] **Step 1: Write the authoring guide**

Create `docs/RULE_PACK_AUTHORING.md` with SPDX header and comprehensive documentation covering:

1. **Overview** — What rule packs are, how the engine uses them
2. **Directory Structure** — `rule_packs/{jurisdiction}/{year}/` with manifest + rules
3. **Manifest Format** — version, tax_year, jurisdiction fields
4. **The Four Rule Types** — With complete YAML examples:
   - `formula` — Arithmetic expressions with named inputs
   - `lookup` — Constant table keyed by filing status
   - `sum` — Add all values in a list
   - `bracket_table` — Progressive tax brackets by filing status
5. **Expression Mini-Language** — `+`, `-`, `*`, `/`, `max()`, `min()`, parens, variable refs, literals
6. **The Constants System** — How to define and reference constant tables
7. **Namespace Conventions** — `fed.{year}.*`, `{state}.{year}.*`
8. **Input References** — `input.filing_status`, `input.withholding.state.{ST}`, cross-pack refs
9. **Rounding** — `ROUND_HALF_UP`, `rounding_precision`
10. **Worked Example** — Complete minimal state rule pack from scratch
11. **Validation** — Using `scripts/validate_rule_pack.py`

Note: `docs/STATE_AUTHORING_GUIDE.md` already covers state-specific onboarding. This guide is broader — it covers the rule system itself for both federal and state packs.

- [ ] **Step 2: Commit**

```bash
git add docs/RULE_PACK_AUTHORING.md
git commit -m "docs(m11): add rule pack authoring guide"
```

---

### Task 8: GitHub Contribution Templates

**Files:**
- Create: `.github/ISSUE_TEMPLATE/new_state.md`
- Create: `.github/PULL_REQUEST_TEMPLATE.md`

- [ ] **Step 1: Create new state issue template**

```markdown
---
name: New State Tax Pack
about: Request or contribute a new state income tax rule pack
title: "[State] Add {STATE_CODE} state rule pack for {YEAR}"
labels: "state-expansion"
assignees: ""
---

## State Information

- **State:** (e.g., CA, NY, IL)
- **Tax Year:** (e.g., 2024)
- **Tax Structure:** (Progressive brackets / Flat rate / No income tax)

## Tax Details

- Standard deduction amounts by filing status
- Tax bracket thresholds and rates (or flat rate)
- Any surtaxes or special provisions
- Official source URL for tax tables

## Checklist

- [ ] I have verified the tax rates against official state documentation
- [ ] I have noted the filing statuses that apply
- [ ] I have identified any state-specific deductions or credits
```

- [ ] **Step 2: Create PR template**

```markdown
## Summary

Brief description of changes.

## Type

- [ ] New state rule pack
- [ ] Rule pack update (existing state/year)
- [ ] Bug fix
- [ ] Feature
- [ ] Documentation

## Checklist

- [ ] `ruff check .` passes
- [ ] `mypy .` passes
- [ ] `pytest` passes (all existing + new tests)
- [ ] Rule pack validates: `python scripts/validate_rule_pack.py <path>`
- [ ] Bracket tables sourced from official government documentation
- [ ] SPDX license headers present on new files
- [ ] README.md repository tree updated (if files added/removed)
- [ ] CHANGELOG.md updated

## Test Plan

Describe how you tested these changes.

## Sources

Link to official tax documentation used for rates/thresholds.
```

- [ ] **Step 3: Commit**

```bash
git add .github/ISSUE_TEMPLATE/new_state.md .github/PULL_REQUEST_TEMPLATE.md
git commit -m "docs(m11): add new state issue template and PR template"
```

---

### Task 9: Update README Tree, CHANGELOG, Session Log, Final Verification

**Files:**
- Modify: `README.md`
- Modify: `CHANGELOG.md`
- Modify: `.agent_tools/05_session_log.md`

- [ ] **Step 1: Run tree discovery and update README.md**

```bash
find . -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -path '*/.mypy_cache/*' -not -path '*/.ruff_cache/*' | sort
```

Update the tree in README.md to include all new files:
- `scripts/validate_rule_pack.py`
- `tests/test_data_mgmt.py`
- `docs/RULE_PACK_AUTHORING.md`
- `.github/PULL_REQUEST_TEMPLATE.md`
- `.github/ISSUE_TEMPLATE/new_state.md`

- [ ] **Step 2: Add CHANGELOG entry**

```
- **Milestone 11 — Data Management & DX (complete):** Full return export/import (JSON round-trip), database backup/restore, run tagging and notes with inline editing, rule pack validation CLI (`scripts/validate_rule_pack.py`), rule pack authoring guide, new-state issue template and PR template.
```

- [ ] **Step 3: Append session log**

- [ ] **Step 4: Final verification**

Run: `ruff check . && mypy . && pytest`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add README.md CHANGELOG.md .agent_tools/05_session_log.md
git commit -m "docs: update repository tree and changelog for M11"
```
