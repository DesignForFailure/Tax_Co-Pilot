<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->

<div align="center">

```
 ___________              _____            ______ _ __      __
/_  __/ __  \__  __      / ___/___        / __ (_) / ___  / /_
 / / / /_/ / / / /___  / /   / __ \___  / /_/ / / / __ \/ __/
/ / / __  / /_/ /___/ / /___/ /_/ /___/ / ____/ / / /_/ / /_
/_/ /_/ /_/\__,_/      \____/\____/     /_/   /_/_/\____/\__/
```

**Local-first, privacy-preserving personal tax software**

[![CI](https://github.com/DesignForFailure/Tax_Co-Pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/DesignForFailure/Tax_Co-Pilot/actions/workflows/ci.yml)
[![License: AGPL-3.0](https://img.shields.io/badge/License-AGPL--3.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB.svg)](https://python.org)
[![Status: Alpha](https://img.shields.io/badge/Status-Alpha-orange.svg)](#project-status)

An engineering-focused system for modeling tax rules, storing tax-relevant data, and deterministically calculating outcomes using transparent, verifiable logic.

**This is not tax advice software.**

[Getting Started](#getting-started) · [Architecture](#architecture) · [Documentation](#documentation) · [Contributing](CONTRIBUTING.md)

</div>

---

## Why Tax Co-Pilot?

Most consumer tax software hides its logic, can't reproduce historical results, and stores your data in the cloud. Tax Co-Pilot takes the opposite approach:

| | Traditional Tax Software | Tax Co-Pilot |
|---|---|---|
| **Calculation logic** | Hidden / proprietary | Open, versioned YAML rule packs |
| **Reproducibility** | Results change silently | Immutable runs with full audit trace |
| **Data storage** | Cloud-based, opaque | Local SQLite, optional AES-256 encryption |
| **Traceability** | Inputs and outputs blended | Every number traceable to its source |

---

## Key Features

- **Rules-as-Data** — Tax logic lives in versioned YAML rule packs, not application code. Past results never silently change.
- **Full Audit Trace** — Every calculation produces rule ID, inputs, intermediates, rounding policy, and human-readable explanation.
- **Local-First & Private** — Runs entirely on local hardware. Optional AES-256 encryption at rest via SQLCipher.
- **Multi-Person & Multi-State** — Two-taxpayer filing support (MFJ/MFS) with multiple state jurisdiction modeling.
- **What-If Engine** — Scenario comparison (e.g., MFJ vs MFS) with compliance-first optimization.
- **Integrity Verification** — SHA-256 hash chain over immutable run artifacts with tamper detection.

---

## Getting Started

### Prerequisites

- Python 3.11+
- pip

### Install

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Optional: dev tooling (ruff, mypy, pip-audit)
python -m pip install -r requirements-dev.txt
```

### Run

```bash
./run.sh
# or: python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** in your browser.

### Test

```bash
pytest -q
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Browser (Server-rendered HTML / Jinja2)        │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│  main.py — FastAPI routes, forms, CSRF, export  │
└──┬──────────────────────────────┬───────────────┘
   │                              │
┌──▼──────────────┐   ┌──────────▼──────────────┐
│  app/engine/    │   │  app/services/          │
│  Calculator     │   │  Database (SQLite/WAL)  │
│  RuleLoader     │   │  Encryption (SQLCipher) │
│  WhatIfEngine   │   │  CSV Import / Export    │
└──┬──────────────┘   └─────────────────────────┘
   │
┌──▼──────────────────────────────────────────────┐
│  rule_packs/ — Versioned YAML (federal + state) │
└─────────────────────────────────────────────────┘
```

### Layer Separation

| Layer | Path | Responsibility |
|---|---|---|
| **Engine** | `app/engine/` | Tax computation only. No persistence, no I/O. Decimal math throughout. |
| **Services** | `app/services/` | Persistence, encryption, adapters. No tax/business logic. |
| **Models** | `app/models/` | Pydantic domain models (FilingStatus, W2Data, ReturnRun, TraceNode, etc.) |
| **Web** | `main.py` | FastAPI routes, form parsing, CSRF, security headers. |
| **Rule Packs** | `rule_packs/` | Versioned YAML rule definitions and manifests per jurisdiction/year. |

### Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.11+ |
| Backend | FastAPI + Uvicorn |
| Database | SQLite (WAL mode) + optional SQLCipher (AES-256) |
| UI | Server-rendered Jinja2 templates |
| Numeric Type | `Decimal` (never `float`) |
| Rule Packs | Versioned YAML |
| CI | GitHub Actions (ruff, mypy, pytest, pip-audit) |

---

## Project Status

Tax Co-Pilot is currently **alpha / MVP**.

### Current Scope

- Tax years 2023 and 2024 with federal 1040-style calculations
- W-2, 1099-INT, 1099-DIV, 1099-B income support
- Withholding and estimated payments
- Two-person filing (MFJ / MFS / Single / HoH / QSS)
- 12 state packs (GA, CA, NY + 9 no-income-tax states)
- What-if scenario comparison engine
- Local web UI with full calculation trace
- JSON and HTML audit export

### Versioning

This project follows [Semantic Versioning](https://semver.org/). During alpha, releases use `0.y.z`. Breaking changes are expected. A stable compatibility promise begins at `1.0.0`.

---

## Documentation

### Guides

| | Document | Description |
|---|---|---|
| :lock: | [Encryption Guide](docs/ENCRYPTION.md) | Setup, configuration, and password management for AES-256 database encryption |
| :book: | [Rule Pack Authoring](docs/RULE_PACK_AUTHORING.md) | How to write rule packs — rule types, expressions, constants, and worked examples |
| :us: | [State Authoring Guide](docs/STATE_AUTHORING_GUIDE.md) | Adding a new state tax jurisdiction from template to tests |

### Project

| | Document | Description |
|---|---|---|
| :dart: | [Roadmap](ROADMAP.md) | Milestones, planned features, and implementation prompts |
| :scroll: | [Changelog](CHANGELOG.md) | Release notes and change history |
| :handshake: | [Contributing](CONTRIBUTING.md) | Development setup, quality checks, and PR expectations |
| :shield: | [Security Policy](SECURITY.md) | Vulnerability reporting and disclosure process |

### Legal

| | Document | Description |
|---|---|---|
| :page_facing_up: | [Notice (Third-Party)](docs/NOTICE.md) | Full attribution for all third-party dependencies |
| :globe_with_meridians: | [Export Control](docs/EXPORT_CONTROL.md) | Cryptographic export control notice (EAR/TSU) |
| :warning: | [Disclaimer](docs/DISCLAIMER.md) | Warranty disclaimer and user responsibilities |

---

## Actual Current Repository Structure

```text
Tax_Co-Pilot/
├── .agent_tools/
│   ├── 00_master_directives.md
│   ├── 01_style_guide.md
│   ├── 02_architecture.md
│   ├── 03_testing_rules.md
│   ├── 04_doc_updater.md
│   └── 05_session_log.md
├── .editorconfig
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.md
│   │   ├── custom.md
│   │   ├── feature_request.md
│   │   └── new_state.md
│   ├── PULL_REQUEST_TEMPLATE.md
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── .pre-commit-config.yaml
├── AGENTS.md
├── CLAUDE.md
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── calculator.py
│   │   ├── rule_loader.py
│   │   └── whatif.py
│   ├── models/
│   │   ├── __init__.py
│   │   ├── domain.py
│   │   └── forms.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── audit_export.py
│   │   ├── csv_import.py
│   │   ├── database.py
│   │   ├── encryption.py
│   │   ├── form_mapper.py
│   │   └── rule_pack_editor.py
│   └── templates/
│       ├── layouts/
│       │   └── base.html
│       └── pages/
│           ├── calculate.html
│           ├── dashboard.html
│           ├── forms_view.html
│           ├── import_csv.html
│           ├── legal.html
│           ├── rotate_key.html
│           ├── rule_editor.html
│           ├── rule_pack_detail.html
│           ├── rule_pack_import.html
│           ├── rule_packs.html
│           ├── run_compare.html
│           ├── runs.html
│           ├── unlock.html
│           └── whatif.html
├── docs/
│   ├── DISCLAIMER.md
│   ├── ENCRYPTION.md
│   ├── EXPORT_CONTROL.md
│   ├── NOTICE.md
│   ├── RULE_PACK_AUTHORING.md
│   ├── STATE_AUTHORING_GUIDE.md
│   └── superpowers/
│       ├── plans/
│       │   ├── 2026-03-15-federal-completeness.md
│       │   ├── 2026-03-16-state-expansion.md
│       │   ├── 2026-03-18-forms-support.md
│       │   ├── 2026-03-18-multi-year-support.md
│       │   ├── 2026-03-18-qa-remediation.md
│       │   ├── 2026-03-21-ca-ny-state-packs.md
│       │   ├── 2026-03-21-itemized-deductions-credits.md
│       │   ├── 2026-03-22-data-mgmt-dx.md
│       │   ├── 2026-03-22-hardening-qa.md
│       │   └── 2026-03-22-rule-pack-editor.md
│       └── specs/
│           ├── 2026-03-15-federal-completeness-design.md
│           ├── 2026-03-16-state-expansion-design.md
│           ├── 2026-03-22-hardening-qa-design.md
│           └── 2026-03-22-rule-pack-editor-design.md
├── scripts/
│   └── validate_rule_pack.py
├── rule_packs/
│   ├── federal/
│   │   ├── 2023/
│   │   │   ├── federal_2023_manifest.yaml
│   │   │   └── federal_2023_rules.yaml
│   │   └── 2024/
│   │       ├── federal_2024_manifest.yaml
│   │       └── federal_2024_rules.yaml
│   └── state/
│       ├── _template/
│       │   └── 2024/
│       │       ├── state_TEMPLATE_2024_manifest.yaml
│       │       └── state_TEMPLATE_2024_rules.yaml
│       ├── AK/
│       │   └── 2024/
│       │       ├── state_AK_2024_manifest.yaml
│       │       └── state_AK_2024_rules.yaml
│       ├── CA/
│       │   └── 2024/
│       │       ├── state_CA_2024_manifest.yaml
│       │       └── state_CA_2024_rules.yaml
│       ├── FL/
│       │   └── 2024/
│       │       ├── state_FL_2024_manifest.yaml
│       │       └── state_FL_2024_rules.yaml
│       ├── GA/
│       │   ├── 2023/
│       │   │   ├── state_GA_2023_manifest.yaml
│       │   │   └── state_GA_2023_rules.yaml
│       │   └── 2024/
│       │       ├── state_GA_2024_manifest.yaml
│       │       └── state_GA_2024_rules.yaml
│       ├── NH/
│       │   └── 2024/
│       │       ├── state_NH_2024_manifest.yaml
│       │       └── state_NH_2024_rules.yaml
│       ├── NV/
│       │   └── 2024/
│       │       ├── state_NV_2024_manifest.yaml
│       │       └── state_NV_2024_rules.yaml
│       ├── NY/
│       │   └── 2024/
│       │       ├── state_NY_2024_manifest.yaml
│       │       └── state_NY_2024_rules.yaml
│       ├── SD/
│       │   └── 2024/
│       │       ├── state_SD_2024_manifest.yaml
│       │       └── state_SD_2024_rules.yaml
│       ├── TN/
│       │   └── 2024/
│       │       ├── state_TN_2024_manifest.yaml
│       │       └── state_TN_2024_rules.yaml
│       ├── TX/
│       │   └── 2024/
│       │       ├── state_TX_2024_manifest.yaml
│       │       └── state_TX_2024_rules.yaml
│       ├── WA/
│       │   └── 2024/
│       │       ├── state_WA_2024_manifest.yaml
│       │       └── state_WA_2024_rules.yaml
│       └── WY/
│           └── 2024/
│               ├── state_WY_2024_manifest.yaml
│               └── state_WY_2024_rules.yaml
├── tests/
│   ├── __init__.py
│   ├── test_calculate_name_validation.py
│   ├── test_calculator_resolve_ref.py
│   ├── test_data_mgmt.py
│   ├── test_encoding_guard.py
│   ├── test_encrypted_database.py
│   ├── test_encryption.py
│   ├── test_error_paths.py
│   ├── test_forms.py
│   ├── test_golden.py
│   ├── test_golden2.py
│   ├── test_golden_m1.py
│   ├── test_hash_versioning.py
│   ├── test_itemized_credits.py
│   ├── test_milestone6_routes.py
│   ├── test_multi_year.py
│   ├── test_parse_money.py
│   ├── test_route_coverage.py
│   ├── test_rule_pack_editor.py
│   ├── test_rule_pack_routes.py
│   ├── test_state_ca_ny.py
│   └── test_state_expansion.py
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── README.txt
├── ROADMAP.md
├── SECURITY.md
├── main.py
├── pyproject.toml
├── requirements-dev.txt
├── requirements.txt
└── run.sh
```

---

## Legal & Acknowledgments

Tax Co-Pilot is licensed under the **GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [LICENSE](LICENSE) for the full text.

### Encryption Engine

Database encryption at rest is powered by **[SQLCipher](https://www.zetetic.net/sqlcipher/)** (AES-256), Copyright 2008-2024 Zetetic LLC, licensed under BSD-3-Clause. SQLCipher is built on [SQLite](https://www.sqlite.org/) (public domain).

The **[cryptography](https://github.com/pyca/cryptography)** library is used for legacy/compatibility encryption tooling (Apache-2.0 OR BSD-3-Clause), including **[OpenSSL](https://www.openssl.org/)** (Apache-2.0).

### Key Dependencies

| Library | License | Use |
|---|---|---|
| FastAPI | MIT | Web framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| Pydantic | MIT | Data validation |
| Jinja2 | BSD-3-Clause | Template engine |
| PyYAML | MIT | YAML rule pack parsing |
| python-multipart | Apache-2.0 | Form data parsing |
| pysqlcipher3 | zlib/libpng | SQLCipher Python binding |
| keyring | MIT | OS credential storage |

All third-party licenses are permissive and compatible with AGPL-3.0. Full attribution in [docs/NOTICE.md](docs/NOTICE.md).

### Export Control

This software contains cryptographic functionality (AES-256 via SQLCipher, PBKDF2-HMAC-SHA256). Distributed under the TSU exception (EAR 740.13(e)). See [docs/EXPORT_CONTROL.md](docs/EXPORT_CONTROL.md).

### Disclaimer

**This software is provided "as is", without warranty of any kind.** Tax Co-Pilot is not tax advice software. All data is stored locally on your device. You are solely responsible for your data, backups, and encryption passwords. See the [AGPL-3.0 license](LICENSE) sections 15-16 for the full warranty disclaimer.
