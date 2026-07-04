# Authoring for Non-Coders — Design

Date: 2026-07-03
Status: Approved (combined milestone, single PR)

## Problem

Field feedback: tax accountants cannot author rule packs. The web editor
(PR #42) removed YAML *syntax* but not *code*: reference paths and formula
expressions are free-typed text, `matrix_lookup` rules are rejected by the
form parser, and pack `constants` — which every `lookup` rule depends on —
cannot be edited anywhere in the UI. There is also no AI-assisted path.

## Goals

1. **AI Authoring Assistant (copy-paste, zero egress).** Generate a complete,
   schema-aware prompt the user pastes into any AI they already use. The AI
   returns a pack in the combined export format; the user pastes it back into
   a new paste-to-import mode. Validation (`RulePack.load`) already gates
   import, closing the verify loop. No API calls, no keys — consistent with
   the local-first privacy posture.
2. **GUI authoring completeness.** Constants editor, `matrix_lookup` form
   section, reference autocomplete, bracket-table ergonomics, inline guidance.

Non-goals: calling AI APIs from the app (future opt-in at most); a full
expression builder; editing standard packs (they stay read-only).

## Design

### A1. Input reference catalog — `known_input_refs()` + `app/services/ref_catalog.py`

The `input.*` namespace exists only as assignments inside
`CalculationEngine._resolve_inputs()`. A public `known_input_refs()` in
`app/engine/calculator.py` derives the base catalog at runtime by
normalizing a synthetic empty `TaxReturnInput` (no hardcoded list to
drift; the private method stays private to its own module).
`app/services/ref_catalog.py` layers on top:

- `input.filing_status` special-cased (key-only; not a Decimal ref),
- parameterized state patterns (`input.withholding.state.{ST}`,
  `input.state.is_resident.{ST}`, `input.state.apportionment.{ST}`,
  `input.state.other_state_tax`, `input.state.other_state_ratio`),
- `constants.*` dotted table paths for a pack's constants.

Consumed by both the prompt builder and the reference picker. Engine layer
is appropriate for the derivation: no I/O, no persistence. A test asserts
the derived catalog is non-empty and every entry starts with `input.`.

### A2. Prompt builder — `app/services/ai_prompt.py`

`build_authoring_prompt(jurisdiction, year, description, *, base_dir=None) -> str`
assembles, from authoritative sources (mirroring `docs/RULE_PACK_AUTHORING.md`):

1. Task preamble + the user's plain-English description (delimited section).
2. Manifest contract (3 fields, SemVer, jurisdiction → rule-ID prefix).
3. All five rule types with minimal valid YAML + the constraints that trip
   authors (decimal *strings*, quoted numeric matrix keys, bracket ordering,
   every expression identifier declared under `inputs`).
4. Expression allowlist (exact character set; `max`/`min` only).
5. Constants system + rounding conventions.
6. Live reference catalog: `input.*` list from A1; when a standard pack
   exists for the jurisdiction/year, its rule IDs + descriptions and constants
   paths; for state packs, the federal pack's rule IDs (cross-pack targets)
   plus required state rule IDs and the apportionment tail.
7. Output contract: **one combined document** using the existing export
   sentinels (`# === MANIFEST ===` / `# === RULES ===`) so the response
   pastes straight into import.
8. A self-check list the AI must run before answering.

### A3. Routes + page

- `GET/POST /rule-packs/ai-assist` in `app/routes/rule_packs.py` (CSRF
  double-submit as elsewhere). POST re-renders with the generated prompt in a
  readonly textarea + copy button.
- Template `pages/rule_pack_ai_assist.html`; JS `app/static/js/ai-assist.js`
  (clipboard copy via `data-copy-target`, CSP-safe external file).
- Description bounded (10k chars) — `form_str`'s 200-char cap is too small,
  so a dedicated bounded read.

### A4. Paste-to-import

- `pages/rule_pack_import.html` gains a "Paste combined YAML" form (textarea
  `combined_text` + `custom_name`), alongside the existing two-file upload.
- `split_combined_yaml(text) -> (manifest_bytes, rules_bytes)` in
  `rule_pack_editor.py` (inverse of `export_yaml`'s combined format;
  `ValueError` on missing/misordered sentinels).
- `rule_packs_import_post` branches on non-empty `combined_text`; identical
  tail (2 MiB cap, `import_yaml`, cache bust, 303).
- On import error: re-render preserving the pasted text + an "AI round-trip"
  hint (copy the error back to your AI, paste the corrected YAML).

### B1. Constants editor

Observed corpus (21 packs): exactly two shapes — flat filing-status mapping
(54×) and 2-level `group → status → value` (12×); all values decimal strings;
consumed only via `lookup` `table:` dotted paths. The editor models exactly
that: a constant is one or more named rows of five status cells (flat = one
unnamed row).

- Service (`rule_pack_editor.py`): `save_constant`, `delete_constant`
  (custom packs only; same temp-dir validate-before-write as `save_rule`).
  `delete_constant` additionally refuses when any rule's `table:` references
  the constant (the loader does not check lookup paths at load time, so
  deletion would otherwise break calculation at runtime).
  `load_pack_detail` now returns `constants`.
- Form encoding (`parse_constant_form` in `form_parsing.py`):
  `constant_name`, groups as `group_{i}_name` + `group_{i}_{status}` cells;
  a single unnamed group saves flat. Values validated as Decimal strings.
- Routes: `.../constants/add`, `.../constants/{name}` (edit),
  `.../constants/{name}/delete`. Template `pages/constant_editor.html`;
  constants table added to `rule_pack_detail.html`.

### B2. matrix_lookup form section

Loader contract: `keys` list (≥2; bare ref string or `{ref: ...}`), `table`
nested exactly `len(keys)` deep, string keys, Decimal-parseable leaves. All
12 real rules are 2-dimensional. The form supports the 2-key case as a grid:
column headers = inner keys, rows = outer key + cells. Encoding:
`matrix_key_0/1`, `matrix_col_{c}`, `matrix_row_{r}_key`,
`matrix_cell_{r}_{c}` (gap-tolerant, capped at `MAX_INDEXED_ENTRIES`).
`parse_rule_form`'s hard rejection is replaced by this parsing; deeper
matrices remain YAML-import-only (stated in the UI).

### B3. Reference picker + guidance

- Editor routes build a catalog: same-pack rule IDs (+ descriptions),
  `constants.*` dotted paths, `input.*` from A1 (state patterns instantiated
  for the pack's jurisdiction), and for state packs the federal rule IDs for
  that year (via `pack_cache`, guarded when absent).
- Rendered as `<datalist>`s in `rule_editor.html`; every ref input (static
  and JS-added rows) gets `list=` + `inputmode` where numeric.
- Bracket ergonomics: per-status "copy rows from…" action, rate format hint
  ("0.22 = 22%"), `upper` blank = no ceiling explained.
- Plain-language ref-vs-literal explanation; links to
  `docs/RULE_PACK_AUTHORING.md`.

## Security

No new I/O surfaces beyond existing validated paths (`_pack_path` guards all
segment inputs; constants routes reuse it). Paste-import feeds the same
size-capped bytes into the same validate-then-commit `import_yaml`. CSP
unchanged (no inline JS/CSS). CSRF on every new POST. The AI prompt is
generated locally from repo data only; nothing leaves the machine unless the
user themselves pastes it elsewhere.

## Testing

- Unit: prompt builder content (schema facts, catalog, sentinels contract),
  `split_combined_yaml` edges, constants CRUD (incl. referenced-constant
  delete refusal), matrix form parsing round-trip, input catalog sanity.
- Routes: ai-assist GET/POST, paste-import success/failure/preserved-text,
  constants add/edit/delete, matrix_lookup add→read-back.
- Gap-closing (from coverage survey): lookup rule via route, bracket_table
  via route with YAML read-back, formula literal inputs, strengthen
  `test_save_rule_via_post` to verify persistence, and an end-to-end
  "author via form-shaped dicts → save → load → calculate" test.

Definition of done: `ruff check . && mypy . && pytest` green.
