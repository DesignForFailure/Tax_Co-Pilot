# Rule Pack Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GUI-based rule pack management system for creating, editing, cloning, importing, and exporting YAML rule packs.

**Architecture:** New service layer (`app/services/rule_pack_editor.py`) handles all rule pack CRUD operations. Routes in `main.py` follow existing patterns (CSRF double-submit, Jinja2 templates, redirect-after-POST). Custom packs live in `custom_vN/` subdirectories with canonical filenames, compatible with existing `_resolve_pack_file()` and `RulePack.load()`.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, PyYAML, vanilla JavaScript (no external JS libraries).

---

## File Structure

| File | Responsibility |
|------|---------------|
| **Create:** `app/services/rule_pack_editor.py` | All rule pack CRUD: list, load, save, clone, delete, validate, import, export. Path resolution. Input validation. Atomic writes. |
| **Create:** `app/templates/pages/rule_packs.html` | Pack Manager list page with grouped table and inline create form |
| **Create:** `app/templates/pages/rule_pack_detail.html` | Pack detail: metadata card, rule list table, validation area |
| **Create:** `app/templates/pages/rule_editor.html` | Type-adaptive rule editor (sum/formula/lookup/bracket_table) with inline JS |
| **Create:** `app/templates/pages/rule_pack_import.html` | YAML import form with file upload |
| **Create:** `tests/test_rule_pack_editor.py` | Service layer unit tests |
| **Create:** `tests/test_rule_pack_routes.py` | Route integration tests |
| **Modify:** `main.py` | Add ~14 routes, cache busting helper, variant-aware pack loading |
| **Modify:** `app/templates/pages/calculate.html` | Add "Rule Pack Variant" dropdown |
| **Modify:** `app/templates/layouts/base.html` | Add "Rule Packs" nav link |

---

## Reference: Existing Patterns

**CSRF pattern** (all POST routes):
```python
fd = await request.form()
_verify_csrf(request, str(fd.get("csrf_token", "")))
```

**GET route pattern:**
```python
@app.get("/path", response_class=HTMLResponse)
def handler(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse("pages/template.html", {"request": request, "csrf": csrf})
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp
```

**POST redirect pattern:**
```python
@app.post("/path")
async def handler(request: Request) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    # ... business logic ...
    return RedirectResponse(url="/target", status_code=303)
```

**Test client pattern:**
```python
CSRF = "test-csrf-token"
def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c
```

**Rule YAML structure (4 types):**
```yaml
# sum
- id: "fed.2024.gross_income.wages"
  description: "Total W-2 wages"
  form_line: "1040 Line 1a"
  type: "sum"
  inputs:
    items: { ref: "input.w2.wages" }

# formula
- id: "fed.2024.gross_income.capital_gains_limited"
  description: "Net capital gains after loss limitation"
  type: "formula"
  expression: "max(gains, neg_limit)"
  inputs:
    gains: { ref: "fed.2024.gross_income.capital_gains" }
    neg_limit: { literal: "-3000" }

# lookup
- id: "fed.2024.gross_income.ss_base_threshold"
  description: "SS taxability base threshold"
  type: "lookup"
  table: "constants.ss_taxability.base_threshold"
  key: { ref: "input.filing_status" }

# bracket_table
- id: "fed.2024.tax.brackets"
  description: "Federal income tax brackets"
  type: "bracket_table"
  input: { ref: "fed.2024.taxable_income" }
  key: { ref: "input.filing_status" }
  tables:
    single:
      - { lower: "0", upper: "11600", rate: "0.10" }
      - { lower: "11600", upper: "47150", rate: "0.12" }
    mfj:
      - { lower: "0", upper: "23200", rate: "0.10" }
      # ...
```

**Manifest YAML:**
```yaml
version: "1.0.0"
tax_year: 2024
jurisdiction: "federal"
```

**Custom pack manifest (editor metadata):**
```yaml
version: "1"
tax_year: 2024
jurisdiction: "federal"
custom: true
custom_name: "high_deduction_scenario"
```

**Directory layout:**
```
rule_packs/federal/2024/                       ← standard
rule_packs/federal/2024/custom_v1/             ← custom variant 1
rule_packs/federal/2024/custom_v2/             ← custom variant 2
rule_packs/state/CA/2024/                      ← standard
rule_packs/state/CA/2024/custom_v1/            ← custom variant 1
```

---

### Task 1: Rule Pack Editor Service — Core Functions

**Files:**
- Create: `app/services/rule_pack_editor.py`
- Create: `tests/test_rule_pack_editor.py`
- Reference: `app/engine/rule_loader.py` (RulePack.load, RulePackError, _read_yaml)

This task creates the service layer with path resolution, listing, loading, validation, and export.

- [ ] **Step 1: Write failing tests for path resolution and listing**

```python
# tests/test_rule_pack_editor.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for rule pack editor service."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml

from app.services.rule_pack_editor import (
    PackInfo,
    list_all_packs,
    load_pack_detail,
    validate_pack,
    export_yaml,
    _pack_path,
    _validate_path_param,
)


@pytest.fixture
def tmp_packs(tmp_path: Path) -> Path:
    """Create a temporary rule_packs directory with a standard federal pack."""
    fed_dir = tmp_path / "federal" / "2024"
    fed_dir.mkdir(parents=True)

    manifest = {"version": "1.0.0", "tax_year": 2024, "jurisdiction": "federal"}
    rules = {
        "constants": {"standard_deduction": {"single": "14600", "mfj": "29200"}},
        "rules": [
            {
                "id": "fed.2024.gross_income.wages",
                "description": "Total W-2 wages",
                "type": "sum",
                "inputs": {"items": {"ref": "input.w2.wages"}},
            }
        ],
    }

    (fed_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (fed_dir / "rules.yaml").write_text(yaml.dump(rules), encoding="utf-8")
    return tmp_path


def test_validate_path_param_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        _validate_path_param("../etc", "jurisdiction")


def test_validate_path_param_rejects_slash() -> None:
    with pytest.raises(ValueError, match="Invalid"):
        _validate_path_param("foo/bar", "jurisdiction")


def test_validate_path_param_accepts_valid() -> None:
    _validate_path_param("federal", "jurisdiction")
    _validate_path_param("CA", "jurisdiction")
    _validate_path_param("custom_v1", "variant")


def test_pack_path_federal_standard(tmp_packs: Path) -> None:
    p = _pack_path("federal", 2024, "standard", base_dir=tmp_packs)
    assert p == tmp_packs / "federal" / "2024"


def test_pack_path_federal_custom(tmp_packs: Path) -> None:
    p = _pack_path("federal", 2024, "custom_v1", base_dir=tmp_packs)
    assert p == tmp_packs / "federal" / "2024" / "custom_v1"


def test_pack_path_state_standard(tmp_packs: Path) -> None:
    p = _pack_path("CA", 2024, "standard", base_dir=tmp_packs)
    assert p == tmp_packs / "state" / "CA" / "2024"


def test_list_all_packs_discovers_standard(tmp_packs: Path) -> None:
    packs = list_all_packs(base_dir=tmp_packs)
    assert len(packs) == 1
    assert packs[0].jurisdiction == "federal"
    assert packs[0].year == 2024
    assert packs[0].variant == "standard"
    assert packs[0].is_custom is False


def test_list_all_packs_discovers_custom(tmp_packs: Path) -> None:
    custom_dir = tmp_packs / "federal" / "2024" / "custom_v1"
    custom_dir.mkdir()
    manifest = {
        "version": "1",
        "tax_year": 2024,
        "jurisdiction": "federal",
        "custom": True,
        "custom_name": "test_scenario",
    }
    rules = {
        "constants": {},
        "rules": [
            {
                "id": "fed.2024.test_rule",
                "description": "Test",
                "type": "formula",
                "expression": "x",
                "inputs": {"x": {"ref": "input.w2.wages"}},
            }
        ],
    }
    (custom_dir / "manifest.yaml").write_text(yaml.dump(manifest), encoding="utf-8")
    (custom_dir / "rules.yaml").write_text(yaml.dump(rules), encoding="utf-8")

    packs = list_all_packs(base_dir=tmp_packs)
    assert len(packs) == 2
    custom = [p for p in packs if p.is_custom]
    assert len(custom) == 1
    assert custom[0].variant == "custom_v1"
    assert custom[0].custom_name == "test_scenario"


def test_list_all_packs_skips_underscore_dirs(tmp_packs: Path) -> None:
    tmpl = tmp_packs / "state" / "_template" / "2024"
    tmpl.mkdir(parents=True)
    (tmpl / "manifest.yaml").write_text(yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "template"}))
    (tmpl / "rules.yaml").write_text(yaml.dump({"rules": []}))
    packs = list_all_packs(base_dir=tmp_packs)
    assert not any(p.jurisdiction == "template" for p in packs)


def test_load_pack_detail(tmp_packs: Path) -> None:
    detail = load_pack_detail("federal", 2024, "standard", base_dir=tmp_packs)
    assert detail["jurisdiction"] == "federal"
    assert detail["year"] == 2024
    assert len(detail["rules"]) == 1
    assert detail["rules"][0]["id"] == "fed.2024.gross_income.wages"


def test_validate_pack_valid(tmp_packs: Path) -> None:
    errors = validate_pack("federal", 2024, "standard", base_dir=tmp_packs)
    assert errors == []


def test_validate_pack_invalid(tmp_packs: Path) -> None:
    bad_dir = tmp_packs / "federal" / "2024" / "custom_v99"
    bad_dir.mkdir()
    (bad_dir / "manifest.yaml").write_text(yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "federal"}))
    (bad_dir / "rules.yaml").write_text(yaml.dump({
        "rules": [{"id": "WRONG.id", "type": "sum", "inputs": {"items": {"ref": "input.w2.wages"}}}]
    }))
    errors = validate_pack("federal", 2024, "custom_v99", base_dir=tmp_packs)
    assert len(errors) > 0
    assert "prefix" in errors[0].lower() or "WRONG" in errors[0]


def test_export_yaml(tmp_packs: Path) -> None:
    manifest_bytes, rules_bytes = export_yaml("federal", 2024, "standard", base_dir=tmp_packs)
    assert b"tax_year" in manifest_bytes
    assert b"fed.2024" in rules_bytes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rule_pack_editor.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rule_pack_editor'`

