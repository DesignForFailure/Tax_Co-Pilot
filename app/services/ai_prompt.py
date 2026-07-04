# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI authoring prompt builder.

Generates a complete, schema-aware prompt a user can paste into any AI
assistant to have a rule pack drafted for them. The prompt embeds the
authoritative pack contract (mirroring docs/RULE_PACK_AUTHORING.md), the
live reference catalog for the target jurisdiction/year, and an output
format that pastes straight back into the paste-to-import flow.

Everything is assembled locally from repository data — no network calls,
no API keys. The user chooses which AI (if any) ever sees the prompt.
"""

from __future__ import annotations

from pathlib import Path

from app.engine.rule_loader import RulePack, RulePackError
from app.services.ref_catalog import (
    FILING_STATUS_KEY_REF,
    constants_table_paths,
    input_ref_options,
)
from app.services.rule_pack_editor import _pack_path

_FEDERAL_ALIASES = {"federal", "fed", "us", "usa"}

MAX_DESCRIPTION_CHARS = 10_000

# ─── Static contract text (mirrors docs/RULE_PACK_AUTHORING.md) ─────────────

_RULE_TYPE_SPEC = """\
## Rule pack contract

A pack is exactly two YAML documents.

`manifest.yaml` — exactly these required fields:

```yaml
version: "1.0.0"        # full SemVer string, quoted
tax_year: {year}
jurisdiction: "{jurisdiction_value}"
```

`rules.yaml` — top level is a mapping with two keys:

```yaml
constants: {{}}          # optional named tables (see Constants below)
rules: []                # list of rule mappings
```

Every rule id MUST start with the prefix `{prefix}` and use only lowercase
letters, digits, dots, underscores (convention:
`{prefix}{year}.<category>.<name>`, e.g. `{prefix}{year}.taxable_income`).

There are exactly five rule types. ALL numeric values everywhere are
QUOTED DECIMAL STRINGS (`"14600"`, `"0.0539"`, `"-3000"`) — never bare
numbers. Every rule should carry a human-readable `description`.

### 1. formula — arithmetic over named inputs

```yaml
- id: "{prefix}{year}.taxable_income"
  description: "Taxable income"
  type: "formula"
  expression: "max(agi - deduction, 0)"
  inputs:
    agi:       {{ ref: "{prefix}{year}.agi" }}
    deduction: {{ ref: "{prefix}{year}.standard_deduction" }}
  rounding: "ROUND_HALF_UP"
  rounding_precision: 0
```

- Every identifier in `expression` MUST be declared as a key under
  `inputs` (bound to `{{ ref: "..." }}` or `{{ literal: "0.04" }}`).
- `inputs` must be NON-EMPTY on every formula rule — even a rule that
  returns a constant needs one declared input, e.g.
  `expression: "zero"` with `inputs: {{ zero: {{ literal: "0" }} }}`.
- Allowed expression characters (exact set): letters, digits, underscore,
  `+ - * / ( ) , .` and space. Nothing else — no `%`, no comparison
  operators, no quotes.
- The only functions are `max(...)` and `min(...)`.
- Bare numeric literals may appear inline (`max(x, 0)`).

### 2. lookup — one-dimensional constant table

```yaml
- id: "{prefix}{year}.standard_deduction"
  description: "Standard deduction"
  type: "lookup"
  table: "constants.standard_deduction"
  key: {{ ref: "input.filing_status" }}
```

- `table` is a dotted path into the `constants:` block and must start
  with `constants.`.
- No `rounding` or `inputs` fields — the raw table value is returned.

### 3. sum — total a collection or list of refs

```yaml
- id: "{prefix}{year}.gross_income.total"
  description: "Total income"
  type: "sum"
  inputs:
    items:
      - {{ ref: "{prefix}{year}.gross_income.wages" }}
      - {{ ref: "{prefix}{year}.gross_income.interest" }}
  rounding: "ROUND_HALF_UP"
  rounding_precision: 2
```

