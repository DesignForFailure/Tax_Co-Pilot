<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Tax_Co-Pilot

Tax_Co-Pilot is a **local-first, privacy-preserving personal tax software system** designed for auditability, reproducibility, and compliance.

This project is **not tax advice software**. It is an engineering-focused system for **modeling tax rules, storing tax-relevant data, and deterministically calculating outcomes** using transparent, verifiable logic.

The core goals are:
- Correctness
- Auditability
- Reproducibility
- Privacy
- Safe, compliant tax optimization through scenario analysis

---

## Why This Exists

Most consumer tax software:
- Hides calculation logic
- Cannot reproduce historical results once rules change
- Blends inputs, assumptions, and outputs without traceability
- Is cloud-based and opaque

Tax_Co-Pilot takes the opposite approach.

This project treats taxes as a **ledger + rules + calculations problem**, where:
- Inputs are explicit and immutable
- Rules are versioned data, not hidden code
- Outputs are fully traceable to their sources
- Every number can be explained

---

## High-Level Design Principles

### 1. Local-First & Privacy
- Runs entirely on local hardware
- No cloud dependency
- Data stored in local SQLite with **optional encryption at rest** (AES-256 via SQLCipher)
- Password-protected database with secure key derivation (PBKDF2)
- Explicit export and backup flows
- See [docs/ENCRYPTION.md](docs/ENCRYPTION.md) for encryption setup guide

### 2. Rules-as-Data
- Federal and state tax logic lives in **versioned rule packs**
- Rules are pinned to a tax year
- Past results never silently change
- Rule updates produce new versions with changelogs

### 3. Auditability by Design
Every calculated value includes:
- Rule ID and rule pack version
- Input references
- Intermediate calculations
- Rounding policy
- Human-readable explanation

Each tax run produces an immutable **Calculation Artifact** containing:
- Input snapshot
- Rule pack snapshot
- Outputs
- Full calculation trace

### 4. Multi-Person, Multi-State, Military-Aware
- Supports two taxpayers (MFJ / MFS)
- Models differing state obligations per person
- Supports military-relevant factors (e.g., PCS moves, residency modeling)
- Focuses on representation and workflow, not legal advice

### 5. Compliance-First Optimization
- Includes a scenario (“what-if”) engine
- Suggests only lawful, documented elections and choices
- Requires eligibility confirmation and supporting notes
- Supports conservative → exploratory analysis modes
- Never suggests concealment, mischaracterization, or unsupported deductions

---

## Project Scope (MVP)

The initial MVP focuses on proving the architecture:

- One tax year
- Simplified federal 1040-style calculation
- W-2 and basic 1099 income
- Withholding and estimated payments
- Two-person filing support
- One state module stub
- Local web UI
- Full calculation trace

---

## Project Status

Tax_Co-Pilot is currently **MVP / alpha**.  
Expect rapid iteration while the rules model, APIs, and data contracts are being validated.

## Versioning Approach

This project follows **Semantic Versioning (SemVer)**.

- During alpha, releases will use the `0.y.z` series (and may include `-alpha` tags).
- Breaking changes are expected between minor alpha releases.
- A stable compatibility promise begins at `1.0.0`.

## Support Policy (Alpha)

- **Release stage:** Alpha / MVP
- **Compatibility:** No backward-compatibility guarantees yet
- **Breaking changes:** Expected and may occur without long deprecation windows
- **Production use:** Not recommended for production tax filing workflows yet

## Tech Stack

- **Language:** Python 3.11+
- **Backend:** FastAPI
- **ASGI Server:** Uvicorn
- **Database:** SQLite (with optional AES-256 encryption via SQLCipher)
- **Encryption:** SQLCipher (primary) / Python Fernet (fallback); PBKDF2-HMAC-SHA256 key derivation
- **UI:** Server-rendered HTML templates (Jinja2)
- **Numeric Type:** Decimal
- **Rule Packs:** YAML (versioned)
- **CI:** GitHub Actions (ruff, mypy, pytest, pip-audit)

---

## Actual Current Repository Structure