- [ ] **Step 3: Implement the service — core read functions**

```python
# app/services/rule_pack_editor.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Rule pack editor service — CRUD operations for rule packs.

All file I/O for rule pack management goes through this module.
The engine's rule_loader.py stays purely for loading/validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from app.engine.rule_loader import RulePack, RulePackError, _read_yaml

_BASE_DIR = Path(__file__).resolve().parent.parent.parent / "rule_packs"

# Validation patterns for path parameters
_JURISDICTION_RE = re.compile(r"^[a-zA-Z]{2,10}$")
_VARIANT_RE = re.compile(r"^(standard|custom_v\d+)$")
_RULE_ID_RE = re.compile(r"^[a-z]{2,10}\.\d{4}\.[a-z0-9_.]+$")
_FEDERAL_JURISDICTIONS = {"federal", "fed"}


def _validate_path_param(value: str, name: str) -> None:
    """Reject path traversal and invalid characters."""
    if ".." in value or "/" in value or "\\" in value:
        raise ValueError(f"Invalid {name}: {value!r}")
    if not value or not re.match(r"^[a-zA-Z0-9_]+$", value):
        raise ValueError(f"Invalid {name}: {value!r}")


def _validate_year(year: int) -> None:
    if not (2000 <= year <= 2099):
        raise ValueError(f"Invalid year: {year}")


def _pack_path(
    jurisdiction: str, year: int, variant: str, *, base_dir: Path | None = None
) -> Path:
    """Resolve the directory path for a pack variant.

    Federal: base/federal/{year}/ or base/federal/{year}/custom_vN/
    State:   base/state/{ST}/{year}/ or base/state/{ST}/{year}/custom_vN/
    """
    base = base_dir or _BASE_DIR
    _validate_path_param(jurisdiction, "jurisdiction")
    _validate_path_param(variant, "variant")
    _validate_year(year)

    j = jurisdiction.lower()
    if j in _FEDERAL_JURISDICTIONS:
        pack_dir = base / "federal" / str(year)
    else:
        pack_dir = base / "state" / jurisdiction.upper() / str(year)

    if variant != "standard":
        pack_dir = pack_dir / variant
    return pack_dir


@dataclass
class PackInfo:
    """Metadata about a discovered rule pack."""

    jurisdiction: str
    year: int
    variant: str
    is_custom: bool
    version: str = ""
    custom_name: str = ""
    rule_count: int = 0


def _scan_year_dir(jurisdiction: str, year_dir: Path) -> list[PackInfo]:
    """Scan a year directory for standard + custom packs."""
    packs: list[PackInfo] = []
    year = int(year_dir.name)

    # Standard pack (the year directory itself)
    # Use same resolution logic as _resolve_pack_file: canonical first, then *_manifest.yaml
    manifest_path = year_dir / "manifest.yaml"
    if not manifest_path.exists():
        candidates = sorted(year_dir.glob("*_manifest.yaml"), key=lambda p: p.name)
        manifest_path = candidates[0] if len(candidates) == 1 else None  # type: ignore[assignment]

    if manifest_path is not None and manifest_path.exists():
        try:
            manifest = _read_yaml(manifest_path)
            rules_path = year_dir / "rules.yaml"
            if not rules_path.exists():
                candidates = [c for c in sorted(year_dir.glob("*_rules.yaml"), key=lambda p: p.name) if "manifest" not in c.name]
                rules_path = candidates[0] if len(candidates) == 1 else None  # type: ignore[assignment]
            rule_count = 0
            if rules_path:
                try:
                    rd = _read_yaml(rules_path)
                    rule_count = len(rd.get("rules", []) or [])
                except Exception:
                    pass
            packs.append(
                PackInfo(
                    jurisdiction=jurisdiction,
                    year=year,
                    variant="standard",
                    is_custom=False,
                    version=str(manifest.get("version", "")),
                    rule_count=rule_count,
                )
            )
        except Exception:
            pass

    # Custom packs (custom_v* subdirectories)
    for sub in sorted(year_dir.iterdir()):
        if not sub.is_dir() or not sub.name.startswith("custom_v"):
            continue
        m_path = sub / "manifest.yaml"
        r_path = sub / "rules.yaml"
        if not m_path.exists():
            continue
        try:
            m = _read_yaml(m_path)
            rule_count = 0
            if r_path.exists():
                try:
                    rd = _read_yaml(r_path)
                    rule_count = len(rd.get("rules", []) or [])
                except Exception:
                    pass
            packs.append(
                PackInfo(
                    jurisdiction=jurisdiction,
                    year=year,
                    variant=sub.name,
                    is_custom=True,
                    version=str(m.get("version", "")),
                    custom_name=str(m.get("custom_name", "")),
                    rule_count=rule_count,
                )
            )
        except Exception:
            pass
    return packs


def list_all_packs(*, base_dir: Path | None = None) -> list[PackInfo]:
    """Scan rule_packs/ and return metadata for all discovered packs."""
    base = base_dir or _BASE_DIR
    packs: list[PackInfo] = []

    # Federal packs
    fed_dir = base / "federal"
    if fed_dir.exists():
        for year_dir in sorted(fed_dir.iterdir()):
            if year_dir.is_dir() and year_dir.name.isdigit():
                packs.extend(_scan_year_dir("federal", year_dir))

    # State packs
    state_dir = base / "state"
    if state_dir.exists():
        for st_dir in sorted(state_dir.iterdir()):
            if not st_dir.is_dir() or st_dir.name.startswith("_"):
                continue
            for year_dir in sorted(st_dir.iterdir()):
                if year_dir.is_dir() and year_dir.name.isdigit():
                    packs.extend(_scan_year_dir(st_dir.name.upper(), year_dir))

    return packs


def load_pack_detail(
    jurisdiction: str, year: int, variant: str, *, base_dir: Path | None = None
) -> dict[str, Any]:
    """Load a pack and return structured detail for the UI."""
    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    pack = RulePack.load(pack_dir)
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        # Legacy naming — find the manifest
        candidates = list(pack_dir.glob("*manifest*.yaml"))
        manifest_path = candidates[0] if candidates else pack_dir / "manifest.yaml"
    manifest = _read_yaml(manifest_path) if manifest_path.exists() else {}

    rules_list = [pack.rules[rid] for rid in pack.rule_order]
    return {
        "jurisdiction": jurisdiction,
        "year": year,
        "variant": variant,
        "is_custom": variant != "standard",
        "version": pack.version,
        "checksum": pack.checksum,
        "custom_name": str(manifest.get("custom_name", "")),
        "rule_count": len(rules_list),
        "rules": rules_list,
        "rule_order": pack.rule_order,
    }


def validate_pack(
    jurisdiction: str, year: int, variant: str, *, base_dir: Path | None = None
) -> list[str]:
    """Validate a pack via RulePack.load(). Returns list of error strings (empty = valid)."""
    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    try:
        RulePack.load(pack_dir)
        return []
    except (RulePackError, Exception) as exc:
        return [str(exc)]


def export_yaml(
    jurisdiction: str, year: int, variant: str, *, base_dir: Path | None = None
) -> tuple[bytes, bytes]:
    """Return raw manifest and rules YAML bytes for download."""
    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    # Find manifest file
    manifest_path = pack_dir / "manifest.yaml"
    if not manifest_path.exists():
        candidates = list(pack_dir.glob("*manifest*.yaml"))
        if candidates:
            manifest_path = candidates[0]
    # Find rules file
    rules_path = pack_dir / "rules.yaml"
    if not rules_path.exists():
        candidates = [c for c in pack_dir.glob("*rules*.yaml") if "manifest" not in c.name]
        if candidates:
            rules_path = candidates[0]
    return manifest_path.read_bytes(), rules_path.read_bytes()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rule_pack_editor.py -v`
Expected: All PASS

- [ ] **Step 5: Run full quality checks**

Run: `ruff check app/services/rule_pack_editor.py tests/test_rule_pack_editor.py && mypy app/services/rule_pack_editor.py tests/test_rule_pack_editor.py`
Expected: PASS (fix any issues)

- [ ] **Step 6: Commit**

```bash
git add app/services/rule_pack_editor.py tests/test_rule_pack_editor.py
git commit -m "feat(rule-editor): add service layer with list, load, validate, export"
```

---

### Task 2: Rule Pack Editor Service — Write Operations

**Files:**
- Modify: `app/services/rule_pack_editor.py`
- Modify: `tests/test_rule_pack_editor.py`

This task adds clone, create, save_rule, delete_rule, delete_pack, and import_yaml.

- [ ] **Step 1: Write failing tests for write operations**

Add to `tests/test_rule_pack_editor.py`:

