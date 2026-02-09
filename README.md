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
- Data encrypted at rest
- Explicit export and backup flows

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

## Tech Stack (Initial)

- **Language:** Python (primary)
- **Optional:** Rust for sandboxed calculation core
- **Backend:** FastAPI
- **Database:** SQLite (MVP), path to Postgres
- **UI:** Local web UI (server-rendered or React)
- **Numeric Type:** Decimal
- **Rule Packs:** JSON/YAML (versioned)

---

## Repository Structure (Planned)

```text
tax_co_pilot/
├── app/
│   ├── api/
│   ├── core/
│   ├── engine/
│   ├── rules/
│   ├── storage/
│   ├── security/
│   └── ui/
├── rule_packs/
│   ├── federal/
│   │   └── 2024/
│   └── states/
├── tests/
├── docs/
└── README.md
