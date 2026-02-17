<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 03 Testing Rules (Strict)

## Definition of Done (Mandatory)
A task is complete only after these commands are run and passing:

1. `ruff check .`
2. `mypy .`
3. `pytest`

## Required Reporting
- Agent final output **MUST** list each command actually run and whether it passed/failed.
- If any command cannot run due to environment limitations, report that explicitly with reason.
- If failures are pre-existing and unrelated, identify them clearly and avoid masking them.

## Merge Safety
Do not submit changes that introduce new lint, typing, or test failures.