- `items` may instead be a single `{{ ref: "..." }}` when the referenced
  input is itself a collection (e.g. `input.withholding.state.XX`).

### 4. bracket_table — graduated brackets keyed by filing status

```yaml
- id: "{prefix}{year}.tax.base"
  description: "Income tax from brackets"
  type: "bracket_table"
  input: {{ ref: "{prefix}{year}.taxable_income" }}
  key: {{ ref: "input.filing_status" }}
  rounding: "ROUND_HALF_UP"
  rounding_precision: 0
  tables:
    single:
      - {{ lower: "0",     upper: "10000", rate: "0.02" }}
      - {{ lower: "10000", upper: null,    rate: "0.04" }}
    mfj:
      - {{ lower: "0",     upper: "20000", rate: "0.02" }}
      - {{ lower: "20000", upper: null,    rate: "0.04" }}
```

- Provide a bracket list for EVERY filing status a filer may use:
  `single`, `mfj`, `mfs`, `hoh`, `qss`.
- Brackets must be ordered, non-overlapping (`lower` >= previous
  `upper`), each `upper` > its `lower`; only the last bracket may omit
  `upper` (or set it `null`) for "no ceiling". Rates apply graduated
  (only to income inside each slice).

### 5. matrix_lookup — multi-dimensional constant table

```yaml
- id: "{prefix}{year}.credits.example.max_credit"
  description: "Credit by filing status and child count"
  type: "matrix_lookup"
  keys:
    - "input.filing_status"
    - {{ ref: "{prefix}{year}.credits.example.num_children" }}
  table:
    single: {{ "0": "600", "1": "4200", "2": "6900", "3": "7800" }}
    mfj:    {{ "0": "600", "1": "4200", "2": "6900", "3": "7800" }}
    mfs:    {{ "0": "0",   "1": "0",    "2": "0",    "3": "0" }}
    hoh:    {{ "0": "600", "1": "4200", "2": "6900", "3": "7800" }}
    qss:    {{ "0": "600", "1": "4200", "2": "6900", "3": "7800" }}
```

- `keys` needs at least two entries; each is a reference string or a
  `{{ ref: "..." }}` mapping. `table` must nest exactly as deep as `keys`
  is long.
- ALL table keys must be strings — QUOTE numeric keys (`"2":` not `2:`).
- An unknown key value fails the whole calculation, so clamp open-ended
  inputs with an upstream formula rule (e.g. `min(children, 3)`).

## Constants

- `constants:` maps names to tables of quoted decimal strings, at most two
  levels deep. Keys use lowercase letters, digits, underscores (no dots).
- Filing-status tables use exactly the keys `single`, `mfj`, `mfs`,
  `hoh`, `qss`.
- Constants are pack-local: a pack cannot read another pack's constants.

## Rounding

- `formula`, `sum`, and `bracket_table` rules should declare `rounding`
  plus `rounding_precision` (`2` for intermediates in cents, `0` for
  whole-dollar form-line outputs).
