# SPDX-License-Identifier: AGPL-3.0-or-later
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Load and validate YAML rule packs.

Sections:
- RulePackError: a single exception type for pack validation failures.
- YAML loading helpers: safe_load + type checks.
- Integrity: SHA-256 checksum across YAML files for audit reproducibility.
- Dependency analysis: extract explicit {ref: ...} edges, validate, toposort.
- Expression validation: allowlisted mini-syntax for formula expressions.
- RulePack: immutable loaded pack with deterministic rule evaluation order.

Security/QA rationale:
- Uses `yaml.safe_load` (not `load`) to avoid arbitrary object construction.
- Validates rule IDs, rule types, and basic shapes to fail fast.
- Enforces namespace prefix so packs cannot overwrite each other's keys.
- Emits deterministic `checksum` for proving which rules produced a result.

Future improvements:
- Add deeper schema validation (JSONSchema / Pydantic model for rules.yaml).
- Add richer expression parsing if needed (keep allowlist model).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml  # type: ignore

# Expression validation is intentionally simple:
# - We do NOT execute expressions.
# - We scan to ensure only allowed chars/functions/identifiers appear.
_ALLOWED_EXPR_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_+-*/(),. "
)
_ALLOWED_FUNCS = {"max", "min"}
_ALLOWED_ROUNDING_MODES = {"ROUND_HALF_UP", "ROUND_DOWN", "ROUND_UP"}
# Rule ids flow into HTML templates and JS-string contexts; a conservative
# charset keeps quotes, angle brackets, and whitespace out of that path.
_RULE_ID_CHARSET_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")
# Prefixes owned by the engine ("input.") or reachable only through the
# federal aliases ("fed.") must not be claimable via a free-form
# jurisdiction string.
_RESERVED_JURISDICTIONS = {"input", "inputs"}
_LEGACY_NUMERIC_VERSION_RE = re.compile(
    r"^(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$"
)
_SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)\."
    r"(0|[1-9]\d*)"
    r"(?:-"
    r"(?:(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9]\d*|\d*[A-Za-z-][0-9A-Za-z-]*))*)"
    r")?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


class RulePackError(ValueError):
    """Raised when a rule pack is invalid or cannot be loaded."""


def normalize_rule_pack_version(version: Any) -> str:
    """Normalize a rule-pack manifest version to canonical semantic version text.

    Backward compatibility:
    - Legacy custom packs created by older app versions stored shorthand numeric
      versions such as ``1``. Those continue to load as ``1.0.0``.
    - New packs should still write full semantic versions directly.
    """
    raw = str(version).strip()
    if not raw:
        raise RulePackError("manifest.yaml must include non-empty 'version'")

    if _SEMVER_RE.fullmatch(raw):
        return raw

    legacy_match = _LEGACY_NUMERIC_VERSION_RE.fullmatch(raw)
    if legacy_match:
        major = legacy_match.group(1)
        minor = legacy_match.group(2) or "0"
        return f"{major}.{minor}.0"

    raise RulePackError(
        "manifest.yaml 'version' must be a Semantic Version such as "
        "'1.0.0' or '1.0.0-alpha.1'"
    )


