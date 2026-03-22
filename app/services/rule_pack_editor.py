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
    return manifest_path.read_bytes(), rules_path.read_bytes()


__all__ = [
    "PackInfo",
    "list_all_packs",
    "load_pack_detail",
    "validate_pack",
    "export_yaml",
    "_pack_path",
    "_validate_path_param",
]
