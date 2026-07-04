# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reference catalogs for rule authoring.

Feeds both the rule editor's autocomplete datalists and the AI authoring
prompt with the references a rule can legally use: the engine's ``input.*``
namespace (derived live from the calculator so it cannot drift), per-state
engine inputs, and dotted ``constants.*`` paths for a pack's constants.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.engine.calculator import known_input_refs

# Key-only pseudo-reference: usable as a lookup/bracket key or matrix key,
# never as a numeric input to a formula or sum.
FILING_STATUS_KEY_REF = "input.filing_status"

# Engine inputs added per state at calculation time ({ST} = uppercase code).
_STATE_INPUT_PATTERNS = (
    "input.withholding.state.{ST}",
    "input.state.is_resident.{ST}",
    "input.state.apportionment.{ST}",
)

# Multi-state aggregates, populated only for the residence pack's run.
_STATE_GLOBAL_REFS = (
    "input.state.other_state_tax",
    "input.state.other_state_ratio",
)

_FEDERAL_ALIASES = {"federal", "fed", "us", "usa"}


def input_ref_options(jurisdiction: str) -> list[str]:
    """All ``input.*`` references a pack for this jurisdiction can use."""
    refs = list(known_input_refs())
    if jurisdiction.lower() not in _FEDERAL_ALIASES:
        state = jurisdiction.upper()
        refs.extend(pattern.format(ST=state) for pattern in _STATE_INPUT_PATTERNS)
        refs.extend(_STATE_GLOBAL_REFS)
    return sorted(set(refs))


def constants_table_paths(constants: Mapping[str, Any]) -> list[str]:
    """Dotted ``constants.*`` paths addressable by lookup ``table:`` fields.

    A constant whose values are all sub-mappings is addressed per sub-table
    (``constants.name.group``); everything else is addressed whole.
    """
    paths: list[str] = []
    for name, value in constants.items():
        if isinstance(value, dict) and value and all(
            isinstance(child, dict) for child in value.values()
        ):
            paths.extend(f"constants.{name}.{group}" for group in value)
        else:
            paths.append(f"constants.{name}")
    return sorted(paths)