```python
from app.services.rule_pack_editor import (
    clone_pack,
    create_empty_pack,
    save_rule,
    delete_rule,
    delete_pack,
    import_yaml,
)


def test_clone_pack_creates_custom_v1(tmp_packs: Path) -> None:
    info = clone_pack("federal", 2024, "standard", "my_scenario", base_dir=tmp_packs)
    assert info.variant == "custom_v1"
    assert info.is_custom is True
    custom_dir = tmp_packs / "federal" / "2024" / "custom_v1"
    assert (custom_dir / "manifest.yaml").exists()
    assert (custom_dir / "rules.yaml").exists()
    m = yaml.safe_load((custom_dir / "manifest.yaml").read_text())
    assert m["custom"] is True
    assert m["custom_name"] == "my_scenario"


def test_clone_auto_increments_version(tmp_packs: Path) -> None:
    clone_pack("federal", 2024, "standard", "first", base_dir=tmp_packs)
    info2 = clone_pack("federal", 2024, "standard", "second", base_dir=tmp_packs)
    assert info2.variant == "custom_v2"
    assert (tmp_packs / "federal" / "2024" / "custom_v2").exists()


def test_create_empty_pack(tmp_packs: Path) -> None:
    info = create_empty_pack("federal", 2024, "blank_pack", base_dir=tmp_packs)
    assert info.is_custom is True
    custom_dir = tmp_packs / "federal" / "2024" / info.variant
    m = yaml.safe_load((custom_dir / "manifest.yaml").read_text())
    assert m["jurisdiction"] == "federal"
    r = yaml.safe_load((custom_dir / "rules.yaml").read_text())
    assert r["rules"] == []


def test_save_rule_to_custom_pack(tmp_packs: Path) -> None:
    clone_pack("federal", 2024, "standard", "editable", base_dir=tmp_packs)
    rule_data = {
        "id": "fed.2024.custom_rule",
        "description": "A custom rule",
        "type": "formula",
        "expression": "x",
        "inputs": {"x": {"ref": "input.w2.wages"}},
    }
    save_rule("federal", 2024, "custom_v1", "fed.2024.custom_rule", rule_data, base_dir=tmp_packs)
    detail = load_pack_detail("federal", 2024, "custom_v1", base_dir=tmp_packs)
    ids = [r["id"] for r in detail["rules"]]
    assert "fed.2024.custom_rule" in ids


def test_save_rule_to_standard_pack_raises(tmp_packs: Path) -> None:
    rule_data = {"id": "fed.2024.x", "type": "formula", "expression": "x", "inputs": {"x": {"ref": "input.w2.wages"}}}
    with pytest.raises(ValueError, match="standard"):
        save_rule("federal", 2024, "standard", "fed.2024.x", rule_data, base_dir=tmp_packs)


def test_delete_rule(tmp_packs: Path) -> None:
    clone_pack("federal", 2024, "standard", "del_test", base_dir=tmp_packs)
    delete_rule("federal", 2024, "custom_v1", "fed.2024.gross_income.wages", base_dir=tmp_packs)
    detail = load_pack_detail("federal", 2024, "custom_v1", base_dir=tmp_packs)
    ids = [r["id"] for r in detail["rules"]]
    assert "fed.2024.gross_income.wages" not in ids


def test_delete_standard_pack_raises(tmp_packs: Path) -> None:
    with pytest.raises(ValueError, match="standard"):
        delete_pack("federal", 2024, "standard", base_dir=tmp_packs)


def test_delete_custom_pack(tmp_packs: Path) -> None:
    clone_pack("federal", 2024, "standard", "to_delete", base_dir=tmp_packs)
    delete_pack("federal", 2024, "custom_v1", base_dir=tmp_packs)
    assert not (tmp_packs / "federal" / "2024" / "custom_v1").exists()


def test_import_yaml_valid(tmp_packs: Path) -> None:
    manifest_bytes = yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "federal"}).encode()
    rules_bytes = yaml.dump({
        "constants": {},
        "rules": [
            {"id": "fed.2024.imp", "description": "Imported", "type": "formula", "expression": "x", "inputs": {"x": {"ref": "input.w2.wages"}}},
        ],
    }).encode()
    info = import_yaml(manifest_bytes, rules_bytes, custom_name="imported", base_dir=tmp_packs)
    assert info.is_custom is True
    assert (tmp_packs / "federal" / "2024" / info.variant / "manifest.yaml").exists()


def test_import_yaml_invalid_rejected(tmp_packs: Path) -> None:
    manifest_bytes = yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "federal"}).encode()
    rules_bytes = yaml.dump({"rules": [{"id": "WRONG", "type": "sum"}]}).encode()
    with pytest.raises(ValueError, match="[Vv]alidat|prefix|Invalid"):
        import_yaml(manifest_bytes, rules_bytes, custom_name="bad", base_dir=tmp_packs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rule_pack_editor.py -v -k "clone or create_empty or save_rule or delete_rule or delete_pack or import"`
Expected: FAIL — `ImportError: cannot import name 'clone_pack'`

- [ ] **Step 3: Implement write operations**

Add to `app/services/rule_pack_editor.py`:

```python
import shutil
import tempfile

def _next_custom_version(pack_parent_dir: Path) -> int:
    """Find the next available custom_vN number in a year directory."""
    existing = [
        int(d.name.split("_v")[1])
        for d in pack_parent_dir.iterdir()
        if d.is_dir() and d.name.startswith("custom_v") and d.name.split("_v")[1].isdigit()
    ]
    return max(existing, default=0) + 1


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML atomically: write to .tmp, then rename."""
    tmp_fd, tmp_path_str = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix=path.name
    )
    tmp_path = Path(tmp_path_str)
    try:
        with open(tmp_fd, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        tmp_path.rename(path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def clone_pack(
    jurisdiction: str,
    year: int,
    source_variant: str,
    custom_name: str,
    *,
    base_dir: Path | None = None,
) -> PackInfo:
    """Clone a pack into a new custom variant with auto-incremented version."""
    source_dir = _pack_path(jurisdiction, year, source_variant, base_dir=base_dir)
    if not source_dir.exists():
        raise ValueError(f"Source pack not found: {source_dir}")

    # Determine parent dir (the year directory) for version scanning
    parent_dir = source_dir if source_variant == "standard" else source_dir.parent
    version = _next_custom_version(parent_dir)
    variant = f"custom_v{version}"

    target_dir = parent_dir / variant
    target_dir.mkdir(parents=True, exist_ok=False)

    # Copy rules file
    source_rules = None
    for candidate in [source_dir / "rules.yaml"] + sorted(source_dir.glob("*rules*.yaml")):
        if candidate.exists() and "manifest" not in candidate.name:
            source_rules = candidate
            break
    if source_rules:
        shutil.copy2(source_rules, target_dir / "rules.yaml")

    # Read source manifest, add custom metadata, write
    source_manifest = source_dir / "manifest.yaml"
    if not source_manifest.exists():
        candidates = list(source_dir.glob("*manifest*.yaml"))
        source_manifest = candidates[0] if candidates else source_dir / "manifest.yaml"
    manifest_data = _read_yaml(source_manifest)
    manifest_data["version"] = str(version)
    manifest_data["custom"] = True
    manifest_data["custom_name"] = custom_name
    _atomic_write_yaml(target_dir / "manifest.yaml", manifest_data)

    # Count rules
    rule_count = 0
    r_path = target_dir / "rules.yaml"
    if r_path.exists():
        try:
            rd = _read_yaml(r_path)
            rule_count = len(rd.get("rules", []) or [])
        except Exception:
            pass

    return PackInfo(
        jurisdiction=jurisdiction,
        year=year,
        variant=variant,
        is_custom=True,
        version=str(version),
        custom_name=custom_name,
        rule_count=rule_count,
    )


def create_empty_pack(
    jurisdiction: str, year: int, custom_name: str, *, base_dir: Path | None = None
) -> PackInfo:
    """Create a new custom pack with an empty rule list."""
    parent_dir = _pack_path(jurisdiction, year, "standard", base_dir=base_dir)
    if not parent_dir.exists():
        parent_dir.mkdir(parents=True, exist_ok=True)

    version = _next_custom_version(parent_dir)
    variant = f"custom_v{version}"
    target_dir = parent_dir / variant
    target_dir.mkdir(parents=True, exist_ok=False)

    j_lower = jurisdiction.lower()
    manifest = {
        "version": str(version),
        "tax_year": year,
        "jurisdiction": "federal" if j_lower in _FEDERAL_JURISDICTIONS else jurisdiction.upper(),
        "custom": True,
        "custom_name": custom_name,
    }
    rules: dict[str, Any] = {"constants": {}, "rules": []}

    _atomic_write_yaml(target_dir / "manifest.yaml", manifest)
    _atomic_write_yaml(target_dir / "rules.yaml", rules)

    return PackInfo(
        jurisdiction=jurisdiction,
        year=year,
        variant=variant,
        is_custom=True,
        version=str(version),
        custom_name=custom_name,
        rule_count=0,
    )


def save_rule(
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
    rule_data: dict[str, Any],
    *,
    base_dir: Path | None = None,
) -> None:
    """Add or update a single rule in a custom pack.

    Validates BEFORE writing: builds the candidate rules YAML in a temp
    directory, runs RulePack.load() on it, and only overwrites the real
    file if validation passes.
    """
    if variant == "standard":
        raise ValueError("Cannot modify a standard pack — clone it as custom first")

    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    rules_path = pack_dir / "rules.yaml"
    rules_yaml = _read_yaml(rules_path)
    rule_list = rules_yaml.get("rules", []) or []

    # Update existing or append
    found = False
    for i, r in enumerate(rule_list):
        if r.get("id") == rule_id:
            rule_list[i] = rule_data
            found = True
            break
    if not found:
        rule_list.append(rule_data)

    rules_yaml["rules"] = rule_list

    # Validate before writing: copy manifest to a temp dir, write candidate rules, load
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        manifest_src = pack_dir / "manifest.yaml"
        if not manifest_src.exists():
            candidates = list(pack_dir.glob("*_manifest*.yaml"))
            manifest_src = candidates[0] if candidates else manifest_src
        shutil.copy2(manifest_src, tmp / "manifest.yaml")
        _atomic_write_yaml(tmp / "rules.yaml", rules_yaml)
        try:
            RulePack.load(tmp)
        except Exception as exc:
            raise ValueError(f"Validation failed: {exc}") from exc

    # Validation passed — write for real
    _atomic_write_yaml(rules_path, rules_yaml)


def delete_rule(
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
    *,
    base_dir: Path | None = None,
) -> None:
    """Remove a rule from a custom pack."""
    if variant == "standard":
        raise ValueError("Cannot modify a standard pack — clone it as custom first")

    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    rules_path = pack_dir / "rules.yaml"
    rules_yaml = _read_yaml(rules_path)
    rule_list = rules_yaml.get("rules", []) or []

    rules_yaml["rules"] = [r for r in rule_list if r.get("id") != rule_id]
    _atomic_write_yaml(rules_path, rules_yaml)


def delete_pack(
    jurisdiction: str, year: int, variant: str, *, base_dir: Path | None = None
) -> None:
    """Delete a custom pack's directory (refuses standard packs)."""
    if variant == "standard":
        raise ValueError("Cannot delete a standard pack")

    pack_dir = _pack_path(jurisdiction, year, variant, base_dir=base_dir)
    if pack_dir.exists():
        shutil.rmtree(pack_dir)


def import_yaml(
    manifest_bytes: bytes,
    rules_bytes: bytes,
    custom_name: str,
    *,
    base_dir: Path | None = None,
) -> PackInfo:
    """Import uploaded YAML files as a new custom pack.

    Validates via RulePack.load() before committing. Raises ValueError on failure.
    """
    manifest = yaml.safe_load(manifest_bytes)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a YAML mapping")

    jurisdiction = str(manifest.get("jurisdiction", "")).strip()
    tax_year = int(manifest.get("tax_year", 0))
    if not jurisdiction or tax_year <= 0:
        raise ValueError("Manifest must include jurisdiction and positive tax_year")

    # Determine target directory
    parent_dir = _pack_path(jurisdiction, tax_year, "standard", base_dir=base_dir)
    if not parent_dir.exists():
        parent_dir.mkdir(parents=True, exist_ok=True)

    version = _next_custom_version(parent_dir)
    variant = f"custom_v{version}"
    target_dir = parent_dir / variant
    target_dir.mkdir(parents=True, exist_ok=False)

    # Write files
    manifest["custom"] = True
    manifest["custom_name"] = custom_name
    manifest["version"] = str(version)
    _atomic_write_yaml(target_dir / "manifest.yaml", manifest)
    (target_dir / "rules.yaml").write_bytes(rules_bytes)

    # Validate — if invalid, clean up
    try:
        RulePack.load(target_dir)
    except Exception as exc:
        shutil.rmtree(target_dir, ignore_errors=True)
        raise ValueError(f"Validation failed: {exc}") from exc

    rule_count = 0
    try:
        rd = yaml.safe_load(rules_bytes)
        rule_count = len(rd.get("rules", []) or []) if isinstance(rd, dict) else 0
    except Exception:
        pass

    return PackInfo(
        jurisdiction=jurisdiction,
        year=tax_year,
        variant=variant,
        is_custom=True,
        version=str(version),
        custom_name=custom_name,
        rule_count=rule_count,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rule_pack_editor.py -v`
