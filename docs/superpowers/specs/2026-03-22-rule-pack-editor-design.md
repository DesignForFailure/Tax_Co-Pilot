<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Rule Pack Editor — Design Spec

## Goal

Add a GUI-based rule pack management system that allows users to create, edit, clone, import, and export YAML rule packs without needing to manually edit files or push to the repository. Standard (shipped) packs are read-only; users create Custom variants for modifications.

## Scope

**In scope:**
- Pack-level management: list, clone, create, delete, import, export
- Rule-level editing: add, edit, delete individual rules via type-adaptive forms
- Bracket table editing via editable HTML table
- Standard vs Custom pack classification with enforced naming conventions
- Custom pack version auto-incrementing
- Calculate form integration (variant selector dropdown)
- Local YAML file import via GUI
- GitHub import documentation (manual clone/copy instructions)
- Full validation on every save via existing `RulePack.load()`

**Out of scope:**
- GitHub CLI fetch tool (future enhancement)
- ZIP/JSON import formats
- Rule pack layering/merge logic
- EITC, AMT, Schedule C tax features

## Data Model

### Pack Classification

Packs are classified as **Standard** or **Custom** based on directory location. Custom packs live in `custom_vN/` subdirectories beneath the standard pack directory. The `custom` and `custom_name` fields appear in the manifest YAML but are **editor metadata only** — they are not fields on the `RulePack` dataclass and are not used by the engine. The editor service reads/writes them directly from the manifest dict.

```yaml
# Standard pack manifest (shipped with repo, in pack root dir)
jurisdiction: federal
tax_year: 2024
version: "1.0.0"

# Custom pack manifest (user-created, in custom_v1/ subdir)
jurisdiction: federal
tax_year: 2024
version: "1"
custom: true
custom_name: "high_deduction_scenario"
```

The editor service detects custom packs by checking if the pack directory name matches `custom_v*`. The `custom` and `custom_name` manifest fields are informational labels; the directory structure is authoritative.

### Directory & File Layout

Custom packs live in **subdirectories** beneath the standard pack directory. This avoids breaking the existing `_resolve_pack_file()` glob (which expects exactly one `*_manifest.yaml` / `*_rules.yaml` in each directory).

- Standard federal: `rule_packs/federal/2024/federal_2024_manifest.yaml` + `federal_2024_rules.yaml`
- Custom federal v1: `rule_packs/federal/2024/custom_v1/manifest.yaml` + `rules.yaml`
- Custom federal v2: `rule_packs/federal/2024/custom_v2/manifest.yaml` + `rules.yaml`
- Standard state: `rule_packs/state/CA/2024/state_CA_2024_manifest.yaml` + `state_CA_2024_rules.yaml`
- Custom state v1: `rule_packs/state/CA/2024/custom_v1/manifest.yaml` + `rules.yaml`

Custom subdirectories use canonical names (`manifest.yaml`, `rules.yaml`) since `_resolve_pack_file()` checks for the canonical name first. The `custom_vN/` directory name encodes the version. The `_resolve_pack_file()` function and `RulePack.load()` work unmodified on these subdirectories.

### Versioning

When a user creates a new custom variant for the same jurisdiction/year, the version auto-increments (v1, v2, v3). Previous versions are preserved on disk. The system scans existing files to determine the next available version number.

### Pack Selection at Calculate Time

The calculate form gets a new "Rule Pack Variant" dropdown that appears after year and jurisdiction are selected. It shows "Standard" plus any custom variants (e.g., "Custom v1 — high_deduction_scenario"). Default is always Standard.

## GUI Pages

### 1. Rule Pack Manager (`GET /rule-packs`)

- Accessed from a "Rule Packs" link in the main navigation
- Table of all packs grouped by jurisdiction (Federal first, then states alphabetically)
- Columns: Jurisdiction, Year, Type (Standard/Custom), Version, Rule Count, Actions
- Actions per pack: "View/Edit", "Clone as Custom", "Export YAML", "Delete" (custom only)
- Standard packs show a lock icon; "Edit" opens in read-only mode with a "Clone as Custom" prompt
- Top-level buttons: "Create Custom Pack", "Import YAML"
- "Create Custom Pack" opens an inline form (JS toggle): jurisdiction dropdown, year input, custom name text field

### 2. Pack Detail / Rule List (`GET /rule-packs/{jurisdiction}/{year}/{variant}`)

- Header card with pack metadata (jurisdiction, year, version, type, checksum, rule count) and action buttons (Clone, Validate, Export, Delete)
- Validation results area (hidden by default, populated after "Validate" click)
- Rules table listing all rules in topological order
- Columns: Rule ID, Type (sum/formula/lookup/bracket_table), Expression/Description preview, Actions
- Actions per rule: "Edit", "Delete" (custom packs only)
- "Add Rule" button: opens inline form with rule ID (pre-filled with namespace prefix like `fed.2024.`), type dropdown, then redirects to the full rule editor
- For standard packs, all mutation controls are disabled with a "Clone as Custom to edit" banner

