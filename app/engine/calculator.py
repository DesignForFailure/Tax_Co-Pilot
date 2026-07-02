# SPDX-License-Identifier: AGPL-3.0-or-later
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Deterministic tax calculation engine with full audit trace.

How it works (MVP):
- Inputs are aggregated into normalized `resolved[...]` values (e.g., total wages).
- Rules from RulePack are evaluated in dependency-safe topological order.
- Each rule evaluation writes:
  - `resolved[rule_id] = Decimal(result)`
  - a TraceNode with inputs, intermediates, result, and human-readable explanation.

Security/QA properties:
- No arbitrary code execution: expressions use a small parser (not eval()).
- All math uses Decimal for audit-friendly, deterministic computation.
- Division-by-zero is explicitly blocked.

Future improvements:
- Add additional expression operators/functions if needed (keep allowlist).
- Add caps/constraints on numeric magnitudes to prevent pathological inputs.
"""

from __future__ import annotations

import re
from decimal import ROUND_DOWN, ROUND_HALF_UP, ROUND_UP, Decimal
from typing import Any

from app.engine.rule_loader import RulePack, RulePackError
from app.log import get_logger
from app.models.domain import ReturnOutput, ReturnRun, StateReturnOutput, TaxReturnInput, TraceNode

logger = get_logger(__name__)

ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}

_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(?:(?:\d+(?:\.\d*)?)|(?:\.\d+))(?:[eE][+-]?\d+)?$")
_REF_LIKE_RE = re.compile(r"^[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+$")


def _to_decimal(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _round(val: Decimal, mode: str, precision: int) -> Decimal:
    if precision < 0:
        raise ValueError(f"rounding_precision must be >= 0, got {precision}")
    rm = ROUNDING_MODES.get(mode)
    if rm is None:
        # A silent fallback would apply a different mode than the audit
        # trace records, so unknown modes must fail loudly.
        raise RulePackError(f"Unsupported rounding mode: {mode!r}")
    if precision == 0:
        return val.quantize(Decimal("1"), rounding=rm)
    return val.quantize(Decimal(10) ** -precision, rounding=rm)


def _format_usd(val: Decimal) -> str:
    return f"${val:,.2f}"


def _is_numeric_literal(spec: str) -> bool:
    return bool(_NUMERIC_LITERAL_RE.fullmatch(spec.strip()))


def _looks_like_reference(spec: str) -> bool:
    stripped = spec.strip()
    if stripped.startswith("input."):
        return True
    if _is_numeric_literal(stripped):
        return False
    return bool(_REF_LIKE_RE.fullmatch(stripped))


class CalculationEngine:
    """Evaluate a rule pack against inputs, producing traced results."""

    def __init__(
        self,
        rule_pack: RulePack,
        inputs: TaxReturnInput,
        state_packs: dict[str, RulePack] | None = None,
    ):
        self.rp = rule_pack
        self.inputs = inputs
        self.state_packs = state_packs or {}
        self.resolved: dict[str, Decimal] = {}
        self.traces: list[TraceNode] = []
        self._filing_status: str = inputs.filing_status.value
        self._evaluating: list[str] = []

    def run(self) -> ReturnRun:
        # 1) Normalize inputs into resolved values (engine inputs are also traceable).
        self._resolve_inputs()

        # 2) Evaluate rules in dependency-safe order.
        for rule_id in self.rp.rule_order:
            self._evaluate_rule(self.rp.rules[rule_id])

        yr = self.rp.tax_year
        output = ReturnOutput(
            gross_income=self.resolved.get(f"fed.{yr}.gross_income.total", Decimal("0")),
            agi=self.resolved.get(f"fed.{yr}.agi.total", Decimal("0")),
            standard_deduction=self.resolved.get(f"fed.{yr}.standard_deduction", Decimal("0")),
            taxable_income=self.resolved.get(f"fed.{yr}.taxable_income", Decimal("0")),
            federal_tax=self.resolved.get(f"fed.{yr}.tax.after_credits", Decimal("0")),
            total_withholding=self.resolved.get(f"fed.{yr}.total_withholding", Decimal("0")),
            refund_or_owed=self.resolved.get(f"fed.{yr}.refund_or_owed", Decimal("0")),
            adjustments_total=self.resolved.get(f"fed.{yr}.adjustments.total", Decimal("0")),
            estimated_tax_payments=self.resolved.get(f"fed.{yr}.estimated_payments", Decimal("0")),
            total_payments=self.resolved.get(f"fed.{yr}.total_payments", Decimal("0")),
            itemized_deductions=self.resolved.get(f"fed.{yr}.itemized.total", Decimal("0")),
            deduction_applied=self.resolved.get(f"fed.{yr}.deductions.applied", Decimal("0")),
            child_tax_credit=self.resolved.get(f"fed.{yr}.credits.ctc.final", Decimal("0")),
            total_credits=self.resolved.get(f"fed.{yr}.credits.total", Decimal("0")),
            tax_before_credits=self.resolved.get(f"fed.{yr}.tax.brackets", Decimal("0")),
        )

        state_outputs = self._run_states()

        return ReturnRun(
            tax_year=self.inputs.tax_year,
            filing_status=self.inputs.filing_status,
            rule_pack_version=self.rp.version,
            rule_pack_checksum=self.rp.checksum,
            input_snapshot=self.inputs,
            output=output,
            state_outputs=state_outputs,
            trace=self.traces,
        )

    # ─── State execution ───────────────────────────────────────

    def _run_states(self) -> list[StateReturnOutput]:
        outs: list[StateReturnOutput] = []
        if not self.state_packs:
            return outs

        # Resolve withholding for every state in state_packs.
        for state_code in sorted(self.state_packs):
            sc = state_code.upper()
            self.resolved[f"input.withholding.state.{sc}"] = sum(
                (
                    w.state_withheld
                    for tp in self.inputs.taxpayers
                    for w in tp.w2s
                    if (w.state or "").upper() == sc
                ),
                Decimal("0"),
            )

        for state_code in sorted(self.state_packs):
            sp = self.state_packs[state_code]
            expected_prefix = f"{state_code.lower()}."
            if sp.id_prefix != expected_prefix:
                # A pack declaring a foreign jurisdiction (e.g. "federal" or
                # another state) could overwrite resolved values outside its
                # namespace; the prefix must match the key it runs under.
                raise RulePackError(
                    f"State pack for {state_code!r} declares jurisdiction "
                    f"{sp.jurisdiction!r} (prefix {sp.id_prefix!r}); expected "
                    f"prefix {expected_prefix!r}"
                )
            orig_pack = self.rp
            self.rp = sp
            try:
                for rule_id in sp.rule_order:
                    self._evaluate_rule(sp.rules[rule_id])

                st = state_code.upper()
                st_lower = state_code.lower()
                yr = sp.tax_year
                outs.append(
                    StateReturnOutput(
                        state=st,
                        state_agi=self.resolved.get(
                            f"{st_lower}.{yr}.agi", Decimal("0")
                        ),
                        state_standard_deduction=self.resolved.get(
                            f"{st_lower}.{yr}.standard_deduction", Decimal("0")
                        ),
                        state_personal_exemption=self.resolved.get(
                            f"{st_lower}.{yr}.personal_exemption", Decimal("0")
                        ),
                        state_taxable_income=self.resolved.get(
                            f"{st_lower}.{yr}.taxable_income", Decimal("0")
                        ),
                        state_tax=self.resolved.get(
                            f"{st_lower}.{yr}.tax", Decimal("0")
                        ),
                        state_withholding=self.resolved.get(
                            f"{st_lower}.{yr}.withholding", Decimal("0")
                        ),
                        state_refund_or_owed=self.resolved.get(
                            f"{st_lower}.{yr}.refund_or_owed", Decimal("0")
                        ),
                    )
                )
            finally:
                self.rp = orig_pack

        return outs

    # ─── Input normalization ───────────────────────────────────

    def _resolve_inputs(self) -> None:
        self.resolved["input.w2.wages"] = self.inputs.total_wages()
        self.resolved["input.1099int.amount"] = self.inputs.total_interest()
        self.resolved["input.1099int.tax_exempt"] = self.inputs.total_tax_exempt_interest()
        self.resolved["input.1099div.ordinary"] = self.inputs.total_dividends()
        self.resolved["input.1099div.qualified"] = self.inputs.total_qualified_dividends()
        self.resolved["input.1099b.net_gain"] = self.inputs.total_capital_gains()
        self.resolved["input.withholding.federal"] = self.inputs.total_federal_withholding()
        self.resolved["input.1099nec.compensation"] = self.inputs.total_self_employment_income()
        self.resolved["input.ssa.total_benefits"] = self.inputs.total_social_security_benefits()
        self.resolved["input.other_income"] = self.inputs.other_income
        self.resolved["input.adjustments.student_loan_interest"] = (
            self.inputs.adjustments.student_loan_interest
        )
        self.resolved["input.adjustments.ira_contributions"] = (
            self.inputs.adjustments.ira_contributions
        )
        self.resolved["input.adjustments.hsa_contributions"] = (
            self.inputs.adjustments.hsa_contributions
        )
        self.resolved["input.adjustments.educator_expenses"] = (
            self.inputs.adjustments.educator_expenses
        )
        self.resolved["input.adjustments.self_employment_tax_deduction"] = (
            self.inputs.adjustments.self_employment_tax_deduction
        )
        self.resolved["input.estimated_payments"] = self.inputs.estimated_tax_payments

        # Itemized deduction inputs
        self.resolved["input.itemized.medical_expenses"] = (
            self.inputs.itemized_deductions.medical_expenses
        )
        self.resolved["input.itemized.state_local_taxes"] = (
            self.inputs.itemized_deductions.state_local_taxes
        )
        self.resolved["input.itemized.real_estate_taxes"] = (
            self.inputs.itemized_deductions.real_estate_taxes
        )
        self.resolved["input.itemized.mortgage_interest"] = (
            self.inputs.itemized_deductions.mortgage_interest
        )
        self.resolved["input.itemized.charitable_cash"] = (
            self.inputs.itemized_deductions.charitable_cash
        )
        self.resolved["input.itemized.charitable_noncash"] = (
            self.inputs.itemized_deductions.charitable_noncash
        )

        # Dependents
        self.resolved["input.qualifying_children"] = Decimal(
            self.inputs.qualifying_children
        )

    # ─── Rule evaluation dispatch ───────────────────────────────

    def _evaluate_rule(self, rule: dict[str, Any]) -> None:
        rule_id = rule.get("id", "")
        # Bare-string references can trigger on-demand evaluation ahead of the
        # topological order (the loader only graphs {ref: ...} dicts), so a
        # rule may be requested twice. Re-evaluating would append a duplicate
        # TraceNode to the sealed run.
        if rule_id in self.resolved:
            return
        if rule_id in self._evaluating:
            cycle = " -> ".join([*self._evaluating, rule_id])
            raise RulePackError(f"Rule dependency cycle detected at runtime: {cycle}")

        self._evaluating.append(rule_id)
        try:
            rule_type = rule.get("type")
            if rule_type == "sum":
                self._eval_sum(rule)
            elif rule_type == "formula":
                self._eval_formula(rule)
            elif rule_type == "lookup":
                self._eval_lookup(rule)
            elif rule_type == "bracket_table":
                self._eval_bracket_table(rule)
            else:
                raise RulePackError(f"Unknown rule type: {rule_type}")
        finally:
            self._evaluating.pop()

    def _enforce_rule_namespace(self, rule_id: str) -> None:
        """Ensure the currently-active RulePack cannot write outside its namespace."""
        if not rule_id.startswith(self.rp.id_prefix):
            raise RulePackError(
                f"Rule id {rule_id!r} violates namespace for jurisdiction {self.rp.jurisdiction!r} "
                f"(expected prefix {self.rp.id_prefix!r})"
            )

    def _resolve_ref(self, spec: Any) -> Decimal:
        # Strings may be rule IDs, input IDs, or numeric literals.
        if isinstance(spec, str):
            ref = spec.strip()
            if ref == "input.filing_status":
                raise RulePackError("input.filing_status cannot be resolved as Decimal")
            if ref in self.resolved:
                return self.resolved[ref]
            if ref in self.rp.rules:
                self._evaluate_rule(self.rp.rules[ref])
                return self.resolved[ref]
            if _looks_like_reference(ref):
                raise RulePackError(f"Missing reference: {ref}")
            if _is_numeric_literal(ref):
                return _to_decimal(ref)
            raise RulePackError(f"Cannot resolve ref or numeric literal: {spec!r}")

        # Canonical spec: {literal: ...} or {ref: ...}
        if isinstance(spec, dict):
            if "literal" in spec:
                return _to_decimal(spec["literal"])
            if "ref" in spec:
                return self._resolve_ref(spec["ref"])

        try:
            return _to_decimal(spec)
        except Exception as e:
            logger.debug("Cannot resolve value spec: %r", spec, exc_info=True)
            raise RulePackError(f"Cannot resolve value spec: {spec!r}") from e

    # ─── Rule evaluators ───────────────────────────────────────

    def _eval_sum(self, rule: dict[str, Any]) -> None:
        rule_id = rule["id"]
        self._enforce_rule_namespace(rule_id)

        items_spec = rule.get("inputs", {}).get("items")
        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = int(rule.get("rounding_precision", 2))

        if isinstance(items_spec, list):
            values = [self._resolve_ref(item) for item in items_spec]
        else:
            values = [self._resolve_ref(items_spec)]

        total = sum(values, Decimal("0"))
        result = _round(total, rounding, precision)
        self.resolved[rule_id] = result

        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"items": [str(v) for v in values]},
                intermediates=[],
                result={
                    "value": str(result),
                    "units": "USD",
                    "rounding": rounding,
                    "precision": precision,
                },
                explanation=(
                    f"{rule.get('form_line', '')}: " if rule.get("form_line") else ""
                )
                + f"{len(values)} item(s) totaling {_format_usd(result)}",
                form_line=rule.get("form_line", ""),
            )
        )

    def _eval_formula(self, rule: dict[str, Any]) -> None:
        rule_id = rule["id"]
        self._enforce_rule_namespace(rule_id)

        expr = rule["expression"]
        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = int(rule.get("rounding_precision", 2))

        inputs = {k: self._resolve_ref(v) for k, v in (rule.get("inputs") or {}).items()}

        result = self._safe_eval(expr, inputs)
        result = _round(result, rounding, precision)
        self.resolved[rule_id] = result

        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={k: str(v) for k, v in inputs.items()},
                intermediates=[{"expression": expr}],
                result={
                    "value": str(result),
                    "units": "USD",
                    "rounding": rounding,
                    "precision": precision,
                },
                explanation=(
                    f"{rule.get('form_line', '')}: " if rule.get("form_line") else ""
                )
                + self._explain_formula(expr, inputs, result),
                form_line=rule.get("form_line", ""),
            )
        )

    def _eval_lookup(self, rule: dict[str, Any]) -> None:
        rule_id = rule["id"]
        self._enforce_rule_namespace(rule_id)

        table_path = rule["table"]
        key_spec = rule["key"]

        if isinstance(key_spec, dict) and key_spec.get("ref") == "input.filing_status":
            key = self._filing_status
        elif isinstance(key_spec, str) and key_spec == "input.filing_status":
            key = self._filing_status
        else:
            key = str(self._resolve_ref(key_spec))

        value = _to_decimal(self.rp.get_constant(table_path, key))
        self.resolved[rule_id] = value

        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"table": table_path, "key": key},
                intermediates=[],
                result={"value": str(value), "units": "USD"},
                explanation=(
                    f"{rule.get('form_line', '')}: " if rule.get("form_line") else ""
                )
                + f"{key} → {_format_usd(value)}",
                form_line=rule.get("form_line", ""),
            )
        )

    def _eval_bracket_table(self, rule: dict[str, Any]) -> None:
        rule_id = rule["id"]
        self._enforce_rule_namespace(rule_id)

        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = int(rule.get("rounding_precision", 0))

        income = self._resolve_ref(rule["input"])

        key_spec = rule["key"]
        if isinstance(key_spec, dict) and key_spec.get("ref") == "input.filing_status":
            fs_key = self._filing_status
        elif isinstance(key_spec, str) and key_spec == "input.filing_status":
            fs_key = self._filing_status
        else:
            fs_key = str(self._resolve_ref(key_spec))

        tables = rule.get("tables") or {}
        if fs_key not in tables:
            raise RulePackError(f"Bracket table missing filing status key: {fs_key}")
        brackets = tables[fs_key]
        if not isinstance(brackets, list):
            raise RulePackError(f"Bracket table for {fs_key} must be a list")

        total_tax = Decimal("0")
        intermediates: list[dict[str, Any]] = []

        for b in brackets:
            lower = _to_decimal(b["lower"])
            upper = _to_decimal(b["upper"]) if b.get("upper") is not None else None
            rate = _to_decimal(b["rate"])

            if income <= lower:
                break

            taxable_in_bracket = (min(income, upper) if upper is not None else income) - lower
            if taxable_in_bracket <= 0:
                continue

            tax_in_bracket = taxable_in_bracket * rate
            total_tax += tax_in_bracket

            intermediates.append(
                {
                    "bracket": f"{(rate * Decimal('100')).normalize()}%",
                    "range": f"{_format_usd(lower)}–{_format_usd(upper) if upper is not None else '∞'}",
                    "taxable_amount": str(taxable_in_bracket),
                    "tax": str(tax_in_bracket),
                }
            )

        result = _round(total_tax, rounding, precision)
        self.resolved[rule_id] = result

        parts = [
            f"{i['bracket']} on {i['range']}: {_format_usd(_to_decimal(i['tax']))}"
            for i in intermediates
        ]
        line_prefix = f"{rule.get('form_line', '')}: " if rule.get("form_line") else ""
        explanation = (
            f"{line_prefix}Tax on {_format_usd(income)} ({fs_key.upper()}): "
            + (" + ".join(parts) if parts else "$0.00")
            + f" = {_format_usd(result)}"
        )

        self.traces.append(
            TraceNode(
                node_id=rule_id,
                rule_id=rule_id,
                rule_pack_version=self.rp.version,
                description=rule.get("description", ""),
                inputs={"taxable_income": str(income), "filing_status": fs_key},
                intermediates=intermediates,
                result={
                    "value": str(result),
                    "units": "USD",
                    "rounding": rounding,
                    "precision": precision,
                },
                explanation=explanation,
                form_line=rule.get("form_line", ""),
            )
        )

    # ─── Safe expression evaluation ────────────────────────────

    def _safe_eval(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        """Evaluate a formula expression safely using recursive-descent parsing.

        Supports: +, -, *, /, max(), min(), parentheses, variable refs, and
        numeric literals.  No eval() or exec() is used anywhere.
        Operator precedence: additive < multiplicative < atom.
        Scanning is right-to-left to get left-associative binding.
        """
        expr = expr.strip()

        for func in ("max", "min"):
            if expr.startswith(f"{func}("):
                # Verify the closing ) matches the opening ( of this call
                depth = 0
                match_end = -1
                for _i, _ch in enumerate(expr[len(func):]):
                    if _ch == "(":
                        depth += 1
                    elif _ch == ")":
                        depth -= 1
                        if depth == 0:
                            match_end = len(func) + _i
                            break
                if match_end == len(expr) - 1:
                    inner = expr[len(func) + 1 : -1]
                    args = self._split_args(inner)
                    vals = [self._safe_eval(a.strip(), variables) for a in args]
                    return max(vals) if func == "max" else min(vals)

        return self._eval_additive(expr, variables)

    def _split_args(self, s: str) -> list[str]:
        """Split a comma-separated argument list, respecting nested parentheses."""
        depth = 0
        parts: list[str] = []
        current: list[str] = []
        for ch in s:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                parts.append("".join(current))
                current = []
                continue
            current.append(ch)
        parts.append("".join(current))
        return [p for p in parts if p.strip()]

    def _eval_additive(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        depth = 0
        pos = -1
        op: str | None = None

        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                depth -= 1
            elif depth == 0 and ch in ("+", "-") and i > 0:
                pos, op = i, ch
                break

        if pos > 0 and op is not None:
            left = self._eval_additive(expr[:pos].strip(), variables)
            right = self._eval_multiplicative(expr[pos + 1 :].strip(), variables)
            return left + right if op == "+" else left - right

        return self._eval_multiplicative(expr, variables)

    def _eval_multiplicative(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        depth = 0
        pos = -1
        op: str | None = None

        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch == ")":
                depth += 1
            elif ch == "(":
                depth -= 1
            elif depth == 0 and ch in ("*", "/") and i > 0:
                pos, op = i, ch
                break

        if pos > 0 and op is not None:
            left = self._eval_multiplicative(expr[:pos].strip(), variables)
            right = self._eval_atom(expr[pos + 1 :].strip(), variables)
            if op == "/" and right == 0:
                raise RulePackError("Division by zero in formula evaluation")
            return left * right if op == "*" else left / right

        return self._eval_atom(expr, variables)

    def _eval_atom(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        expr = expr.strip()

        # Handle unary operators
        if expr.startswith("-") and len(expr) > 1:
            return -self._eval_atom(expr[1:], variables)
        if expr.startswith("+") and len(expr) > 1:
            return self._eval_atom(expr[1:], variables)

        for func in ("max", "min"):
            if expr.startswith(f"{func}("):
                # Verify the closing ) matches the opening ( of this call
                depth = 0
                match_end = -1
                for _i, _ch in enumerate(expr[len(func):]):
                    if _ch == "(":
                        depth += 1
                    elif _ch == ")":
                        depth -= 1
                        if depth == 0:
                            match_end = len(func) + _i
                            break
                if match_end == len(expr) - 1:
                    inner = expr[len(func) + 1 : -1]
                    args = self._split_args(inner)
                    vals = [self._safe_eval(a.strip(), variables) for a in args]
                    return max(vals) if func == "max" else min(vals)

        if expr.startswith("(") and expr.endswith(")"):
            return self._eval_additive(expr[1:-1], variables)

        if expr in variables:
            return variables[expr]

        try:
            return Decimal(expr)
        except Exception as e:
            logger.debug("Cannot evaluate expression atom: %r", expr, exc_info=True)
            raise RulePackError(f"Cannot evaluate expression atom: '{expr}'") from e

    def _explain_formula(self, expr: str, inputs: dict[str, Decimal], result: Decimal) -> str:
        parts = [f"{k}={_format_usd(v)}" for k, v in inputs.items()]
        return f"{expr} where {', '.join(parts)} → {_format_usd(result)}"
