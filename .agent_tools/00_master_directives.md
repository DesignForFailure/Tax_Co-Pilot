<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# 00 Master Directives (Strict)

## Purpose
These are repository-wide, non-negotiable directives for all AI Agent work.

## Do-Not-Break Rules
1. **SQLCipher row compatibility is mandatory.**
   - Use and preserve `hybrid_factory` behavior.
   - DB changes **MUST** preserve both `row[0]` and `row["field"]` access.
2. **Strict typing is mandatory.**
   - New/modified Python code **MUST** satisfy MyPy checks.
   - Do not introduce avoidable `Any` types.
3. **License compliance is mandatory.**
   - Do not remove existing GPL/AGPL/SPDX headers.
   - Add SPDX headers/comments to new source/docs when applicable.
4. **Validation evidence is mandatory.**
   - Final task output **MUST** include executed quality-check commands and results.

## Conflict Handling
If a request conflicts with these directives, the agent must provide the safest compliant alternative and not bypass the directive.
