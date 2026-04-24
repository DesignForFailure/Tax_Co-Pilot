# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule-pack cache helpers shared by route modules."""

from __future__ import annotations

from pathlib import Path

from app.engine.rule_loader import RulePack

BASE_DIR = Path(__file__).resolve().parents[2]
FEDERAL_PACKS_DIR = BASE_DIR / "rule_packs" / "federal"
STATE_PACKS_DIR = BASE_DIR / "rule_packs" / "state"

federal_cache: dict[int, RulePack] = {}
state_cache: dict[int, dict[str, RulePack]] = {}


def bust_pack_cache(jurisdiction: str, year: int) -> None:
    """Remove cached packs so the next load reads from disk."""
    normalized = jurisdiction.lower()
    if normalized in {"federal", "fed"}:
        federal_cache.pop(year, None)
    else:
        state_cache.pop(year, None)


def discover_available_years() -> list[int]:
    """Scan rule_packs/federal for available tax years."""
    years: list[int] = []
    if not FEDERAL_PACKS_DIR.exists():
        return years
    for year_dir in sorted(FEDERAL_PACKS_DIR.iterdir()):
        if year_dir.is_dir() and year_dir.name.isdigit():
            years.append(int(year_dir.name))
    return years


def get_federal_pack(year: int) -> RulePack:
    """Load and cache a federal rule pack for the given year."""
    if year not in federal_cache:
        federal_cache[year] = RulePack.load(FEDERAL_PACKS_DIR / str(year))
    return federal_cache[year]


def get_state_packs(year: int) -> dict[str, RulePack]:
    """Load and cache all state rule packs for the given year."""
    if year not in state_cache:
        packs: dict[str, RulePack] = {}
        if STATE_PACKS_DIR.exists():
            for state_dir in sorted(STATE_PACKS_DIR.iterdir()):
                if not state_dir.is_dir() or state_dir.name.startswith("_"):
                    continue
                year_dir = state_dir / str(year)
                if year_dir.exists():
                    packs[state_dir.name.upper()] = RulePack.load(year_dir)
        state_cache[year] = packs
    return state_cache[year]


available_years = discover_available_years()


def available_states_by_year(years: list[int] | None = None) -> dict[int, list[str]]:
    """Return a deterministic list of state packs for each available year."""
    target_years = years if years is not None else available_years
    return {year: sorted(get_state_packs(year).keys()) for year in target_years}


def warm_caches() -> None:
    """Pre-load all discovered federal and state packs."""
    for year in available_years:
        get_federal_pack(year)
        get_state_packs(year)

