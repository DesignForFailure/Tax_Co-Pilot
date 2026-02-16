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

## Tech Stack (Current)

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

## Tech Stack (Initial)

- **Language:** Python
- **Backend:** FastAPI
- **ASGI Server:** Uvicorn
- **Database:** SQLite
- **Storage security (current):** plaintext SQLite database file on local disk
- **Storage security (planned):** optional encryption-at-rest workflow (e.g., SQLCipher)
- **UI:** Server-rendered HTML templates
- **Numeric Type:** Decimal
- **Rule Packs:** YAML (versioned)

---

## Actual Current Repository Structure

```text
Tax_Co-Pilot/
├── app/
│   ├── engine/
│   │   ├── calculator.py
│   │   ├── rule_loader.py
│   │   └── whatif.py
│   ├── models/
│   │   └── domain.py
│   ├── services/
│   │   ├── audit_export.py
│   │   ├── csv_import.py
│   │   └── database.py
│   └── templates/
│       ├── layouts/
│       │   └── base.html
│       └── pages/
│           ├── calculate.html
│           ├── dashboard.html
│           └── runs.html
├── main.py
├── requirements.txt
├── requirements-dev.txt
├── run.sh
├── test_golden.py
├── test_golden2.py
└── rule_packs/
    ├── federal/2024/
    │   ├── federal_2024_manifest.yaml
    │   └── federal_2024_rules.yaml
    └── state/GA/2024/
        ├── state_GA_2024_manifest.yaml
        └── state_GA_2024_rules.yaml
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