```text
Tax_Co-Pilot/
├── .editorconfig
├── .github/
│   └── workflows/
│       └── ci.yml
├── .gitignore
├── .pre-commit-config.yaml
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
│   │   └── form_mapper.py
│   └── templates/
│       ├── layouts/
│       │   └── base.html
│       └── pages/
│           ├── calculate.html
│           ├── dashboard.html
│           ├── import_csv.html
│           ├── legal.html
│           ├── run_compare.html
│           ├── runs.html
│           ├── forms_view.html
│           ├── unlock.html
│           └── whatif.html
├── docs/
│   ├── DISCLAIMER.md
│   ├── ENCRYPTION.md
│   ├── EXPORT_CONTROL.md
│   └── NOTICE.md
├── rule_packs/
│   ├── federal/2024/
│   │   ├── federal_2024_manifest.yaml
│   │   └── federal_2024_rules.yaml
│   └── state/GA/2024/
│       ├── state_GA_2024_manifest.yaml
│       └── state_GA_2024_rules.yaml
├── tests/
│   ├── __init__.py
│   ├── test_calculate_name_validation.py
│   ├── test_calculator_resolve_ref.py
│   ├── test_encoding_guard.py
│   ├── test_encrypted_database.py
│   ├── test_encryption.py
│   ├── test_forms.py
│   ├── test_golden.py
│   ├── test_golden2.py
│   ├── test_golden_m1.py
│   ├── test_milestone6_routes.py
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
├── requirements.txt
├── requirements-dev.txt
└── run.sh
```

---

## Install

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Optional: dev tooling
python -m pip install -r requirements-dev.txt
```

## Run (Canonical)

Use the project launcher script:

```bash
./run.sh
```

The script starts Uvicorn with the ASGI import target `main:app`.

Expected local URL:

- <http://127.0.0.1:8000>

## Run (Direct Uvicorn Alternative)

```bash
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

## Test

```bash
pytest -q
```

---

## Legal & Acknowledgments

Tax_Co-Pilot is licensed under the **GNU Affero General Public License v3.0 or later** (AGPL-3.0-or-later). See [LICENSE](LICENSE) for the full text.

### Encryption Engine

Database encryption at rest is powered by **[SQLCipher](https://www.zetetic.net/sqlcipher/)** (AES-256), Copyright © 2008-2024 Zetetic LLC, licensed under the **BSD-3-Clause** license. SQLCipher is built on [SQLite](https://www.sqlite.org/), which is in the public domain.

The Python **[cryptography](https://github.com/pyca/cryptography)** library provides Fernet fallback encryption and is licensed under **Apache-2.0 OR BSD-3-Clause**. It includes **[OpenSSL](https://www.openssl.org/)** (Apache-2.0).

### Key Frameworks

| Library          | License      | Use                      |
|------------------|--------------|--------------------------|
| FastAPI          | MIT          | Web framework            |
| Uvicorn          | BSD-3-Clause | ASGI server              |
| Pydantic         | MIT          | Data validation          |
| Jinja2           | BSD-3-Clause | Template engine          |
| PyYAML           | MIT          | YAML rule pack parsing   |
| python-multipart | Apache-2.0   | Form data parsing        |
| pysqlcipher3     | zlib/libpng  | SQLCipher Python binding |
| keyring          | MIT          | OS credential storage    |
| htmx             | 0BSD         | Frontend interactivity   |

All third-party licenses are permissive and compatible with AGPL-3.0. Full attribution details are in [docs/NOTICE.md](docs/NOTICE.md).

### Encryption & Export Control

This software contains cryptographic functionality (AES-256 via SQLCipher, PBKDF2-HMAC-SHA256 key derivation). As publicly available open-source software, it is distributed under the TSU exception (EAR §740.13(e)). See [docs/EXPORT_CONTROL.md](docs/EXPORT_CONTROL.md) for details.

### Disclaimer

**This software is provided "as is", without warranty of any kind.** Tax_Co-Pilot is not tax advice software. All data is stored locally on your device. You are solely responsible for your data, backups, and encryption passwords. See the [AGPL-3.0 license](LICENSE) sections 15-16 for the full warranty disclaimer and liability limitation.
