"""Load and parse YAML rule packs."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml


class RulePack:
    """Loaded, versioned rule pack."""

    def __init__(self, pack_dir: Path):
        self.pack_dir = pack_dir
        self.manifest = self._load_yaml(pack_dir / "manifest.yaml")
        self.rules_raw = self._load_yaml(pack_dir / "rules.yaml")
        self.version = self.manifest["version"]
        self.tax_year = self.manifest["tax_year"]
        self.checksum = self._compute_checksum()

        # Parse into lookup structures
        self.constants: dict[str, Any] = self.rules_raw.get("constants", {})
        self.rules: dict[str, dict] = {}
        for rule in self.rules_raw.get("rules", []):
            self.rules[rule["id"]] = rule

    def _load_yaml(self, path: Path) -> dict:
        with open(path) as f:
            return yaml.safe_load(f)

    def _compute_checksum(self) -> str:
        h = hashlib.sha256()
        for p in sorted(self.pack_dir.glob("*.yaml")):
            h.update(p.read_bytes())
        return h.hexdigest()

    def get_constant(self, path: str, key: str | None = None) -> Any:
        """Resolve a dotted constant path like 'standard_deduction'.
        If key is provided, index into the resulting dict."""
        parts = path.replace("constants.", "").split(".")
        val = self.constants
        for part in parts:
            val = val[part]
        if key and isinstance(val, dict):
            val = val[key]
        return val
