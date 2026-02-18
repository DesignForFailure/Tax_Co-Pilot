<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# Agent Session Log (Machine Readable)

> APPEND ONLY.
> Required format: `- [YYYY-MM-DD] {File Changed}: {Technical Summary}`
> Regex guide: `^- \[[0-9]{4}-[0-9]{2}-[0-9]{2}\] [^:]+: .+$`

## Rules
- Append new entries at EOF only.
- Do not edit, delete, or reorder existing entries.
- One completed task = one appended line.
- `File Changed` must name concrete file(s) or directory scope.
- `Technical Summary` must be concise and technical (no narrative fluff).

- [2026-02-16] app/services/encryption.py: Fixed SQLCipher compatibility by implementing `hybrid_factory`.
- [2026-02-16] app/services/encryption.py: Fixed `backup_path` logic to append suffix instead of replacing extension.
- [2026-02-16] app/services/encryption.py, app/main.py, tests/test_golden2.py: Resolved Ruff/MyPy typing issues and no-any-return violations.
- [2026-02-17] .agent_tools/*, AGENTS.md, CHANGELOG.md: Added agent toolkit directives and synchronized changelog/session records for SQLCipher and typing fixes.
- [2026-02-17] AGENTS.md, .agent_tools/*, CHANGELOG.md: Tightened agent directives, strict session-log protocol, and mandatory Ruff/MyPy/Pytest reporting requirements.
- [2026-02-17] AGENTS.md, .agent_tools/04_doc_updater.md, CHANGELOG.md: Added README tree mapping rule requiring agents to use and maintain README file structure tree on structural changes.
- [2026-02-17] tests/test_calculate_name_validation.py, tests/test_calculator_resolve_ref.py, tests/test_encoding_guard.py, app/engine/__init__.py, app/models/__init__.py, app/services/__init__.py, README.md, CHANGELOG.md, CONTRIBUTING.md, SECURITY.md, ROADMAP.md, docs/ENCRYPTION.md, CODE_OF_CONDUCT.md: Added missing module docstrings to three test files, corrected copy-pasted package docstrings in three __init__.py sub-packages, and added SPDX license headers to seven project markdown docs.
- [2026-02-18] app/templates/pages/calculate.html, main.py, app/templates/layouts/base.html, rule_packs/federal/2024/federal_2024_rules.yaml, tests/test_calculate_name_validation.py: Overhauled tax input form with dynamic multi-row W-2/1099-INT/1099-DIV/1099-B sections, spouse support for MFJ/MFS, HOH/QSS filing statuses; refactored calculate_submit to async with _parse_tax_input_from_form helper parsing indexed form fields into domain models; added HOH/QSS 2024 bracket tables to federal rules.