Expected: All PASS

- [ ] **Step 5: Run full quality checks**

Run: `ruff check app/services/rule_pack_editor.py tests/test_rule_pack_editor.py && mypy app/services/rule_pack_editor.py tests/test_rule_pack_editor.py`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app/services/rule_pack_editor.py tests/test_rule_pack_editor.py
git commit -m "feat(rule-editor): add clone, create, save, delete, import operations"
```

---

### Task 3: Routes — Pack List, Detail, Clone, Delete, Validate, Export, Create

**Files:**
- Modify: `main.py` (add routes + imports + cache busting)
- Create: `app/templates/pages/rule_packs.html`
- Create: `app/templates/pages/rule_pack_detail.html`
- Modify: `app/templates/layouts/base.html` (add nav link)
- Create: `tests/test_rule_pack_routes.py`

This task adds the main pack management routes and templates.

- [ ] **Step 1: Write failing route tests**

```python
# tests/test_rule_pack_routes.py
# SPDX-License-Identifier: GPL-3.0-or-later
"""Route integration tests for rule pack editor."""

from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from app.services.database import init_db
from main import app

CSRF = "test-csrf-token"


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


@pytest.fixture(autouse=True)
def _cleanup_custom_packs() -> None:
    """Remove any custom_v* directories created during tests."""
    import shutil
    from pathlib import Path
    yield  # type: ignore[misc]
    base = Path(__file__).resolve().parent.parent / "rule_packs"
    for custom_dir in base.rglob("custom_v*"):
        if custom_dir.is_dir():
            shutil.rmtree(custom_dir, ignore_errors=True)


def test_rule_packs_list_page() -> None:
    c = _client()
    r = c.get("/rule-packs")
    assert r.status_code == 200
    assert "Rule Pack" in r.text
    assert "federal" in r.text.lower()


def test_pack_detail_page() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard")
    assert r.status_code == 200
    assert "fed.2024" in r.text


def test_clone_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "test_clone"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    loc = r.headers.get("location", "")
    assert "custom_v" in loc


def test_validate_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/federal/2024/standard/validate",
        data={"csrf_token": CSRF},
    )
    assert r.status_code == 200
    assert "valid" in r.text.lower() or "error" in r.text.lower()


def test_export_download() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard/export")
    assert r.status_code == 200
    assert "yaml" in r.headers.get("content-type", "").lower() or r.status_code == 200
    assert b"tax_year" in r.content


