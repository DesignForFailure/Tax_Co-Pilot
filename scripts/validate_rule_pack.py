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
