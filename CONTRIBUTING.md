<!-- SPDX-License-Identifier: AGPL-3.0-or-later -->
# Contributing to Tax_Co-Pilot

Thanks for helping improve Tax_Co-Pilot. This project emphasizes deterministic behavior, transparency, and reproducibility.

This project is licensed under the **GNU AGPL v3**. By contributing, you agree that your contributions will be licensed under the same terms. All new source files should include the AGPL v3 license header.

## Local development setup

1. **Install Python**
   - Use Python 3.11+ (3.12 is also supported).
2. **Create and activate a virtual environment**
   - `python -m venv .venv`
   - `source .venv/bin/activate` (Linux/macOS) or `.venv\\Scripts\\activate` (Windows)
3. **Install dependencies**
   - `python -m pip install --upgrade pip`
   - `python -m pip install -r requirements.txt`
   - `python -m pip install -r requirements-dev.txt`
4. **Run the app locally (optional while developing)**
   - `python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload`

## Quality checks

Run all checks before opening a pull request:

- **Lint:** `python -m ruff check .`
- **Type-check:** `python -m mypy .`
- **Tests:** `python -m pytest -q` (tests live in the `tests/` directory)

If any check fails, fix the issue and rerun until clean.

## Commit expectations

- Make focused commits with clear messages (imperative mood, e.g., `Add GA rule validation for filing status`).
- Keep each commit scoped to one logical change.
- Include tests and/or documentation updates when behavior changes.

## Pull request expectations

Each PR should include:

- A concise summary of what changed and why.
- Notes on risk/impact (especially around calculation logic and rule packs).
- Evidence of validation (lint/type/tests run and results).
- Linked issue(s) when applicable.

Before requesting review, confirm:

- New logic is deterministic and auditable.
- Existing tests still pass.
- Added behavior is covered by tests where practical.

## CI expectations

This repository uses GitHub Actions CI from `.github/workflows/ci.yml`.

Current CI behavior:

- Runs on pull requests and pushes to `main`.
- Tests against Python `3.11` and `3.12`.
- Installs both runtime and development dependencies from:
  - `requirements.txt`
  - `requirements-dev.txt`
- Executes the following quality gates:
  - `ruff check .`
  - `mypy .`
  - `pytest` (with JUnit output and optional coverage XML)
- Runs `pip-audit` as **non-blocking** for now (`continue-on-error: true`).
- Uploads `test-results/` artifacts (JUnit + coverage when enabled).

### What this means for contributors

- Treat `ruff`, `mypy`, and `pytest` as required checks before opening a PR.
- Expect `pip-audit` findings to be visible in CI logs, but not to fail the workflow initially.
- If you disable coverage or artifact upload in CI env flags, ensure the change is intentional and documented in your PR.
