# Roadmap

This roadmap reflects the near-term plan for evolving Tax_Co-Pilot from MVP/alpha toward a broader and more stable release.

## Current Stage

**Status:** MVP / alpha (`0.1.x-alpha`)  
**Focus:** Prove correctness, reproducibility, and auditability of core architecture.

---

## Near-Term Milestones

## 1) Federal Completeness (MVP hardening)

**Goal:** Expand the federal engine from simplified 1040-style coverage toward broader real-world household scenarios.

- Expand federal rule coverage for additional common income and adjustment categories.
- Improve edge-case handling, trace clarity, and deterministic rounding consistency.
- Add test vectors to reduce regression risk as rule pack complexity grows.
- Improve explainability output so each computed value is easier to audit.

## 2) State Expansion

**Goal:** Move from a single state stub to multi-state practical support.

- Add additional state rule pack scaffolds beyond GA.
- Define a repeatable onboarding pattern for new state modules.
- Improve multi-state household handling and state residency modeling.
- Introduce state-specific regression suites and validation fixtures.

## 3) Forms Support

**Goal:** Map calculated outputs to form-oriented workflows.

- Build form data models for key federal and state filing artifacts.
- Add export-ready structures for draft review and downstream tooling.
- Improve input capture coverage for form-required fields.
- Introduce consistency checks between calculated outputs and form mappings.

## 4) Security Hardening

**Goal:** Raise confidence in local-first data protection and operational safety.

- Harden data-at-rest protections and key-management workflow.
- Strengthen audit logging and trace tamper-evidence characteristics.
- Add dependency review and secure configuration baselines.
- Introduce targeted security tests and threat-model updates.

---

## Versioning & Release Trajectory

- Continue using **Semantic Versioning**.
- Treat `0.y.z` as **alpha** period where breaking changes may happen between minor releases.
- Promote to `1.0.0` once core interfaces, rule pack contracts, and data model stability criteria are met.
