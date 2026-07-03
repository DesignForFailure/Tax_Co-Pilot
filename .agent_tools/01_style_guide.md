<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# 01 Style Guide (Strict)

## Mandatory Header Pattern (Python)
For new Python modules, use this top-of-file order:
1. SPDX license identifier comment.
2. Module docstring.
3. Imports grouped as stdlib, third-party, local.

Example:
```python
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Module purpose and boundaries."""

from __future__ import annotations
```

## Import Rules
- Prefer abstract types from `collections.abc` over `typing` aliases when applicable.
- Keep imports explicit, minimal, and sorted.
- Never wrap imports in `try`/`except` blocks.

## Comment Rules
- Comments must explain **why** a choice exists, not restate **what** code already expresses.
- Remove or update stale comments in the same change where code behavior changes.
- Avoid placeholder comments (`TODO` without owner/date/context).
