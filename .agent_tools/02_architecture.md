<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
# 02 Architecture (Strict)

## SQLCipher / `hybrid_factory` Rule
The DB layer must keep the established `hybrid_factory` compatibility model.

### Required Behavior
- Key access must continue working: `row["field"]`
- Index access must continue working: `row[0]`
- Refactors must not break existing consumers of either pattern.

## Layer Separation Rule
- `app/engine/` = business/tax computation logic.
- `app/services/` = persistence, encryption, adapters, and external service/data concerns.

### Guardrails
- Engine modules should not directly own persistence implementation details.
- Service modules should not absorb tax/business-rule logic.
- Keep cross-layer boundaries explicit and minimal.