def _jurisdiction_prefix(jurisdiction: str) -> str:
    """Map a jurisdiction string to a required rule-id prefix.

    Examples:
    - "federal" -> "fed."
    - "FED" -> "fed."
    - "GA" -> "ga."

    This is a safety boundary: it prevents packs from overwriting each other's
    `resolved[...]` values when multiple jurisdictions run in one engine.
    """
    j = (jurisdiction or "").strip().lower()
    if j in {"federal", "fed", "us", "usa"}:
        return "fed."
    if j in _RESERVED_JURISDICTIONS:
        raise RulePackError(f"Jurisdiction {jurisdiction!r} is reserved")
    if len(j) == 2 and j.isalpha():
        return f"{j}."
    if j.isidentifier():
        return f"{j}."
    raise RulePackError(f"Unsupported jurisdiction value: {jurisdiction!r}")


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return a dict.

    Security:
    - Uses yaml.safe_load.
    - Rejects non-mapping top-level structures.

    QA:
    - Raises RulePackError with file context for faster debugging.
    """
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except FileNotFoundError as e:
        raise RulePackError(f"Missing rule pack file: {path}") from e
    except yaml.YAMLError as e:
        raise RulePackError(f"Invalid YAML in {path}: {e}") from e

    if not isinstance(data, dict):
        raise RulePackError(f"Top-level YAML must be a mapping in {path}")
    return data


def _resolve_pack_file(pack_dir: Path, canonical_name: str, pattern_suffix: str) -> Path:
    """Resolve a rule-pack file path with backward-compatible naming.

    Preferred names are the canonical files (`manifest.yaml` and `rules.yaml`).
    For compatibility with legacy/generated packs, this also supports exactly
    one `*_<suffix>.yaml` match (for example `federal_2024_manifest.yaml`).
    """
    canonical = pack_dir / canonical_name
    if canonical.exists():
        return canonical

    candidates = sorted(pack_dir.glob(f"*_{pattern_suffix}.yaml"), key=lambda p: p.name)
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise RulePackError(
            f"Missing rule pack file: expected {canonical} or one '*_{pattern_suffix}.yaml' file"
        )
    raise RulePackError(
        f"Ambiguous rule pack file for {canonical_name}: found {', '.join(p.name for p in candidates)}"
    )


def _sha256_files(paths: Iterable[Path]) -> str:
    """Compute a deterministic SHA-256 checksum over a set of files.

    Each file's name and byte length frame its content so that shifting
    bytes across file boundaries (or renaming files) cannot produce a
    checksum collision between two different packs.
    """
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        data = p.read_bytes()
        h.update(p.name.encode("utf-8"))
        h.update(b"\x00")
        h.update(len(data).to_bytes(8, "big"))
        h.update(data)
    return h.hexdigest()


def _iter_refs(obj: Any) -> Iterator[str]:
    """Yield all explicit reference strings from a rule structure.

    We only treat YAML objects of the form `{ref: "some.rule.id"}` as dependencies.
    This avoids accidentally treating free-form strings (descriptions, literals) as refs.
    """
    if isinstance(obj, dict):
        if set(obj.keys()) == {"ref"} and isinstance(obj.get("ref"), str):
            yield obj["ref"]
            return
        for v in obj.values():
            yield from _iter_refs(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _iter_refs(v)


def _build_rule_deps(rules: dict[str, dict[str, Any]], id_prefix: str) -> dict[str, set[str]]:
    """Build dependency edges: rule_id -> referenced_rule_ids.

    Only includes refs within the same pack (matching id_prefix).
    Cross-pack refs (e.g. state referencing federal) are resolved at runtime.
    """
    deps: dict[str, set[str]] = {rid: set() for rid in rules}
    for rid, rule in rules.items():
        for ref in _iter_refs(rule):
            if ref.startswith("input."):
                continue
            # Skip cross-pack references
            if not ref.startswith(id_prefix):
                continue
            deps[rid].add(ref)
    return deps


def _validate_deps(rules: dict[str, dict[str, Any]], deps: dict[str, set[str]]) -> None:
    """Validate missing refs and cycles."""
    for rid, refs in deps.items():
        for ref in refs:
            if ref.startswith("input."):
                continue
            if ref not in rules:
                raise RulePackError(f"Rule {rid} references unknown rule id: {ref}")

    visiting: set[str] = set()
    visited: set[str] = set()

    def dfs(node: str, stack: list[str]) -> None:
        if node in visited:
            return
        if node in visiting:
            cycle = " -> ".join(stack + [node])
            raise RulePackError(f"Rule dependency cycle detected: {cycle}")

        visiting.add(node)
        for nxt in sorted(deps.get(node, set())):
            if nxt in rules:
                dfs(nxt, stack + [node])
        visiting.remove(node)
        visited.add(node)

    for rid in rules:
        dfs(rid, [])


def _toposort_rules(rules: dict[str, dict[str, Any]], deps: dict[str, set[str]]) -> list[str]:
    """Return a deterministic topological ordering of rules."""
    # Kahn's algorithm with sorted tie-breaking
    indeg: dict[str, int] = {rid: 0 for rid in rules}
    out_edges: dict[str, set[str]] = {rid: set() for rid in rules}

    for rid, refs in deps.items():
        for ref in refs:
            if ref in rules:
                out_edges[ref].add(rid)
                indeg[rid] += 1

    ready = sorted([rid for rid, d in indeg.items() if d == 0])
    order: list[str] = []

    while ready:
        n = ready.pop(0)
        order.append(n)
        for m in sorted(out_edges[n]):
            indeg[m] -= 1
            if indeg[m] == 0:
                # keep ready sorted for determinism
                lo, hi = 0, len(ready)
                while lo < hi:
                    mid = (lo + hi) // 2
                    if ready[mid] < m:
                        lo = mid + 1
                    else:
                        hi = mid
                ready.insert(lo, m)

    if len(order) != len(rules):
        raise RulePackError("Topological sort failed; possible dependency cycle")

    return order


# ─── Rule type validators ─────────────────────────────────────


def _extract_identifiers(expr: str) -> set[str]:
    out: set[str] = set()
    buf: list[str] = []

    def flush() -> None:
        if buf:
            out.add("".join(buf))
            buf.clear()

    for ch in expr:
        if ch.isalpha() or ch == "_" or (buf and ch.isdigit()):
            buf.append(ch)
        else:
            flush()
    flush()
    return out


def _validate_sum_rule(rule: dict[str, Any]) -> None:
    rid = rule.get("id", "<unknown>")
    inputs = rule.get("inputs")
    if not isinstance(inputs, dict) or "items" not in inputs:
        raise RulePackError(f"Rule {rid} (sum) must include inputs.items")


def _validate_lookup_rule(rule: dict[str, Any]) -> None:
    rid = rule.get("id", "<unknown>")
    table = rule.get("table")
    key = rule.get("key")
    if not isinstance(table, str) or not table:
        raise RulePackError(f"Rule {rid} (lookup) must include non-empty 'table'")
    if key is None:
        raise RulePackError(f"Rule {rid} (lookup) must include 'key'")


def _validate_bracket_table_rule(rule: dict[str, Any]) -> None:
    rid = rule.get("id", "<unknown>")
    if "input" not in rule:
        raise RulePackError(f"Rule {rid} (bracket_table) must include 'input'")
    if "key" not in rule:
        raise RulePackError(f"Rule {rid} (bracket_table) must include 'key'")
    tables = rule.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise RulePackError(f"Rule {rid} (bracket_table) must include non-empty 'tables'")
    for status, brackets in tables.items():
        if not isinstance(brackets, list) or not brackets:
            raise RulePackError(
                f"Rule {rid} (bracket_table) tables[{status}] must be a non-empty list"
            )
        # The evaluator walks brackets in order and stops at the first one
        # whose lower bound exceeds income, so out-of-order, overlapping, or
        # open-ended middle brackets silently compute the wrong tax.
        prev_upper: Decimal | None = None
        for i, b in enumerate(brackets):
            if not isinstance(b, dict):
                raise RulePackError(f"Rule {rid} (bracket_table) has non-mapping bracket")
            for req in ("lower", "rate"):
                if req not in b:
                    raise RulePackError(f"Rule {rid} (bracket_table) bracket missing '{req}'")
            try:
                lower = Decimal(str(b["lower"]))
                upper = Decimal(str(b["upper"])) if b.get("upper") is not None else None
                Decimal(str(b["rate"]))
            except InvalidOperation as e:
                raise RulePackError(
                    f"Rule {rid} (bracket_table) tables[{status}] bracket {i} "
                    f"has a non-numeric bound or rate"
                ) from e
            if upper is None and i != len(brackets) - 1:
                raise RulePackError(
                    f"Rule {rid} (bracket_table) tables[{status}] bracket {i} "
                    f"omits 'upper' but is not the last bracket"
                )
            if upper is not None and upper <= lower:
                raise RulePackError(
                    f"Rule {rid} (bracket_table) tables[{status}] bracket {i} "
                    f"has upper {upper} <= lower {lower}"
                )
            if prev_upper is not None and lower < prev_upper:
                raise RulePackError(
                    f"Rule {rid} (bracket_table) tables[{status}] bracket {i} "
                    f"overlaps the previous bracket (lower {lower} < previous upper {prev_upper})"
                )
            prev_upper = upper


def _validate_matrix_table(
    rid: str, node: Any, remaining_dims: int, path: tuple[str, ...]
) -> None:
    """Recursively validate that a matrix table matches its declared key depth."""
    where = " → ".join(path) if path else "<root>"
    if remaining_dims == 0:
        try:
            Decimal(str(node))
        except InvalidOperation as e:
            raise RulePackError(
                f"Rule {rid} (matrix_lookup) leaf at {where} must be numeric, got {node!r}"
            ) from e
        return
    if not isinstance(node, dict) or not node:
        raise RulePackError(
            f"Rule {rid} (matrix_lookup) expects {remaining_dims} more nested "
            f"mapping level(s) at {where}, got {type(node).__name__}"
        )
    for key, child in node.items():
        if not isinstance(key, str):
            raise RulePackError(
                f"Rule {rid} (matrix_lookup) table key {key!r} at {where} must be a "
                f"string (quote numeric keys in YAML)"
            )
        _validate_matrix_table(rid, child, remaining_dims - 1, path + (key,))


def _validate_matrix_lookup_rule(rule: dict[str, Any]) -> None:
    rid = rule.get("id", "<unknown>")
    keys = rule.get("keys")
    if not isinstance(keys, list) or len(keys) < 2:
        raise RulePackError(
            f"Rule {rid} (matrix_lookup) must include a 'keys' list with at least 2 entries"
        )
    for i, key_spec in enumerate(keys):
        if isinstance(key_spec, str) and key_spec.strip():
            continue
        if (
            isinstance(key_spec, dict)
            and set(key_spec.keys()) == {"ref"}
            and isinstance(key_spec.get("ref"), str)
            and key_spec["ref"].strip()
        ):
            continue
        raise RulePackError(
            f"Rule {rid} (matrix_lookup) keys[{i}] must be a reference string "
            f"or a {{ref: ...}} mapping"
        )
    table = rule.get("table")
    if not isinstance(table, dict) or not table:
        raise RulePackError(f"Rule {rid} (matrix_lookup) must include non-empty 'table'")
    _validate_matrix_table(rid, table, len(keys), ())


def _validate_formula_rule(rule: dict[str, Any]) -> None:
    rid = rule.get("id", "<unknown>")
    expr = rule.get("expression")
    inputs = rule.get("inputs")

    if not isinstance(expr, str) or not expr.strip():
        raise RulePackError(f"Rule {rid} (formula) must include non-empty 'expression'")
    if not isinstance(inputs, dict) or not inputs:
        raise RulePackError(f"Rule {rid} (formula) must include non-empty 'inputs'")

    expr = expr.strip()

    for ch in expr:
        if ch not in _ALLOWED_EXPR_CHARS:
            raise RulePackError(f"Rule {rid} (formula) has invalid character: {ch!r}")

    if re.search(r"\b(?:min|max)\(\s*\)", expr):
        raise RulePackError(f"Rule {rid} (formula) calls min()/max() with no arguments")

    idents = {i for i in _extract_identifiers(expr) if i}
    declared = set(inputs.keys())
    idents = {i for i in idents if i not in _ALLOWED_FUNCS}

    # Input names must be plain identifiers: a name like "2000" would
    # silently shadow the numeric literal 2000 in the expression while the
    # trace still displays the literal, misrepresenting the actual math.
    bad_names = sorted(
        str(name)
        for name in declared
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(name))
    )
    if bad_names:
        raise RulePackError(
            f"Rule {rid} (formula) has invalid input names {bad_names}; "
            "input names must be identifiers not starting with a digit"
        )

    unknown = sorted(i for i in idents if i not in declared)
    if unknown:
        raise RulePackError(
            f"Rule {rid} (formula) references unknown identifiers {unknown}. "
            f"Declare them under inputs: {sorted(declared)}"
        )


@dataclass(frozen=True)
class RulePack:
    """Immutable, validated rule pack."""

    pack_dir: Path
    version: str
    tax_year: int
    jurisdiction: str
    id_prefix: str
    checksum: str
    constants: dict[str, Any]
    rules: dict[str, dict[str, Any]]
    rule_order: list[str]

    @classmethod
    def load(cls, pack_dir: Path) -> RulePack:
        pack_dir = pack_dir.resolve()
        manifest_path = _resolve_pack_file(pack_dir, "manifest.yaml", "manifest")
        rules_path = _resolve_pack_file(pack_dir, "rules.yaml", "rules")

        manifest = _read_yaml(manifest_path)
        rules_yaml = _read_yaml(rules_path)

        version = normalize_rule_pack_version(manifest.get("version", ""))
        tax_year = int(manifest.get("tax_year", 0))
        jurisdiction = str(manifest.get("jurisdiction", "")).strip()

        if tax_year <= 0:
            raise RulePackError("manifest.yaml must include a positive 'tax_year'")
        if not jurisdiction:
            raise RulePackError("manifest.yaml must include non-empty 'jurisdiction'")

        id_prefix = _jurisdiction_prefix(jurisdiction)

        constants = rules_yaml.get("constants", {}) or {}
        if not isinstance(constants, dict):
            raise RulePackError("rules.yaml 'constants' must be a mapping")

        rule_list = rules_yaml.get("rules", []) or []
        if not isinstance(rule_list, list):
            raise RulePackError("rules.yaml 'rules' must be a list")

        rules: dict[str, dict[str, Any]] = {}
        for r in rule_list:
            if not isinstance(r, dict):
                raise RulePackError("Each rule must be a mapping")

            rid = r.get("id")
            rtype = r.get("type")

            if not isinstance(rid, str) or not rid:
                raise RulePackError("Each rule must have a non-empty string 'id'")
            if not _RULE_ID_CHARSET_RE.fullmatch(rid):
                raise RulePackError(
                    f"Rule id {rid!r} contains unsupported characters "
                    f"(allowed: letters, digits, '_', '.', '-')"
                )
            if not rid.startswith(id_prefix):
                raise RulePackError(
                    f"Rule id {rid!r} does not match jurisdiction prefix {id_prefix!r} "
                    f"for {jurisdiction!r}"
                )
            if rid in rules:
                raise RulePackError(f"Duplicate rule id: {rid}")
            if rtype not in {"sum", "formula", "lookup", "bracket_table", "matrix_lookup"}:
                raise RulePackError(f"Unsupported rule type for {rid}: {rtype}")
            if not isinstance(r.get("description", ""), str):
                raise RulePackError(f"Rule {rid} description must be a string")
            rounding = r.get("rounding", "ROUND_HALF_UP")
            if rounding not in _ALLOWED_ROUNDING_MODES:
                raise RulePackError(
                    f"Rule {rid} has unsupported rounding mode {rounding!r} "
                    f"(allowed: {sorted(_ALLOWED_ROUNDING_MODES)})"
                )

            # Type-specific validation for early failure (startup time)
            if rtype == "formula":
                _validate_formula_rule(r)
            elif rtype == "sum":
                _validate_sum_rule(r)
            elif rtype == "lookup":
                _validate_lookup_rule(r)
            elif rtype == "bracket_table":
                _validate_bracket_table_rule(r)
            elif rtype == "matrix_lookup":
                _validate_matrix_lookup_rule(r)

            rules[rid] = r

        deps = _build_rule_deps(rules, id_prefix)
        _validate_deps(rules, deps)
        rule_order = _toposort_rules(rules, deps)

        checksum = _sha256_files(pack_dir.glob("*.yaml"))
        return cls(
            pack_dir=pack_dir,
            version=version,
            tax_year=tax_year,
            jurisdiction=jurisdiction,
            id_prefix=id_prefix,
            checksum=checksum,
            constants=constants,
            rules=rules,
            rule_order=rule_order,
        )

    def get_constant(self, path: str, key: str | None = None) -> Any:
        """Resolve a dotted constant path like 'constants.standard_deduction'.

        If key is provided, index into the resulting mapping.
        """
        if not isinstance(path, str) or not path:
            raise RulePackError("Constant path must be a non-empty string")

        parts = path.split(".")
        if parts and parts[0] == "constants":
            parts = parts[1:]

        val: Any = self.constants
        for part in parts:
            if not isinstance(val, dict) or part not in val:
                raise RulePackError(f"Unknown constant path: {path}")
            val = val[part]

        if key is not None:
            if not isinstance(val, dict) or key not in val:
                raise RulePackError(f"Unknown constant key '{key}' for {path}")
            return val[key]

        return val
