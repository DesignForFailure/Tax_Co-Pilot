<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `GET /whatif`, `POST /whatif`: What-if scenario comparison page using `WhatIfEngine` (MFJ vs MFS); shows diffs table, recommendation, and savings amount.
- `GET /import-csv`, `POST /import-csv`: CSV import page with textarea input and record-type dropdown (W-2, 1099-B, 1099-INT, 1099-DIV); displays per-line parse errors and parsed record table.
- `GET /runs/{run_id}/export/json`, `GET /runs/{run_id}/export/html`: Downloadable audit export endpoints using `generate_audit_html()` from `audit_export.py`.
- `POST /runs/{run_id}/delete`: Run deletion endpoint with CSRF protection; redirects to `/runs` on success.
- `GET /runs/compare?a={id}&b={id}`: Side-by-side run comparison view showing output diffs and delta for all `ReturnOutput` fields.
- `delete_return_run(run_id)` added to `app/services/database.py` (parameterized DELETE, hybrid_factory compatible).
- Extended `app/services/csv_import.py` with `1099-INT` and `1099-DIV` record type support following existing W-2/1099-B patterns.
- Nav links for What-If and Import CSV added to `app/templates/layouts/base.html`.
- Export JSON / Export HTML buttons added to `app/templates/pages/dashboard.html`.
- Delete buttons (with confirmation dialog) and comparison checkboxes added to `app/templates/pages/runs.html`; `past_runs` route now passes CSRF token to the template.
- New templates: `app/templates/pages/whatif.html`, `app/templates/pages/import_csv.html`, `app/templates/pages/run_compare.html`.
- `ReturnRun` moved to top-level import in `main.py`; `WhatIfEngine`, `generate_audit_html`, `import_csv`, `delete_return_run` imports added.
- New test file `tests/test_milestone6_routes.py`: 22 route integration tests covering all Milestone 6 features.


- Full third-party license audit and NOTICE file (`docs/NOTICE.md`) with copyright notices for all production dependencies.
- Legal notices page in the web UI (`/legal` route, `app/templates/pages/legal.html`) with SQLCipher BSD-3-Clause attribution, dependency table, and disclaimers.
- Footer attribution bar in `app/templates/layouts/base.html` with license, SQLCipher credit, and link to legal notices page.
- Export control notice (`docs/EXPORT_CONTROL.md`) with ECCN classification, TSU exception details, and BIS notification template.
- Data privacy and liability disclaimer (`docs/DISCLAIMER.md`) tailored for local-first tax software.
- Legal & Acknowledgments section in `README.md` and `README.txt` crediting the encryption engine and key frameworks.
- Established project-level release documentation with a formal changelog.
- Added a public roadmap focused on federal completeness, state expansion, forms support, and security hardening.
- Added an explicit alpha support policy and versioning approach in the README.
- Database encryption at rest using SQLCipher (AES-256) with Python/Fernet fallback (`app/services/encryption.py`, `app/config.py`).
- Password-protected database with PBKDF2-HMAC-SHA256 key derivation (100,000+ iterations).
- Database unlock UI page (`app/templates/pages/unlock.html`).
- Encryption setup and usage guide (`docs/ENCRYPTION.md`).
- GitHub Actions CI pipeline (`.github/workflows/ci.yml`) running ruff, mypy, pytest, and pip-audit.
- Input validation for required trimmed first/last names on calculation submit.
- What-if scenario analysis engine (`app/engine/whatif.py`).
- Test suite for encryption (`tests/test_encryption.py`, `tests/test_encrypted_database.py`).
- Test for taxpayer name validation (`tests/test_calculate_name_validation.py`).
- Test for `_resolve_ref` edge cases (`tests/test_calculator_resolve_ref.py`).
- Test for UTF-8 encoding integrity (`tests/test_encoding_guard.py`).

### Changed
- Tightened AI agent governance docs (`AGENTS.md`, `.agent_tools/*`) with stricter MUST-level routing, formatting, append-only log protocol, and explicit validation reporting rules.
- Added a README tree mapping rule so agents use the documented repository structure first and must update the tree when structure changes.
- License changed from MIT to **GNU AGPL v3**; AGPL headers added to all source files.
- Restructured tests from project root into `tests/` directory.
- Moved `whatif.py` into `app/engine/`.
- Updated `pyproject.toml` license classifier from MIT to AGPL-3.0-or-later.
- Hardened `_resolve_ref` handling for missing or invalid string references.

### Fixed
- SQLCipher cursor compatibility via hybrid row factory supporting both index and key access.
- SQLCipher backup-path handling in encryption service corrected to append suffix safely.
- Ruff UP035 typing import warnings resolved in encryption service.
- Mypy `no-any-return` error resolved in security headers middleware.
- Additional MyPy type fixes across `app/main.py`, `tests/test_golden2.py`, and related modules.
- UTF-8 encoding issues in calculation outputs.

## [0.1.0-alpha.1] - 2026-02-15

### Added
- Initial MVP architecture for local-first, privacy-preserving tax computation.
- Deterministic rules engine with versioned rule packs for federal and state modules.
- Local web UI with calculation flow and run history views.
- Golden tests and baseline federal/state rule pack stubs.

### Notes
- This is an alpha/MVP release. Breaking changes are expected while core data models, rules, and APIs stabilize.