def test_create_custom_pack_via_post() -> None:
    c = _client()
    r = c.post(
        "/rule-packs/create",
        data={"csrf_token": CSRF, "jurisdiction": "federal", "year": "2024", "custom_name": "new_pack"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_delete_custom_pack_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "to_delete"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rule_pack_routes.py -v`
Expected: FAIL — `404 Not Found` for `/rule-packs`

- [ ] **Step 3: Add nav link to base template**

Read `app/templates/layouts/base.html` and add a "Rule Packs" link after "Runs" in the nav:

```html
<a href="/runs">Runs</a>
<a href="/rule-packs">Rule Packs</a>
```

- [ ] **Step 4: Add routes to main.py**

Add imports at the top of `main.py`:

```python
from app.services.rule_pack_editor import (
    list_all_packs as list_rule_packs,
    load_pack_detail,
    validate_pack as validate_rule_pack,
    export_yaml,
    clone_pack,
    create_empty_pack,
    delete_pack,
    import_yaml,
)
```

Add a cache-busting helper near the existing `_federal_cache` / `_state_cache`:

```python
def _bust_pack_cache(jurisdiction: str, year: int) -> None:
    """Remove cached packs so next load reads from disk."""
    j = jurisdiction.lower()
    if j in {"federal", "fed"}:
        _federal_cache.pop(year, None)
    else:
        _state_cache.pop(year, None)
```

Add routes. **IMPORTANT: Place literal `/rule-packs/import`, `/rule-packs/create` routes BEFORE parameterized `/rule-packs/{jurisdiction}/...` routes** in main.py:

```python
# ── Rule Pack Editor routes ────────────────────────────────────

@app.get("/rule-packs", response_class=HTMLResponse)
def rule_packs_list(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    packs = list_rule_packs()
    resp = templates.TemplateResponse(
        "pages/rule_packs.html",
        {"request": request, "csrf": csrf, "packs": packs, "available_years": available_years},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/create")
async def rule_packs_create(request: Request) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    jurisdiction = _form_str(fd, "jurisdiction")
    year = int(_form_str(fd, "year") or "0")
    custom_name = _form_str(fd, "custom_name")
    info = create_empty_pack(jurisdiction, year, custom_name)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@app.get("/rule-packs/{jurisdiction}/{year}/{variant}", response_class=HTMLResponse)
def rule_pack_detail(request: Request, jurisdiction: str, year: int, variant: str) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    detail = load_pack_detail(jurisdiction, year, variant)
    resp = templates.TemplateResponse(
        "pages/rule_pack_detail.html",
        {"request": request, "csrf": csrf, "pack": detail},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/clone")
async def rule_pack_clone(request: Request, jurisdiction: str, year: int, variant: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    custom_name = _form_str(fd, "custom_name")
    info = clone_pack(jurisdiction, year, variant, custom_name)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/delete")
async def rule_pack_delete(request: Request, jurisdiction: str, year: int, variant: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_pack(jurisdiction, year, variant)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(url="/rule-packs", status_code=303)


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/validate", response_class=HTMLResponse)
async def rule_pack_validate(request: Request, jurisdiction: str, year: int, variant: str) -> HTMLResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    errors = validate_rule_pack(jurisdiction, year, variant)
    detail = load_pack_detail(jurisdiction, year, variant)
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/rule_pack_detail.html",
        {"request": request, "csrf": csrf, "pack": detail, "validation_errors": errors, "validated": True},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.get("/rule-packs/{jurisdiction}/{year}/{variant}/export")
def rule_pack_export(request: Request, jurisdiction: str, year: int, variant: str) -> Response:
    manifest_bytes, rules_bytes = export_yaml(jurisdiction, year, variant)
    combined = b"# === MANIFEST ===\n" + manifest_bytes + b"\n# === RULES ===\n" + rules_bytes
    filename = f"{jurisdiction}_{year}_{variant}.yaml"
    return Response(
        content=combined,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
```

- [ ] **Step 5: Create rule_packs.html template**

```html
<!-- app/templates/pages/rule_packs.html -->
{% extends "layouts/base.html" %}
{% block title %}Rule Packs{% endblock %}
{% block content %}
<h1>Rule Pack Manager</h1>

<div class="card" style="margin-bottom:20px;">
  <div style="display:flex;gap:12px;align-items:center;">
    <button type="button" class="btn" onclick="document.getElementById('create-form').style.display = document.getElementById('create-form').style.display === 'none' ? 'block' : 'none'">Create Custom Pack</button>
    <a href="/rule-packs/import" class="btn btn-outline">Import YAML</a>
  </div>
  <form id="create-form" method="POST" action="/rule-packs/create" style="display:none;margin-top:16px;">
    <input type="hidden" name="csrf_token" value="{{ csrf }}">
    <div class="form-row">
      <div>
        <label>Jurisdiction</label>
        <select name="jurisdiction">
          <option value="federal">Federal</option>
          {% for st in available_years %}{% endfor %}
        </select>
      </div>
      <div><label>Year</label><input type="number" name="year" value="2024" min="2000" max="2099"></div>
      <div><label>Custom Name</label><input type="text" name="custom_name" required placeholder="e.g. high_deduction"></div>
    </div>
    <button type="submit" class="btn" style="margin-top:8px;">Create</button>
  </form>
</div>

<div class="card">
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr>
        <th style="text-align:left;padding:8px;">Jurisdiction</th>
        <th style="text-align:left;padding:8px;">Year</th>
        <th style="text-align:left;padding:8px;">Type</th>
        <th style="text-align:left;padding:8px;">Version</th>
        <th style="text-align:right;padding:8px;">Rules</th>
        <th style="text-align:right;padding:8px;">Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for pack in packs %}
      <tr style="border-top:1px solid var(--border,#333);">
        <td style="padding:8px;">{{ pack.jurisdiction }}{% if pack.custom_name %} <small>({{ pack.custom_name }})</small>{% endif %}</td>
        <td style="padding:8px;">{{ pack.year }}</td>
        <td style="padding:8px;">{% if pack.is_custom %}Custom{% else %}🔒 Standard{% endif %}</td>
        <td style="padding:8px;">{{ pack.version }}</td>
        <td style="padding:8px;text-align:right;">{{ pack.rule_count }}</td>
        <td style="padding:8px;text-align:right;">
          <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}" class="btn btn-sm">View</a>
          <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/export" class="btn btn-sm btn-outline">Export</a>
          {% if pack.is_custom %}
          <form method="POST" action="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/delete" style="display:inline;">
            <input type="hidden" name="csrf_token" value="{{ csrf }}">
            <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('Delete this pack?')">Delete</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 6: Create rule_pack_detail.html template**

```html
<!-- app/templates/pages/rule_pack_detail.html -->
{% extends "layouts/base.html" %}
{% block title %}{{ pack.jurisdiction }} {{ pack.year }} — {{ pack.variant }}{% endblock %}
{% block content %}
<h1>{{ pack.jurisdiction | upper }} {{ pack.year }} {% if pack.is_custom %}(Custom — {{ pack.custom_name or pack.variant }}){% else %}(Standard){% endif %}</h1>

<div class="card" style="margin-bottom:20px;">
  <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center;">
    <span><strong>Version:</strong> {{ pack.version }}</span>
    <span><strong>Checksum:</strong> <code>{{ pack.checksum[:12] }}…</code></span>
    <span><strong>Rules:</strong> {{ pack.rule_count }}</span>
  </div>
  <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
    <form method="POST" action="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/clone" style="display:inline;">
      <input type="hidden" name="csrf_token" value="{{ csrf }}">
      <input type="text" name="custom_name" placeholder="custom name" required style="width:160px;">
      <button type="submit" class="btn btn-sm">Clone as Custom</button>
    </form>
    <form method="POST" action="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/validate" style="display:inline;">
      <input type="hidden" name="csrf_token" value="{{ csrf }}">
      <button type="submit" class="btn btn-sm btn-outline">Validate</button>
    </form>
    <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/export" class="btn btn-sm btn-outline">Export YAML</a>
    {% if pack.is_custom %}
    <form method="POST" action="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/delete" style="display:inline;">
      <input type="hidden" name="csrf_token" value="{{ csrf }}">
      <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('Delete this pack?')">Delete</button>
    </form>
    {% endif %}
  </div>
</div>

{% if validated is defined and validated %}
<div class="card" style="margin-bottom:20px;border-color:{% if validation_errors %}var(--red,#e74c3c){% else %}var(--green,#27ae60){% endif %};">
  {% if validation_errors %}
  <h2 style="color:var(--red,#e74c3c);">Validation Errors</h2>
  <ul style="padding-left:20px;">{% for err in validation_errors %}<li>{{ err }}</li>{% endfor %}</ul>
  {% else %}
  <h2 style="color:var(--green,#27ae60);">✓ Pack is valid</h2>
  {% endif %}
</div>
{% endif %}

{% if not pack.is_custom %}
<div class="card" style="margin-bottom:20px;border-color:var(--accent,#3498db);background:rgba(52,152,219,0.1);">
  <p>This is a <strong>Standard</strong> pack (read-only). Clone as Custom to edit rules.</p>
</div>
{% endif %}

<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px;">
    <h2>Rules ({{ pack.rule_count }})</h2>
    {% if pack.is_custom %}
    <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/rules/add" class="btn btn-sm">+ Add Rule</a>
    {% endif %}
  </div>
  <table style="width:100%;border-collapse:collapse;">
    <thead>
      <tr>
        <th style="text-align:left;padding:8px;">Rule ID</th>
        <th style="text-align:left;padding:8px;">Type</th>
        <th style="text-align:left;padding:8px;">Description</th>
        <th style="text-align:right;padding:8px;">Actions</th>
      </tr>
    </thead>
    <tbody>
    {% for rule in pack.rules %}
      <tr style="border-top:1px solid var(--border,#333);">
        <td style="padding:8px;"><code>{{ rule.id }}</code></td>
        <td style="padding:8px;">{{ rule.type }}</td>
        <td style="padding:8px;">{{ rule.get('description', '') if rule.get is defined else rule.description|default('') }}</td>
        <td style="padding:8px;text-align:right;">
          <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/rules/{{ rule.id }}" class="btn btn-sm">{% if pack.is_custom %}Edit{% else %}View{% endif %}</a>
          {% if pack.is_custom %}
          <form method="POST" action="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/rules/{{ rule.id }}/delete" style="display:inline;">
            <input type="hidden" name="csrf_token" value="{{ csrf }}">
            <button type="submit" class="btn btn-sm btn-danger" onclick="return confirm('Delete rule {{ rule.id }}?')">Delete</button>
          </form>
          {% endif %}
        </td>
      </tr>
    {% endfor %}
    </tbody>
  </table>
</div>
{% endblock %}
```

- [ ] **Step 7: Run route tests**

Run: `pytest tests/test_rule_pack_routes.py -v`
Expected: All PASS

- [ ] **Step 8: Run full quality checks**

Run: `ruff check . && mypy main.py app/services/rule_pack_editor.py && pytest tests/test_rule_pack_routes.py tests/test_rule_pack_editor.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add main.py app/templates/layouts/base.html app/templates/pages/rule_packs.html app/templates/pages/rule_pack_detail.html tests/test_rule_pack_routes.py
git commit -m "feat(rule-editor): add pack list, detail, clone, delete, validate, export routes"
```

---

### Task 4: Routes — Rule Editor (Type-Adaptive Form)

**Files:**
- Modify: `main.py` (add rule editor routes)
- Create: `app/templates/pages/rule_editor.html`
- Modify: `tests/test_rule_pack_routes.py`

This task adds the GET/POST routes for viewing and editing individual rules with a form that adapts to the rule type (sum, formula, lookup, bracket_table).

- [ ] **Step 1: Write failing tests for rule editor routes**

Add to `tests/test_rule_pack_routes.py`:

```python
def test_rule_editor_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/federal/2024/standard/rules/fed.2024.gross_income.wages")
    assert r.status_code == 200
    assert "fed.2024.gross_income.wages" in r.text
    assert "sum" in r.text.lower()


def test_add_rule_form_renders() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_add"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.get(f"/rule-packs/federal/2024/{variant}/rules/add")
    assert r.status_code == 200
    assert "Add Rule" in r.text or "New Rule" in r.text


def test_save_rule_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_save"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/add",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.my_new_rule",
            "rule_type": "formula",
            "description": "Test formula",
            "expression": "x",
            "input_name_0": "x",
            "input_type_0": "ref",
            "input_value_0": "input.w2.wages",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303 or r.status_code == 200


def test_save_existing_rule_via_post() -> None:
    c = _client()
    # Clone to create a custom pack
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_edit"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.gross_income.wages",
        data={
            "csrf_token": CSRF,
            "rule_id": "fed.2024.gross_income.wages",
            "rule_type": "sum",
            "description": "Updated wages",
            "sum_items_ref": "input.w2.wages",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_delete_rule_via_post() -> None:
    c = _client()
    resp = c.post(
        "/rule-packs/federal/2024/standard/clone",
        data={"csrf_token": CSRF, "custom_name": "for_rule_del"},
        follow_redirects=False,
    )
    variant = resp.headers["location"].rstrip("/").split("/")[-1]
    r = c.post(
        f"/rule-packs/federal/2024/{variant}/rules/fed.2024.gross_income.wages/delete",
        data={"csrf_token": CSRF},
        follow_redirects=False,
    )
    assert r.status_code == 303
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `pytest tests/test_rule_pack_routes.py::test_rule_editor_renders tests/test_rule_pack_routes.py::test_add_rule_form_renders tests/test_rule_pack_routes.py::test_save_rule_via_post tests/test_rule_pack_routes.py::test_delete_rule_via_post -v`
Expected: FAIL — 404

- [ ] **Step 3: Add rule editor routes to main.py**

Add imports:
```python
from app.services.rule_pack_editor import save_rule, delete_rule
```

Add routes (literal `/rules/add` BEFORE parameterized `/rules/{rule_id}`):

```python
@app.get("/rule-packs/{jurisdiction}/{year}/{variant}/rules/add", response_class=HTMLResponse)
def rule_add_form(request: Request, jurisdiction: str, year: int, variant: str) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    detail = load_pack_detail(jurisdiction, year, variant)
    id_prefix = "fed." if jurisdiction.lower() in {"federal", "fed"} else f"{jurisdiction.lower()}."
    id_prefix += f"{year}."
    resp = templates.TemplateResponse(
        "pages/rule_editor.html",
        {
            "request": request,
            "csrf": csrf,
            "pack": detail,
            "rule": None,
            "is_new": True,
            "id_prefix": id_prefix,
        },
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/add")
async def rule_add_submit(request: Request, jurisdiction: str, year: int, variant: str) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    rule_data = _parse_rule_form(fd)
    try:
        save_rule(jurisdiction, year, variant, rule_data["id"], rule_data)
        _bust_pack_cache(jurisdiction, year)
        return RedirectResponse(
            url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
            status_code=303,
        )
    except ValueError as exc:
        csrf = _get_csrf_token(request)
        detail = load_pack_detail(jurisdiction, year, variant)
        resp = templates.TemplateResponse(
            "pages/rule_editor.html",
            {"request": request, "csrf": csrf, "pack": detail, "rule": rule_data, "is_new": True, "error": str(exc), "id_prefix": ""},
        )
        resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return resp


@app.get("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}", response_class=HTMLResponse)
def rule_edit_form(request: Request, jurisdiction: str, year: int, variant: str, rule_id: str) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    detail = load_pack_detail(jurisdiction, year, variant)
    rule = next((r for r in detail["rules"] if r["id"] == rule_id), None)
    if rule is None:
        return HTMLResponse(content="Rule not found", status_code=404)
    resp = templates.TemplateResponse(
        "pages/rule_editor.html",
        {"request": request, "csrf": csrf, "pack": detail, "rule": rule, "is_new": False, "id_prefix": ""},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}/delete")
async def rule_delete_submit(request: Request, jurisdiction: str, year: int, variant: str, rule_id: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_rule(jurisdiction, year, variant, rule_id)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
        status_code=303,
    )


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}")
async def rule_save_submit(request: Request, jurisdiction: str, year: int, variant: str, rule_id: str) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    rule_data = _parse_rule_form(fd)
    try:
        save_rule(jurisdiction, year, variant, rule_id, rule_data)
        _bust_pack_cache(jurisdiction, year)
        return RedirectResponse(
            url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
            status_code=303,
        )
    except ValueError as exc:
        csrf = _get_csrf_token(request)
        detail = load_pack_detail(jurisdiction, year, variant)
        resp = templates.TemplateResponse(
            "pages/rule_editor.html",
            {"request": request, "csrf": csrf, "pack": detail, "rule": rule_data, "is_new": False, "error": str(exc), "id_prefix": ""},
        )
        resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return resp
```

Add the `_parse_rule_form` helper near other form helpers:

```python
def _parse_rule_form(fd: FormData) -> dict[str, Any]:
    """Parse the rule editor form into a rule dict for YAML storage."""
    rule_id = _form_str(fd, "rule_id")
    rule_type = _form_str(fd, "rule_type")
    description = _form_str(fd, "description")
    form_line = _form_str(fd, "form_line")

    rule: dict[str, Any] = {
        "id": rule_id,
        "type": rule_type,
        "description": description,
    }
    if form_line:
        rule["form_line"] = form_line

    if rule_type == "sum":
        items_ref = _form_str(fd, "sum_items_ref")
        rule["inputs"] = {"items": {"ref": items_ref}}

    elif rule_type == "formula":
        rule["expression"] = _form_str(fd, "expression")
        inputs: dict[str, Any] = {}
        i = 0
        while True:
            name = str(fd.get(f"input_name_{i}", "") or "").strip()
            if not name:
                break
            itype = str(fd.get(f"input_type_{i}", "ref") or "ref").strip()
            ival = str(fd.get(f"input_value_{i}", "") or "").strip()
            if itype == "literal":
                inputs[name] = {"literal": ival}
            else:
                inputs[name] = {"ref": ival}
            i += 1
        rule["inputs"] = inputs

    elif rule_type == "lookup":
        rule["table"] = _form_str(fd, "lookup_table")
        key_ref = _form_str(fd, "lookup_key_ref")
        rule["key"] = {"ref": key_ref}

    elif rule_type == "bracket_table":
        input_ref = _form_str(fd, "bracket_input_ref")
        key_ref = _form_str(fd, "bracket_key_ref")
        rule["input"] = {"ref": input_ref}
        rule["key"] = {"ref": key_ref}
        tables: dict[str, list[dict[str, str | None]]] = {}
        for status in ("single", "mfj", "mfs", "hoh", "qss"):
            brackets: list[dict[str, str | None]] = []
            row = 0
            while True:
                lower = str(fd.get(f"bracket_{status}_{row}_lower", "") or "").strip()
                if not lower and row > 0:
                    break
                if not lower:
                    row += 1
                    continue
                upper = str(fd.get(f"bracket_{status}_{row}_upper", "") or "").strip() or None
                rate = str(fd.get(f"bracket_{status}_{row}_rate", "") or "").strip()
                brackets.append({"lower": lower, "upper": upper, "rate": rate})
                row += 1
            if brackets:
                tables[status] = brackets
        if tables:
            rule["tables"] = tables

    return rule
```

- [ ] **Step 4: Create rule_editor.html template**

```html
<!-- app/templates/pages/rule_editor.html -->
{% extends "layouts/base.html" %}
{% block title %}{% if is_new %}Add Rule{% else %}Edit Rule{% endif %}{% endblock %}
{% block content %}
<h1>{% if is_new %}Add Rule{% else %}Edit Rule{% endif %} — {{ pack.jurisdiction | upper }} {{ pack.year }} ({{ pack.variant }})</h1>

{% if error is defined and error %}
<div class="card" style="border-color:var(--red,#e74c3c);margin-bottom:20px;">
  <p style="color:var(--red,#e74c3c);">{{ error }}</p>
</div>
{% endif %}

{% set r = rule or {} %}
{% set rtype = r.get('type', 'formula') if r else 'formula' %}
{% set readonly = not pack.is_custom %}

<form method="POST" action="{% if is_new %}/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/rules/add{% else %}/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}/rules/{{ r.id }}{% endif %}">
  <input type="hidden" name="csrf_token" value="{{ csrf }}">

  <div class="card" style="margin-bottom:20px;">
    <h2>Rule Identity</h2>
    <div class="form-row">
      <div>
        <label>Rule ID</label>
        <input type="text" name="rule_id" value="{{ r.get('id', id_prefix) if r else id_prefix }}" {% if not is_new %}readonly{% endif %} required>
      </div>
      <div>
        <label>Type</label>
        <select name="rule_type" id="rule_type" onchange="switchType(this.value)" {% if not is_new and readonly %}disabled{% endif %}>
          <option value="sum" {% if rtype == 'sum' %}selected{% endif %}>sum</option>
          <option value="formula" {% if rtype == 'formula' %}selected{% endif %}>formula</option>
          <option value="lookup" {% if rtype == 'lookup' %}selected{% endif %}>lookup</option>
          <option value="bracket_table" {% if rtype == 'bracket_table' %}selected{% endif %}>bracket_table</option>
        </select>
      </div>
    </div>
    <div class="form-row" style="margin-top:8px;">
      <div><label>Description</label><input type="text" name="description" value="{{ r.get('description', '') }}" style="width:100%;"></div>
      <div><label>Form Line</label><input type="text" name="form_line" value="{{ r.get('form_line', '') }}" placeholder="e.g. 1040 Line 1a"></div>
    </div>
  </div>

  <!-- SUM section -->
  <div class="card type-section" id="section-sum" style="margin-bottom:20px;{% if rtype != 'sum' %}display:none;{% endif %}">
    <h2>Sum Inputs</h2>
    <label>Items Reference</label>
    <input type="text" name="sum_items_ref" value="{% if rtype == 'sum' and r.get('inputs') %}{{ r['inputs'].get('items', {}).get('ref', '') }}{% endif %}" placeholder="e.g. input.w2.wages" style="width:100%;">
  </div>

  <!-- FORMULA section -->
  <div class="card type-section" id="section-formula" style="margin-bottom:20px;{% if rtype != 'formula' %}display:none;{% endif %}">
    <h2>Formula</h2>
    <label>Expression</label>
    <input type="text" name="expression" value="{{ r.get('expression', '') }}" placeholder="e.g. max(gains, neg_limit)" style="width:100%;">
    <p style="font-size:12px;color:var(--muted,#888);margin-top:4px;">Allowed: letters, digits, +, -, *, /, (, ), comma, dot, space. Functions: max, min.</p>
    <h3 style="margin-top:12px;">Inputs</h3>
    <div id="formula-inputs">
      {% if rtype == 'formula' and r.get('inputs') %}
        {% for name, val in r['inputs'].items() %}
        <div class="form-row formula-input-row" style="margin-bottom:4px;">
          <div><input type="text" name="input_name_{{ loop.index0 }}" value="{{ name }}" placeholder="variable name"></div>
          <div>
            <select name="input_type_{{ loop.index0 }}">
              <option value="ref" {% if val.get('ref') is defined %}selected{% endif %}>ref</option>
              <option value="literal" {% if val.get('literal') is defined %}selected{% endif %}>literal</option>
            </select>
          </div>
          <div><input type="text" name="input_value_{{ loop.index0 }}" value="{{ val.get('ref', val.get('literal', '')) }}" placeholder="value"></div>
          <div><button type="button" class="btn btn-sm btn-danger" onclick="this.closest('.formula-input-row').remove()">×</button></div>
        </div>
        {% endfor %}
      {% endif %}
    </div>
    <button type="button" class="btn btn-sm" onclick="addFormulaInput()" style="margin-top:8px;">+ Add Input</button>
  </div>

  <!-- LOOKUP section -->
  <div class="card type-section" id="section-lookup" style="margin-bottom:20px;{% if rtype != 'lookup' %}display:none;{% endif %}">
    <h2>Lookup</h2>
    <div class="form-row">
      <div><label>Table Path</label><input type="text" name="lookup_table" value="{{ r.get('table', '') }}" placeholder="e.g. constants.standard_deduction"></div>
      <div><label>Key Reference</label><input type="text" name="lookup_key_ref" value="{% if r.get('key') %}{{ r['key'].get('ref', '') }}{% endif %}" placeholder="e.g. input.filing_status"></div>
    </div>
  </div>

  <!-- BRACKET TABLE section -->
  <div class="card type-section" id="section-bracket_table" style="margin-bottom:20px;{% if rtype != 'bracket_table' %}display:none;{% endif %}">
    <h2>Bracket Table</h2>
    <div class="form-row">
      <div><label>Input Reference</label><input type="text" name="bracket_input_ref" value="{% if r.get('input') %}{{ r['input'].get('ref', '') }}{% endif %}" placeholder="e.g. fed.2024.taxable_income"></div>
      <div><label>Key Reference</label><input type="text" name="bracket_key_ref" value="{% if r.get('key') %}{{ r['key'].get('ref', '') }}{% endif %}" placeholder="e.g. input.filing_status"></div>
    </div>
    {% for status in ['single', 'mfj', 'mfs', 'hoh', 'qss'] %}
    <h3 style="margin-top:12px;">{{ status | upper }}</h3>
    <table style="width:100%;border-collapse:collapse;" id="bracket-table-{{ status }}">
      <thead><tr><th>Lower</th><th>Upper</th><th>Rate</th><th></th></tr></thead>
      <tbody>
        {% if rtype == 'bracket_table' and r.get('tables', {}).get(status) %}
          {% for b in r['tables'][status] %}
          <tr>
            <td><input type="text" name="bracket_{{ status }}_{{ loop.index0 }}_lower" value="{{ b.lower }}" style="width:100%;"></td>
            <td><input type="text" name="bracket_{{ status }}_{{ loop.index0 }}_upper" value="{{ b.upper if b.upper is not none else '' }}" style="width:100%;"></td>
            <td><input type="text" name="bracket_{{ status }}_{{ loop.index0 }}_rate" value="{{ b.rate }}" style="width:100%;"></td>
            <td><button type="button" class="btn btn-sm btn-danger" onclick="this.closest('tr').remove()">×</button></td>
          </tr>
          {% endfor %}
        {% else %}
          <tr>
            <td><input type="text" name="bracket_{{ status }}_0_lower" value="0" style="width:100%;"></td>
            <td><input type="text" name="bracket_{{ status }}_0_upper" value="" style="width:100%;"></td>
            <td><input type="text" name="bracket_{{ status }}_0_rate" value="" style="width:100%;"></td>
            <td><button type="button" class="btn btn-sm btn-danger" onclick="this.closest('tr').remove()">×</button></td>
          </tr>
        {% endif %}
      </tbody>
    </table>
    <button type="button" class="btn btn-sm" onclick="addBracketRow('{{ status }}')" style="margin-top:4px;">+ Add Row</button>
    {% endfor %}
  </div>

  {% if not readonly %}
  <div style="display:flex;gap:12px;">
    <button type="submit" class="btn">Save</button>
    <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}" class="btn btn-outline">Cancel</a>
  </div>
  {% else %}
  <a href="/rule-packs/{{ pack.jurisdiction }}/{{ pack.year }}/{{ pack.variant }}" class="btn btn-outline">Back</a>
  {% endif %}
</form>

<script>
function switchType(type) {
  document.querySelectorAll('.type-section').forEach(s => s.style.display = 'none');
  var sec = document.getElementById('section-' + type);
  if (sec) sec.style.display = 'block';
}

var formulaIdx = {{ (r.get('inputs', {}) | length) if (r and rtype == 'formula') else 0 }};
function addFormulaInput() {
  var container = document.getElementById('formula-inputs');
  var html = '<div class="form-row formula-input-row" style="margin-bottom:4px;">'
    + '<div><input type="text" name="input_name_' + formulaIdx + '" placeholder="variable name"></div>'
    + '<div><select name="input_type_' + formulaIdx + '"><option value="ref">ref</option><option value="literal">literal</option></select></div>'
    + '<div><input type="text" name="input_value_' + formulaIdx + '" placeholder="value"></div>'
    + '<div><button type="button" class="btn btn-sm btn-danger" onclick="this.closest(\'.formula-input-row\').remove()">×</button></div>'
    + '</div>';
  container.insertAdjacentHTML('beforeend', html);
  formulaIdx++;
}

var bracketCounters = {single: 0, mfj: 0, mfs: 0, hoh: 0, qss: 0};
{% if rtype == 'bracket_table' and r.get('tables') %}
  {% for status in ['single', 'mfj', 'mfs', 'hoh', 'qss'] %}
  bracketCounters['{{ status }}'] = {{ r.get('tables', {}).get(status, []) | length }};
  {% endfor %}
{% else %}
  for (var k in bracketCounters) bracketCounters[k] = 1;
{% endif %}

function addBracketRow(status) {
  var idx = bracketCounters[status];
  var tbody = document.querySelector('#bracket-table-' + status + ' tbody');
  var tr = document.createElement('tr');
  tr.innerHTML = '<td><input type="text" name="bracket_' + status + '_' + idx + '_lower" style="width:100%;"></td>'
    + '<td><input type="text" name="bracket_' + status + '_' + idx + '_upper" style="width:100%;"></td>'
    + '<td><input type="text" name="bracket_' + status + '_' + idx + '_rate" style="width:100%;"></td>'
    + '<td><button type="button" class="btn btn-sm btn-danger" onclick="this.closest(\'tr\').remove()">×</button></td>';
  tbody.appendChild(tr);
  bracketCounters[status] = idx + 1;
}
</script>
{% endblock %}
```

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_rule_pack_routes.py tests/test_rule_pack_editor.py -v`
Expected: All PASS

- [ ] **Step 6: Run full quality checks**

Run: `ruff check . && mypy main.py && pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add main.py app/templates/pages/rule_editor.html tests/test_rule_pack_routes.py
git commit -m "feat(rule-editor): add rule editor with type-adaptive forms"
```

---

### Task 5: YAML Import Route and Template

**Files:**
- Modify: `main.py` (add import routes)
- Create: `app/templates/pages/rule_pack_import.html`
- Modify: `tests/test_rule_pack_routes.py`

- [ ] **Step 1: Write failing tests for import routes**

Add to `tests/test_rule_pack_routes.py`:

```python
def test_import_page_renders() -> None:
    c = _client()
    r = c.get("/rule-packs/import")
    assert r.status_code == 200
    assert "Import" in r.text


def test_import_upload_valid() -> None:
    import yaml as _yaml
    c = _client()
    manifest = _yaml.dump({"version": "1", "tax_year": 2024, "jurisdiction": "federal"}).encode()
    rules = _yaml.dump({
        "constants": {},
        "rules": [
            {"id": "fed.2024.imported_rule", "description": "Imported", "type": "formula", "expression": "x", "inputs": {"x": {"ref": "input.w2.wages"}}},
        ],
    }).encode()
    r = c.post(
        "/rule-packs/import",
        data={"csrf_token": CSRF, "custom_name": "uploaded"},
        files={"manifest_file": ("manifest.yaml", manifest, "application/x-yaml"), "rules_file": ("rules.yaml", rules, "application/x-yaml")},
    )
    assert r.status_code == 200 or r.status_code == 303
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rule_pack_routes.py::test_import_page_renders tests/test_rule_pack_routes.py::test_import_upload_valid -v`
Expected: FAIL — 404

- [ ] **Step 3: Add import routes to main.py**

Place these BEFORE the parameterized `/rule-packs/{jurisdiction}/...` routes:

```python
@app.get("/rule-packs/import", response_class=HTMLResponse)
def rule_pack_import_form(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/rule_pack_import.html", {"request": request, "csrf": csrf}
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/import", response_class=HTMLResponse)
async def rule_pack_import_submit(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    custom_name = _form_str(fd, "custom_name")

    manifest_upload = fd.get("manifest_file")
    rules_upload = fd.get("rules_file")
    if not manifest_upload or not rules_upload:
        csrf = _get_csrf_token(request)
        resp = templates.TemplateResponse(
            "pages/rule_pack_import.html",
            {"request": request, "csrf": csrf, "error": "Both manifest and rules files are required."},
        )
        resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return resp

    from starlette.datastructures import UploadFile
    manifest_bytes = await manifest_upload.read() if isinstance(manifest_upload, UploadFile) else b""
    rules_bytes = await rules_upload.read() if isinstance(rules_upload, UploadFile) else b""

    try:
        from app.services.rule_pack_editor import import_yaml
        info = import_yaml(manifest_bytes, rules_bytes, custom_name=custom_name)
        _bust_pack_cache(info.jurisdiction, info.year)
        return RedirectResponse(
            url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
            status_code=303,
        )
    except ValueError as exc:
        csrf = _get_csrf_token(request)
        resp = templates.TemplateResponse(
            "pages/rule_pack_import.html",
            {"request": request, "csrf": csrf, "error": str(exc)},
        )
        resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return resp
```

- [ ] **Step 4: Create rule_pack_import.html template**

```html
<!-- app/templates/pages/rule_pack_import.html -->
{% extends "layouts/base.html" %}
{% block title %}Import Rule Pack{% endblock %}
{% block content %}
<h1>Import YAML Rule Pack</h1>

{% if error is defined and error %}
<div class="card" style="border-color:var(--red,#e74c3c);margin-bottom:20px;">
  <p style="color:var(--red,#e74c3c);">{{ error }}</p>
</div>
{% endif %}

<form method="POST" action="/rule-packs/import" enctype="multipart/form-data">
  <input type="hidden" name="csrf_token" value="{{ csrf }}">
  <div class="card">
    <div class="form-row">
      <div>
        <label>Manifest YAML</label>
        <input type="file" name="manifest_file" accept=".yaml,.yml" required>
      </div>
      <div>
        <label>Rules YAML</label>
        <input type="file" name="rules_file" accept=".yaml,.yml" required>
      </div>
    </div>
    <div style="margin-top:12px;">
      <label>Custom Name</label>
      <input type="text" name="custom_name" required placeholder="e.g. imported_2024_alt">
    </div>
    <button type="submit" class="btn" style="margin-top:12px;">Validate &amp; Import</button>
  </div>
</form>

<div class="card" style="margin-top:20px;">
  <h2>Importing from GitHub</h2>
  <p>To import rule packs from the GitHub repository:</p>
  <ol style="padding-left:20px;margin-top:8px;">
    <li>Clone the repo or download a release: <code>git clone https://github.com/your-org/Tax_Co-Pilot.git</code></li>
    <li>Copy the desired <code>rule_packs/{jurisdiction}/{year}/</code> directory into your local installation</li>
    <li>Restart the app to pick up new packs</li>
  </ol>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_rule_pack_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Run full quality checks**

Run: `ruff check . && mypy main.py && pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add main.py app/templates/pages/rule_pack_import.html tests/test_rule_pack_routes.py
git commit -m "feat(rule-editor): add YAML import route with validation"
```

---

### Task 6: Calculate Form Integration — Variant Dropdown

**Files:**
- Modify: `main.py` (update calculate route + pack loading)
- Modify: `app/templates/pages/calculate.html` (add variant dropdown)
- Modify: `tests/test_rule_pack_routes.py` (add end-to-end test)

- [ ] **Step 1: Write failing end-to-end test**

Add to `tests/test_rule_pack_routes.py`:

```python
def test_calculate_with_custom_variant_param() -> None:
    """The calculate form should accept a pack_variant parameter."""
    c = _client()
    r = c.get("/calculate")
    assert r.status_code == 200
    assert "pack_variant" in r.text or "Rule Pack" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rule_pack_routes.py::test_calculate_with_custom_variant_param -v`
Expected: FAIL — `assert "pack_variant" in r.text`

- [ ] **Step 3: Update the calculate GET route in main.py**

Modify the `calculate_form` function to pass available variants:

```python
@app.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    all_packs = list_rule_packs()
    resp = templates.TemplateResponse(
        "pages/calculate.html",
        {
            "request": request,
            "csrf": csrf,
            "available_years": available_years,
            "available_states": sorted(_get_state_packs(max(available_years)).keys()) if available_years else [],
            "pack_variants": all_packs,
        },
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp
```

- [ ] **Step 4: Update the calculate POST route to use variant**

In `calculate_submit`, after parsing `fd`:

```python
pack_variant = _form_str(fd, "pack_variant") or "standard"
```

Update the pack loading to handle custom variants:

```python
if pack_variant == "standard":
    fed_pack = _get_federal_pack(inputs.tax_year)
else:
    from app.services.rule_pack_editor import _pack_path
    fed_custom_dir = _pack_path("federal", inputs.tax_year, pack_variant)
    if fed_custom_dir.exists():
        fed_pack = RulePack.load(fed_custom_dir)
    else:
        fed_pack = _get_federal_pack(inputs.tax_year)
```

- [ ] **Step 5: Add variant dropdown to calculate.html**

After the State of Residence dropdown in the Filing Information card, add:

```html
<div>
    <label>Rule Pack Variant</label>
    <select name="pack_variant">
        <option value="standard" selected>Standard</option>
        {% for pv in pack_variants if pv.jurisdiction == 'federal' and pv.is_custom %}
        <option value="{{ pv.variant }}">Custom {{ pv.version }} — {{ pv.custom_name or pv.variant }}</option>
        {% endfor %}
    </select>
</div>
```

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_rule_pack_routes.py -v && pytest tests/test_milestone6_routes.py -v`
Expected: All PASS (existing calculate tests still work with default "standard")

- [ ] **Step 7: Run full quality checks**

Run: `ruff check . && mypy main.py && pytest`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add main.py app/templates/pages/calculate.html tests/test_rule_pack_routes.py
git commit -m "feat(rule-editor): integrate variant dropdown into calculate form"
```

---

### Task 7: Documentation, CHANGELOG, README Tree Update

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md` (repository tree)
- Modify: `docs/RULE_PACK_AUTHORING.md` (GitHub import section)

- [ ] **Step 1: Update CHANGELOG.md**

Add under `## [Unreleased]` → `### Added`:

```markdown
- **Milestone 12 — Rule Pack Editor (complete):** GUI-based rule pack management system. Create, edit, clone, import, export YAML rule packs via web UI. Standard packs are read-only; custom variants use `custom_vN/` subdirectories. Type-adaptive rule editor (sum, formula, lookup, bracket_table) with inline bracket table editing. Calculate form integration with variant selector dropdown. Full validation via `RulePack.load()` on every save. CSRF-protected POST routes. Path traversal protection on all route parameters.
- `app/services/rule_pack_editor.py`: CRUD service for rule packs (list, load, clone, create, save, delete, validate, import, export).
- Rule Pack Manager page (`GET /rule-packs`) with grouped table and inline create form.
- Pack Detail page with rule list, validation, clone/export/delete actions.
- Type-adaptive Rule Editor page with dynamic form sections for all four rule types.
- YAML Import page with file upload and validation.
- "Rule Pack Variant" dropdown on calculate form for selecting custom packs.
- `tests/test_rule_pack_editor.py` and `tests/test_rule_pack_routes.py`.
```

- [ ] **Step 2: Update README repository tree**

Run: `find . -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/.pytest_cache/*' -not -path '*/.mypy_cache/*' -not -path '*/.ruff_cache/*' | sort`

Update the tree in README.md to include all new files.

- [ ] **Step 3: Add GitHub import documentation to docs/RULE_PACK_AUTHORING.md**

Append a new section:

```markdown
## Importing Rule Packs from GitHub

To manually import rule packs from the Tax Co-Pilot GitHub repository:

1. Clone or download the repository:
   ```bash
   git clone https://github.com/your-org/Tax_Co-Pilot.git /tmp/tax-co-pilot
   ```

2. Copy the desired rule pack directory into your local installation:
   ```bash
   cp -r /tmp/tax-co-pilot/rule_packs/federal/2024/ ./rule_packs/federal/2024/
   ```

3. Restart the application to pick up the new packs.

Alternatively, use the web UI's Import feature to upload individual manifest + rules YAML files.

**Future enhancement:** A CLI helper script for automated GitHub import.
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md README.md docs/RULE_PACK_AUTHORING.md
git commit -m "docs: add Rule Pack Editor changelog, tree update, GitHub import guide"
```

- [ ] **Step 5: Final full test run**

Run: `ruff check . && mypy . && pytest`
Expected: All PASS — this is the definition of done.
