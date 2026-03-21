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
- [2026-02-18] docs/NOTICE.md, docs/EXPORT_CONTROL.md, docs/DISCLAIMER.md, app/templates/pages/legal.html, app/templates/layouts/base.html, main.py, README.md, README.txt, CHANGELOG.md: Full license audit and attribution generation — added NOTICE with all third-party copyright/license texts, legal notices UI page with /legal route, footer attribution bar, ECCN/TSU export control notice, local-first data disclaimer, and Legal & Acknowledgments sections in README files.
- [2026-03-15] main.py, app/services/database.py, app/services/csv_import.py, app/templates/layouts/base.html, app/templates/pages/runs.html, app/templates/pages/dashboard.html, app/templates/pages/whatif.html, app/templates/pages/import_csv.html, app/templates/pages/run_compare.html, tests/test_milestone6_routes.py, README.md, CHANGELOG.md: Milestone 6 — wired whatif engine (/whatif GET/POST), CSV import (/import-csv GET/POST, added 1099-INT/1099-DIV support), audit export (/runs/{id}/export/json|html), run deletion (/runs/{id}/delete with CSRF), run comparison (/runs/compare); 22 new route integration tests; nav links and export/delete/compare UI added.
- [2026-03-18] app/models/forms.py, app/services/form_mapper.py, app/models/domain.py, app/engine/calculator.py, rule_packs/federal/2024/federal_2024_rules.yaml, main.py, app/templates/pages/calculate.html, app/templates/pages/forms_view.html, app/templates/pages/dashboard.html, tests/test_forms.py, tests/test_golden.py, tests/test_golden2.py, README.md, CHANGELOG.md: Milestone 3 — form data models (Form1040Lines/Schedule1Lines/FormPacket), form mapper with consistency checks, estimated_tax_payments/total_payments rules, form_line on TraceNode, adjustments/estimated payments on calculate form, /runs/{id}/forms view and /export/forms routes.
- [2026-03-21] rule_packs/federal/2023/federal_2023_manifest.yaml, rule_packs/federal/2023/federal_2023_rules.yaml, rule_packs/state/GA/2023/state_GA_2023_manifest.yaml, rule_packs/state/GA/2023/state_GA_2023_rules.yaml, main.py, app/engine/calculator.py, app/templates/pages/calculate.html, tests/test_multi_year.py, tests/test_state_expansion.py, README.md, CHANGELOG.md: Milestone 9 — 2023 federal rule pack (different brackets/deductions/limits), 2023 GA state pack (graduated brackets), dynamic year-aware rule pack loading with caching, tax year dropdown on calculate form, year-dynamic output mapping in calculator.
