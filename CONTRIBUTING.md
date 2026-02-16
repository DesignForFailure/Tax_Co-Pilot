# Contributing

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
