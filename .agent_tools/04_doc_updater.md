<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# 04 Documentation Updater (Strict)

## README.md Update Rules
When structure/workflows change, update README in the same task:
- File tree snippets must match current repository layout.
- Setup/run commands must be executable as documented.
- Architecture/security notes must reflect current behavior.

## CHANGELOG.md Update Rules
- Record notable changes under `## [Unreleased]`.
- Use clear bullets under `### Added`, `### Changed`, `### Fixed`.
- Include impacted component/file context where useful.

## Consistency Rule
Documentation and code must not drift; update docs in the same change whenever feasible.


## Repository Tree Mapping
- Treat the `README.md` repository tree as the canonical high-level structure map before manual traversal.
- If files/directories are added, moved, renamed, or deleted, update the README tree in the same task.