### 3. Rule Editor (`GET /rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}`)

Form adapts based on rule type:

- **All types share:** Rule ID field (read-only for existing, editable for new), description text field, optional `form_line` annotation
- **sum:** List of text inputs for rule references, with add/remove buttons (JS dynamic rows)
- **formula:** Single text input for the expression, with help tooltip showing allowed syntax
- **lookup:** Key-value pairs — filing status dropdown + value input, with add/remove rows
- **bracket_table:** Editable HTML table. Column headers are filing statuses (single, mfj, mfs, hoh, qss). Each row: lower bound, upper bound, rate. Add/remove row buttons. JS handles inserting/removing `<tr>` elements

"Save" validates the rule and returns errors inline. "Cancel" returns to pack detail.

### 4. YAML Import (`GET /rule-packs/import`)

- File upload inputs: one for manifest YAML, one for rules YAML
- Radio selector: "Standard" or "Custom"
- If Custom: custom name text field
- "Validate & Import" button uploads, validates via `RulePack.load()`, shows errors or success

## Backend Architecture

### New Service: `app/services/rule_pack_editor.py`

All read/write operations for rule packs. Keeps `rule_loader.py` purely for loading/validation.

Functions:
- `list_all_packs()` — scan `rule_packs/` directories, return metadata for each pack
- `load_pack_detail(jurisdiction, year, variant)` — load a specific pack and return rules as structured dicts
- `save_rule(jurisdiction, year, variant, rule_id, rule_data)` — update or add a single rule in a custom pack
- `delete_rule(jurisdiction, year, variant, rule_id)` — remove a rule from a custom pack
- `clone_pack(jurisdiction, year, source_variant, custom_name)` — copy a pack to a new custom variant with auto-incremented version
- `create_empty_pack(jurisdiction, year, custom_name)` — create new custom pack with manifest and empty rules
- `delete_pack(jurisdiction, year, variant)` — delete a custom pack's files (refuses standard packs)
- `validate_pack(jurisdiction, year, variant)` — wraps `RulePack.load()`, returns structured errors
- `import_yaml(manifest_bytes, rules_bytes, is_custom)` — validate uploaded YAML, write to correct directory
- `export_yaml(jurisdiction, year, variant)` — return raw YAML file contents

Path resolution is centralized in `_pack_path(jurisdiction, year, variant)` enforcing the naming convention:
- Federal standard: `rule_packs/federal/{year}/`
- Federal custom: `rule_packs/federal/{year}/custom_v1/`
- State standard: `rule_packs/state/{ST}/{year}/`
- State custom: `rule_packs/state/{ST}/{year}/custom_v1/`

The function detects federal vs state by checking `jurisdiction.lower() in {"federal", "fed"}` vs a 2-letter state code.

`list_all_packs()` scans for `custom_v*/` subdirectories within each year directory to discover custom variants.

### Write Safety

- All writes go through the service layer (never direct file manipulation from routes)
- Standard packs are read-only — mutation functions raise `ValueError` for standard packs
- Full pack validation via `RulePack.load()` before writing to prevent saving broken packs
- Atomic write pattern: write to `.tmp` file, then rename
- **CSRF protection:** All 7 POST routes use the existing `_verify_csrf(request, csrf_token)` double-submit cookie pattern, matching the rest of the app
- Import rejects uploads that would overwrite an existing pack without explicit confirmation
- Deletion of custom packs that are currently selected as the active variant in a saved run emits a warning (not a block)

### Routes (in `main.py`)

```
GET  /rule-packs                                              — list page
GET  /rule-packs/import                                       — import form
POST /rule-packs/import                                       — handle upload  [CSRF]
POST /rule-packs/create                                       — create empty custom pack  [CSRF]
GET  /rule-packs/{jurisdiction}/{year}/{variant}               — pack detail
POST /rule-packs/{jurisdiction}/{year}/{variant}/clone         — clone action  [CSRF]
POST /rule-packs/{jurisdiction}/{year}/{variant}/delete        — delete pack  [CSRF]
POST /rule-packs/{jurisdiction}/{year}/{variant}/validate      — validate pack  [CSRF]
GET  /rule-packs/{jurisdiction}/{year}/{variant}/export        — download YAML
GET  /rule-packs/{jurisdiction}/{year}/{variant}/rules/add     — new rule form (NOTE: "add" not "new" to avoid route conflict with {rule_id})
POST /rule-packs/{jurisdiction}/{year}/{variant}/rules/add     — save new rule  [CSRF]
GET  /rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}       — rule editor
POST /rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}       — save rule  [CSRF]
POST /rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}/delete — delete rule  [CSRF]
```

**Route ordering note:** The literal `/rules/add` routes MUST be registered before the parameterized `/rules/{rule_id}` routes in FastAPI to avoid `add` being captured as a `rule_id`.

### Calculate Form Integration