- Exactly three modes exist: `"ROUND_HALF_UP"` (ordinary rounding — the
  default and the right choice for most rules), `"ROUND_UP"` (away from
  zero — required for step counts like "reduced $50 per $1,000 *or
  fraction thereof*"), and `"ROUND_DOWN"` (truncate toward zero). Any
  other mode is rejected; picking HALF_UP where the law says "or
  fraction thereof" silently understates the phaseout.
- `lookup` and `matrix_lookup` do no arithmetic and take no rounding.

## References

- `{{ ref: "..." }}` may point at another rule's id in the same pack, an
  engine input (`input.*` — see catalog below), or, from a state pack, a
  federal rule id (`fed.{year}.*`); the federal pack always runs first.
- `input.filing_status` is key-only: it may be a lookup/bracket `key` or
  a matrix key, but never a numeric input to a formula or sum.
"""

_FEDERAL_REQUIRED = """\
## Required rules (federal pack)

The engine refuses to run a federal pack unless these four rules exist:

- `fed.{year}.agi.total`
- `fed.{year}.taxable_income`
- `fed.{year}.tax.after_credits`
- `fed.{year}.refund_or_owed` (refund positive, balance due negative)
"""

_STATE_REQUIRED = """\
## Required rules (state pack)

The engine extracts state results by convention. An income-tax pack needs:

- `{prefix}{year}.agi` (usually starts from `fed.{year}.agi.total`)
- `{prefix}{year}.taxable_income`
- `{prefix}{year}.tax.full` (tax before apportionment)
- `{prefix}{year}.tax` (after apportionment:
  `tax.full * input.state.apportionment.{state}`)
- `{prefix}{year}.credits.other_state`
  (`min(other_state_tax, tax.full * other_state_ratio) * is_resident`)
- `{prefix}{year}.credits.total` (fold in other_state, cap at tax)
- `{prefix}{year}.withholding`
  (sum of `input.withholding.state.{state}`)
- `{prefix}{year}.refund_or_owed` (`withholding - tax + credits`
  per your state's form; refund positive)

For a no-income-tax state, a minimal stub suffices: `agi` and `tax` as
formula rules returning zero (`expression: "zero"` with
`inputs: {{ zero: {{ literal: "0" }} }}` — remember formula rules must
declare at least one input), `withholding` summing
`input.withholding.state.{state}`, and `refund_or_owed` as
`withholding - tax`.
"""

_SELF_CHECK = """\
## Before you answer — self-check

1. Every rule id starts with `{prefix}` and the pack contains every
   required rule listed above.
2. Every identifier in every formula `expression` is declared under that
   rule's `inputs`.
3. Every `{{ ref: "..." }}` points at a rule id you defined, an `input.*`
   reference from the catalog, or (state packs only) a federal
   `fed.{year}.*` rule id.
4. Every number anywhere is a quoted decimal string.
5. Bracket lists are ordered and non-overlapping; only the last bracket
   omits `upper`.
6. matrix_lookup tables nest exactly as deep as `keys` is long and all
   table keys are quoted strings.
7. Every lookup `table:` path exists under `constants:`.
8. No rule references `input.filing_status` as a formula/sum input.
9. Every formula rule declares a non-empty `inputs` mapping, and every
   `rounding` value is exactly ROUND_HALF_UP, ROUND_UP, or ROUND_DOWN —
   with ROUND_UP wherever the law says "or fraction thereof".

## Output format (exact)

Reply with ONE fenced code block containing both documents joined by
these exact marker lines:

```
# === MANIFEST ===
<manifest.yaml content>
# === RULES ===
<rules.yaml content>
```

No other text inside the code block. The user will paste the block into
Tax Co-Pilot's Rule Packs → Import YAML → "Paste combined YAML" box,
which validates it and reports any errors — if the user returns with a
validation error, correct the YAML and resend the full block.
"""


def _jurisdiction_prefix_and_value(jurisdiction: str) -> tuple[str, str]:
    """Return (rule-id prefix, canonical manifest jurisdiction value)."""
    j = jurisdiction.strip()
    if j.lower() in _FEDERAL_ALIASES:
        return "fed.", "federal"
    if len(j) == 2 and j.isalpha():
        return f"{j.lower()}.", j.upper()
    raise ValueError(
        "Jurisdiction must be 'federal' or a two-letter state code (e.g. GA)"
    )


def _load_pack_or_none(
    jurisdiction: str, year: int, *, base_dir: Path | None
) -> RulePack | None:
    """Best-effort load of the standard pack; None when absent or invalid."""
    try:
        pack_dir = _pack_path(jurisdiction, year, "standard", base_dir=base_dir)
        return RulePack.load(pack_dir)
    except (RulePackError, ValueError, OSError):
        return None


def _rule_lines(pack: RulePack) -> list[str]:
    lines = []
    for rule_id in pack.rule_order:
        description = str(pack.rules[rule_id].get("description", "")).strip()
        lines.append(f"- `{rule_id}` — {description}" if description else f"- `{rule_id}`")
    return lines


def _catalog_section(
    jurisdiction: str,
    year: int,
    prefix: str,
    *,
    base_dir: Path | None,
) -> str:
    """The live reference catalog: inputs, existing pack, federal targets."""
    parts: list[str] = ["## Reference catalog (authoritative — use only these)\n"]

    parts.append("### Engine inputs (`input.*`)\n")
    parts.append(
        f"- `{FILING_STATUS_KEY_REF}` — filing status key: one of "
        "`single`, `mfj`, `mfs`, `hoh`, `qss` (key-only, see above)"
    )
    parts.extend(f"- `{ref}`" for ref in input_ref_options(jurisdiction))
    parts.append("")

    is_federal = prefix == "fed."
    standard = _load_pack_or_none(jurisdiction, year, base_dir=base_dir)
    if standard is not None:
        parts.append(
            f"### Rules in the shipped standard {jurisdiction} {year} pack\n"
        )
        parts.append(
            "Reuse these ids when your pack builds on the standard one; a "
            "custom pack replaces the whole pack, so include every rule the "
            "result depends on.\n"
        )
        parts.extend(_rule_lines(standard))
        table_paths = constants_table_paths(standard.constants)
        if table_paths:
            parts.append("\nIts constants tables:\n")
            parts.extend(f"- `{path}`" for path in table_paths)
        parts.append("")

    if not is_federal:
        federal = _load_pack_or_none("federal", year, base_dir=base_dir)
        if federal is not None:
            parts.append(
                f"### Federal {year} rule ids (cross-pack reference targets)\n"
            )
            parts.extend(_rule_lines(federal))
            parts.append("")

    return "\n".join(parts)


def build_authoring_prompt(
    jurisdiction: str,
    year: int,
    description: str,
    *,
    base_dir: Path | None = None,
) -> str:
    """Assemble the full copy-paste authoring prompt.

    Raises ValueError for an unusable jurisdiction/year/description; the
    route surfaces the message on the form.
    """
    prefix, jurisdiction_value = _jurisdiction_prefix_and_value(jurisdiction)
    if not (2000 <= year <= 2099):
        raise ValueError(f"Invalid year: {year}")
    wanted = description.strip()
    if not wanted:
        raise ValueError("Describe the rules you want before generating a prompt")
    if len(wanted) > MAX_DESCRIPTION_CHARS:
        raise ValueError(
            f"Description exceeds {MAX_DESCRIPTION_CHARS} characters"
        )

    state = jurisdiction_value if jurisdiction_value != "federal" else ""
    required = (
        _FEDERAL_REQUIRED.format(year=year)
        if prefix == "fed."
        else _STATE_REQUIRED.format(prefix=prefix, year=year, state=state)
    )
    # Aliases like "us"/"usa" must load the federal pack, not a
    # nonexistent state/USA directory — use the canonical value.
    catalog_jurisdiction = "federal" if prefix == "fed." else jurisdiction_value

    header = (
        "You are drafting a rule pack for Tax Co-Pilot, a local-first tax "
        "calculator whose tax logic lives in versioned YAML \"rule packs\" "
        "evaluated with exact Decimal arithmetic. Follow the contract below "
        "EXACTLY — the pack is machine-validated on import and any deviation "
        "is rejected.\n\n"
        f"Target pack: jurisdiction `{jurisdiction_value}`, tax year {year}, "
        f"rule-id prefix `{prefix}`.\n\n"
        "## What the user wants\n\n"
        '"""\n'
        f"{wanted}\n"
        '"""\n'
    )

    return "\n".join(
        [
            header,
            _RULE_TYPE_SPEC.format(
                year=year,
                jurisdiction_value=jurisdiction_value,
                prefix=prefix,
            ),
            required,
            _catalog_section(catalog_jurisdiction, year, prefix, base_dir=base_dir),
            _SELF_CHECK.format(prefix=prefix, year=year),
        ]
    )
