# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Tax Co-Pilot is a local-first, privacy-preserving personal tax software system. It uses a **rules-as-data** architecture where tax logic lives in versioned YAML rule packs, not in application code. Every calculation produces a full audit trace (rule ID, inputs, intermediates, rounding, explanation). Currently alpha/MVP targeting tax year 2024 with federal 1040-style calculations and a Georgia state stub.

## Common Commands

```bash
# Run the app (FastAPI on localhost:8000)
./run.sh
# or: uvicorn main:app --host 127.0.0.1 --port 8000 --reload

# Lint
ruff check .

# Type check
mypy .

# Run all tests
pytest

# Run a single test file
pytest tests/test_golden.py

# Run a single test
pytest tests/test_golden.py::test_single_w2_mfj -v

# All three checks (definition of done for any task)
ruff check . && mypy . && pytest
```

## Architecture

### Layer Separation (strict rule)

- **`app/engine/`** — Tax computation logic only. No persistence, no I/O.
  - `calculator.py` — Deterministic CalculationEngine: normalizes inputs to `resolved[...]` namespace, evaluates rules in topological order using Decimal math, produces TraceNodes.
  - `rule_loader.py` — Loads YAML rule packs, validates expressions against an allowlist, computes SHA-256 checksums, topologically sorts rules. Four rule types: `sum`, `formula`, `lookup`, `bracket_table`.
  - `whatif.py` — WhatIfEngine for scenario comparison (e.g., MFJ vs MFS).

- **`app/services/`** — Persistence, encryption, adapters. No tax/business logic.
  - `database.py` — SQLite with WAL mode. Stores ReturnRun as immutable JSON blobs. Uses `hybrid_factory` for row access.
  - `encryption.py` — SQLCipher (primary) or Python Fernet (fallback). PBKDF2-HMAC-SHA256 key derivation.
  - `csv_import.py` — CSV parsing for W-2, 1099-INT, 1099-DIV, 1099-B.
  - `audit_export.py` — HTML and JSON audit export.

- **`app/models/domain.py`** — All Pydantic domain models (FilingStatus, W2Data, TaxReturnInput, ReturnRun, TraceNode, etc.).

- **`main.py`** — FastAPI app with all routes, form parsing, CSRF, security headers. This is a large file (~27KB) that serves as the web layer.

- **`rule_packs/{jurisdiction}/{year}/`** — Versioned YAML rule definitions and manifests.

### Key Invariants

- **`hybrid_factory` row compatibility is mandatory.** DB rows must support both `row[0]` (index) and `row["field"]` (key) access. Never break this.
- **Deterministic math.** All tax calculations use `Decimal`, never `float`.
- **Immutable runs.** A `ReturnRun` is a sealed artifact — inputs, outputs, and trace are stored together and never mutated.

## Agent Governance (`.agent_tools/`)

These files contain strict, non-negotiable rules for AI agent work:

- **New Python files** must have: SPDX license header (`# SPDX-License-Identifier: GPL-3.0-or-later`), module docstring, then imports (stdlib → third-party → local).
- **Imports:** Prefer `collections.abc` over `typing` aliases. Keep explicit, minimal, sorted. Never wrap in try/except.
- **Comments:** Explain *why*, not *what*. No ownerless TODOs.
- **Definition of done:** Every task must run `ruff check .`, `mypy .`, `pytest` and report results. Do not submit changes that introduce new lint, typing, or test failures.
- **Strict typing:** All new/modified code must satisfy mypy. Avoid `Any` types.

## Encryption Configuration

Controlled via environment variables:
- `TAX_COPILOT_ENCRYPTION_ENABLED` (true/false, default: false)
- `TAX_COPILOT_ENCRYPTION_PROVIDER` (sqlcipher/python/auto)
- `TAX_COPILOT_PASSWORD_SOURCE` (env/keyring/prompt/auto)
- `TAX_COPILOT_KEY_ITERATIONS` (default: 100000, minimum enforced)

## Testing Patterns

- **Golden tests** (`test_golden.py`, `test_golden2.py`): Hand-verified tax calculation scenarios. These are the primary correctness tests for the engine.
- **Route tests** (`test_milestone6_routes.py`): Integration tests covering all FastAPI endpoints using httpx TestClient.
- **Unit tests**: Encryption, reference resolution, name validation, encoding guards, CSV parsing.

## License

AGPL-3.0-or-later. All source files must include SPDX headers.
