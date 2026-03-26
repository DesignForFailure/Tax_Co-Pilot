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

"""Rule pack editor service — CRUD operations for rule packs.

All file I/O for rule pack management goes through this module.
The engine's rule_loader.py stays purely for loading/validation.
"""

from __future__ import annotations

import re
import shutil
import tempfile
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
_DEFAULT_CUSTOM_PACK_VERSION = "0.1.0"


def _validate_custom_name(name: str) -> None:
    """Reject empty or control-character-containing custom names."""
    stripped = name.strip()
    if not stripped:
        raise ValueError("Custom name must not be empty")
    if any(ord(c) < 32 for c in stripped):
        raise ValueError("Custom name must not contain control characters")
    if len(stripped) > 100:
        raise ValueError("Custom name too long (max 100 characters)")


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

    if not _JURISDICTION_RE.match(jurisdiction):
        raise ValueError(f"Invalid jurisdiction: {jurisdiction!r}")
    if variant != "standard" and not _VARIANT_RE.match(variant):
        raise ValueError(f"Invalid variant: {variant!r}")

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
    manifest_path: Path | None = year_dir / "manifest.yaml"
    if not manifest_path.exists():  # type: ignore[union-attr]
        candidates = sorted(year_dir.glob("*_manifest.yaml"), key=lambda p: p.name)
        manifest_path = candidates[0] if len(candidates) == 1 else None

    if manifest_path is not None and manifest_path.exists():
        try:
            manifest = _read_yaml(manifest_path)
            rules_path: Path | None = year_dir / "rules.yaml"
            if not rules_path.exists():  # type: ignore[union-attr]
                candidates2 = [
                    c
                    for c in sorted(year_dir.glob("*_rules.yaml"), key=lambda p: p.name)
                    if "manifest" not in c.name
                ]
                rules_path = candidates2[0] if len(candidates2) == 1 else None
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
        candidates2 = [c for c in pack_dir.glob("*rules*.yaml") if "manifest" not in c.name]
        if candidates2:
            rules_path = candidates2[0]
    if not manifest_path.exists():
        raise ValueError(f"Manifest file not found in {pack_dir}")
    if not rules_path.exists():
        raise ValueError(f"Rules file not found in {pack_dir}")
    return manifest_path.read_bytes(), rules_path.read_bytes()


def _next_custom_variant_number(pack_parent_dir: Path) -> int:
    """Find the next available custom_vN suffix in a year directory."""
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
    _validate_custom_name(custom_name)
    source_dir = _pack_path(jurisdiction, year, source_variant, base_dir=base_dir)
    if not source_dir.exists():
        raise ValueError(f"Source pack not found: {source_dir}")
    source_pack = RulePack.load(source_dir)

    # Determine parent dir (the year directory) for variant scanning.
    parent_dir = source_dir if source_variant == "standard" else source_dir.parent
    variant_number = _next_custom_variant_number(parent_dir)
    variant = f"custom_v{variant_number}"

    target_dir = parent_dir / variant
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ValueError(
            "A custom pack is being created concurrently; please try again."
        ) from None

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
        version=source_pack.version,
        custom_name=custom_name,
        rule_count=rule_count,
    )


def create_empty_pack(
    jurisdiction: str, year: int, custom_name: str, *, base_dir: Path | None = None
) -> PackInfo:
    """Create a new custom pack with an empty rule list."""
    _validate_custom_name(custom_name)
    parent_dir = _pack_path(jurisdiction, year, "standard", base_dir=base_dir)
    if not parent_dir.exists():
        parent_dir.mkdir(parents=True, exist_ok=True)

    variant_number = _next_custom_variant_number(parent_dir)
    variant = f"custom_v{variant_number}"
    target_dir = parent_dir / variant
    try:
        target_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ValueError(
            "A custom pack is being created concurrently; please try again."
        ) from None

    j_lower = jurisdiction.lower()
    manifest: dict[str, Any] = {
        "version": _DEFAULT_CUSTOM_PACK_VERSION,
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
        version=_DEFAULT_CUSTOM_PACK_VERSION,
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
    rule_list: list[dict[str, Any]] = rules_yaml.get("rules", []) or []

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
    rule_list: list[dict[str, Any]] = rules_yaml.get("rules", []) or []

    filtered = [r for r in rule_list if r.get("id") != rule_id]
    if len(filtered) == len(rule_list):
        raise ValueError(f"Rule {rule_id!r} not found in pack")
    rules_yaml["rules"] = filtered
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
    _validate_custom_name(custom_name)
    manifest: Any = yaml.safe_load(manifest_bytes)
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

    variant_number = _next_custom_variant_number(parent_dir)
    variant = f"custom_v{variant_number}"
    target_dir = parent_dir / variant
    target_dir.mkdir(parents=True, exist_ok=False)

    # Write files
    manifest["custom"] = True
    manifest["custom_name"] = custom_name
    _atomic_write_yaml(target_dir / "manifest.yaml", manifest)
    (target_dir / "rules.yaml").write_bytes(rules_bytes)

    # Validate — if invalid, clean up
    try:
        pack = RulePack.load(target_dir)
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
        version=pack.version,
        custom_name=custom_name,
        rule_count=rule_count,
    )


__all__ = [
    "PackInfo",
    "list_all_packs",
    "load_pack_detail",
    "validate_pack",
    "export_yaml",
    "clone_pack",
    "create_empty_pack",
    "save_rule",
    "delete_rule",
    "delete_pack",
    "import_yaml",
    "_pack_path",
    "_validate_path_param",
]