The existing `_get_federal_pack()` and `_get_state_packs()` helpers are extended to accept an optional variant parameter. The calculate form adds a "Rule Pack Variant" dropdown populated from `list_all_packs()`, defaulting to "Standard".

## Templates & JavaScript

### New Templates (4 files)

1. `app/templates/pages/rule_packs.html` — Pack Manager list
2. `app/templates/pages/rule_pack_detail.html` — Pack detail with rule list
3. `app/templates/pages/rule_editor.html` — Single rule editor (type-adaptive)
4. `app/templates/pages/rule_pack_import.html` — YAML import form

### JavaScript (inline, vanilla, matching existing patterns)

- Rule editor type switcher: shows/hides form sections based on type dropdown
- Bracket table editor: add/remove `<tr>` rows, reindex hidden field names
- Dynamic reference list (sum rules): add/remove input rows
- Lookup table editor: add/remove key-value rows
- Pack creation inline form: toggle visibility

No external JS libraries.

## Input Validation & Path Safety

All route path parameters are validated before reaching the service layer:
- `jurisdiction` must match `^[a-zA-Z]{2,10}$` (e.g., "federal", "CA", "NY")
- `year` must be a 4-digit integer (2000–2099)
- `variant` must match `^(standard|custom_v\d+)$`
- `rule_id` must match the existing namespace pattern `^[a-z]{2,10}\.\d{4}\.[a-z0-9_.]+$`

The `_pack_path()` function resolves paths within `rule_packs/` only; any path component containing `..` or `/` is rejected. This prevents path traversal attacks since the feature writes and deletes files from user-controlled parameters.

The `list_all_packs()` scan skips directories starting with `_` (e.g., `_template`) to avoid surfacing internal scaffolding in the UI.

## Cache Invalidation

Custom packs created, edited, or deleted at runtime must invalidate the module-level `_federal_cache` / `_state_cache`. The cache key changes from `year` to `(year, variant)`. After any write operation, the editor service calls a `_bust_pack_cache(jurisdiction, year, variant)` helper that removes the relevant cache entry so the next `_get_federal_pack()` / `_get_state_packs()` call reloads from disk.

## Rule Validation Rules

- Rule IDs must match namespace: `{jurisdiction}.{year}.*`
- Expression syntax validated against existing allowlist in `rule_loader.py`
- Bracket tables must have ascending thresholds and valid rates (0–100%)
- References in sum/formula rules must resolve within the pack (or known cross-pack refs)
- Manifest jurisdiction and tax_year must match target directory
- Custom packs cannot use rule IDs colliding with another pack's namespace
- Full `RulePack.load()` validation on every save

## Testing

### `tests/test_rule_pack_editor.py` — Service layer

- `test_list_all_packs` — discovers standard + custom packs
- `test_clone_pack` — clones standard to custom with correct naming
- `test_clone_auto_increments_version` — cloning twice produces v1 and v2
- `test_save_rule_to_custom_pack` — add/update rule, verify YAML
- `test_save_rule_to_standard_pack_raises` — refuses standard pack mutation
- `test_delete_rule` — removes rule from custom pack
- `test_delete_standard_pack_raises` — refuses standard pack deletion
- `test_validate_pack_returns_errors` — bad pack returns structured errors
- `test_create_empty_pack` — creates manifest + empty rules
- `test_import_yaml_valid` — valid upload writes to correct location
- `test_import_yaml_invalid_rejected` — bad YAML returns errors, nothing written

### `tests/test_rule_pack_routes.py` — Route integration

- `test_rule_packs_list_page` — GET returns 200 with packs
- `test_pack_detail_page` — pack detail shows rules
- `test_clone_pack_via_post` — POST clone creates custom variant
- `test_rule_editor_renders` — correct form for each rule type
- `test_save_rule_via_post` — save and redirect
- `test_delete_custom_pack_via_post` — delete and redirect
- `test_import_upload` — valid YAML upload succeeds
- `test_export_download` — export returns YAML content
- `test_calculate_with_custom_pack` — end-to-end: clone, modify, calculate, verify different result

## Files Changed

- **Create:** `app/services/rule_pack_editor.py`, `app/templates/pages/rule_packs.html`, `app/templates/pages/rule_pack_detail.html`, `app/templates/pages/rule_editor.html`, `app/templates/pages/rule_pack_import.html`, `tests/test_rule_pack_editor.py`, `tests/test_rule_pack_routes.py`
- **Modify:** `main.py` (routes + variant dropdown), `app/templates/pages/calculate.html` (variant dropdown), `app/templates/layouts/base.html` (nav link), `README.md` (tree update), `CHANGELOG.md`

## GitHub Import Documentation

A new section in `docs/RULE_PACK_AUTHORING.md` explaining how to manually fetch rule packs from the GitHub repository:
- Clone the repo or download a release
- Copy the desired `rule_packs/{jurisdiction}/{year}/` directory into the local installation
- Restart the app to pick up new packs

Future enhancement: CLI helper script for automated fetching.
