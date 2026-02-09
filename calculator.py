"""Deterministic tax calculation engine with full audit trace.

This engine evaluates rules from a loaded RulePack against a TaxReturnInput,
producing a ReturnOutput and a list of TraceNodes. No arbitrary code execution.
All math uses Decimal. Every step is traced.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP, ROUND_DOWN, ROUND_UP
from typing import Any

from app.engine.rule_loader import RulePack
from app.models.domain import (
    TaxReturnInput, ReturnOutput, ReturnRun, TraceNode,
)

ROUNDING_MODES = {
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_UP": ROUND_UP,
}


def _to_decimal(val: Any) -> Decimal:
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))


def _round(val: Decimal, mode: str, precision: int) -> Decimal:
    rm = ROUNDING_MODES.get(mode, ROUND_HALF_UP)
    if precision == 0:
        return val.quantize(Decimal("1"), rounding=rm)
    return val.quantize(Decimal(10) ** -precision, rounding=rm)


def _format_usd(val: Decimal) -> str:
    return f"${val:,.2f}"


class CalculationEngine:
    """Evaluate a rule pack against inputs, producing traced results."""

    def __init__(self, rule_pack: RulePack, inputs: TaxReturnInput):
        self.rp = rule_pack
        self.inputs = inputs
        self.resolved: dict[str, Decimal] = {}
        self.traces: list[TraceNode] = []

    def run(self) -> ReturnRun:
        """Execute all rules in dependency order and return immutable ReturnRun."""
        # Resolve input refs first
        self._resolve_inputs()

        # Evaluate rules in defined order (YAML list order = dependency order for MVP)
        for rule_id, rule in self.rp.rules.items():
            self._evaluate_rule(rule)

        output = ReturnOutput(
            gross_income=self.resolved.get("fed.2024.gross_income.total", Decimal("0")),
            agi=self.resolved.get("fed.2024.agi.total", Decimal("0")),
            standard_deduction=self.resolved.get("fed.2024.standard_deduction", Decimal("0")),
            taxable_income=self.resolved.get("fed.2024.taxable_income", Decimal("0")),
            federal_tax=self.resolved.get("fed.2024.tax.brackets", Decimal("0")),
            total_withholding=self.resolved.get("fed.2024.total_withholding", Decimal("0")),
            refund_or_owed=self.resolved.get("fed.2024.refund_or_owed", Decimal("0")),
        )

        return ReturnRun(
            tax_year=self.inputs.tax_year,
            filing_status=self.inputs.filing_status,
            rule_pack_version=self.rp.version,
            rule_pack_checksum=self.rp.checksum,
            input_snapshot=self.inputs,
            output=output,
            trace=self.traces,
        )

    # ─── Input Resolution ─────────────────────────────────────

    def _resolve_inputs(self):
        """Pre-populate resolved dict with raw input aggregates."""
        self.resolved["input.filing_status"] = Decimal("0")  # sentinel; actual used as string
        self._filing_status = self.inputs.filing_status.value

        # W-2 wages
        self.resolved["input.w2.wages"] = self.inputs.total_wages()
        # 1099-INT
        self.resolved["input.1099int.amount"] = self.inputs.total_interest()
        # 1099-DIV
        self.resolved["input.1099div.ordinary"] = self.inputs.total_dividends()
        # 1099-B
        self.resolved["input.1099b.net_gain"] = self.inputs.total_capital_gains()
        # Withholding
        self.resolved["input.withholding.federal"] = self.inputs.total_federal_withholding()

    # ─── Rule Evaluation (closed set of types) ────────────────

    def _evaluate_rule(self, rule: dict):
        rule_type = rule["type"]
        if rule_type == "sum":
            self._eval_sum(rule)
        elif rule_type == "formula":
            self._eval_formula(rule)
        elif rule_type == "lookup":
            self._eval_lookup(rule)
        elif rule_type == "bracket_table":
            self._eval_bracket_table(rule)
        else:
            raise ValueError(f"Unknown rule type: {rule_type}")

    def _resolve_ref(self, ref_spec: Any) -> Decimal:
        """Resolve a reference — either a string or dict with 'ref' key."""
        if isinstance(ref_spec, str):
            ref = ref_spec
        elif isinstance(ref_spec, dict) and "ref" in ref_spec:
            ref = ref_spec["ref"]
        else:
            return _to_decimal(ref_spec)

        if ref in self.resolved:
            return self.resolved[ref]
        # Check if it's a rule we haven't evaluated yet
        if ref in self.rp.rules:
            self._evaluate_rule(self.rp.rules[ref])
            return self.resolved[ref]
        raise ValueError(f"Unresolved reference: {ref}")

    def _eval_sum(self, rule: dict):
        rule_id = rule["id"]
        items_spec = rule["inputs"]["items"]
        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = rule.get("rounding_precision", 2)

        # items can be a single ref or list of refs
        if isinstance(items_spec, list):
            values = [self._resolve_ref(item) for item in items_spec]
        else:
            # Single ref to an already-resolved aggregate
            val = self._resolve_ref(items_spec)
            values = [val]

        total = sum(values, Decimal("0"))
        result = _round(total, rounding, precision)
        self.resolved[rule_id] = result

        self.traces.append(TraceNode(
            node_id=rule_id,
            rule_id=rule_id,
            rule_pack_version=self.rp.version,
            description=rule["description"],
            inputs={"items": [str(v) for v in values]},
            intermediates=[],
            result={"value": str(result), "units": "USD", "rounding": rounding, "precision": precision},
            explanation=f"Sum of {len(values)} item(s) = {_format_usd(result)}",
        ))

    def _eval_formula(self, rule: dict):
        rule_id = rule["id"]
        expression = rule["expression"]
        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = rule.get("rounding_precision", 2)

        # Resolve named inputs
        input_vals: dict[str, Decimal] = {}
        for name, spec in rule["inputs"].items():
            input_vals[name] = self._resolve_ref(spec)

        # Safe expression evaluation (closed set of operations)
        result = self._safe_eval(expression, input_vals)
        result = _round(result, rounding, precision)
        self.resolved[rule_id] = result

        self.traces.append(TraceNode(
            node_id=rule_id,
            rule_id=rule_id,
            rule_pack_version=self.rp.version,
            description=rule["description"],
            inputs={k: str(v) for k, v in input_vals.items()},
            intermediates=[{"expression": expression}],
            result={"value": str(result), "units": "USD", "rounding": rounding, "precision": precision},
            explanation=self._explain_formula(expression, input_vals, result),
        ))

    def _eval_lookup(self, rule: dict):
        rule_id = rule["id"]
        table_path = rule["table"]
        key_spec = rule["key"]

        # Determine the lookup key
        if isinstance(key_spec, dict) and key_spec.get("ref") == "input.filing_status":
            key = self._filing_status
        else:
            key = str(self._resolve_ref(key_spec))

        value = _to_decimal(self.rp.get_constant(table_path, key))
        self.resolved[rule_id] = value

        self.traces.append(TraceNode(
            node_id=rule_id,
            rule_id=rule_id,
            rule_pack_version=self.rp.version,
            description=rule["description"],
            inputs={"table": table_path, "key": key},
            intermediates=[],
            result={"value": str(value), "units": "USD"},
            explanation=f"Lookup {table_path}[{key}] = {_format_usd(value)}",
        ))

    def _eval_bracket_table(self, rule: dict):
        rule_id = rule["id"]
        rounding = rule.get("rounding", "ROUND_HALF_UP")
        precision = rule.get("rounding_precision", 0)

        income = self._resolve_ref(rule["input"])

        # Determine filing status key
        key_spec = rule["key"]
        if isinstance(key_spec, dict) and key_spec.get("ref") == "input.filing_status":
            fs_key = self._filing_status
        else:
            fs_key = str(self._resolve_ref(key_spec))

        brackets = rule["tables"][fs_key]
        total_tax = Decimal("0")
        intermediates = []

        for bracket in brackets:
            lower = _to_decimal(bracket["lower"])
            upper = _to_decimal(bracket["upper"]) if bracket["upper"] is not None else None
            rate = _to_decimal(bracket["rate"])

            if income <= lower:
                break

            if upper is not None:
                taxable_in_bracket = min(income, upper) - lower
            else:
                taxable_in_bracket = income - lower

            tax_in_bracket = taxable_in_bracket * rate
            total_tax += tax_in_bracket

            intermediates.append({
                "bracket": f"{rate * 100}%",
                "range": f"{_format_usd(lower)}–{_format_usd(upper) if upper else '∞'}",
                "taxable_amount": str(taxable_in_bracket),
                "tax": str(tax_in_bracket),
            })

        result = _round(total_tax, rounding, precision)
        self.resolved[rule_id] = result

        # Build explanation
        parts = []
        for inter in intermediates:
            parts.append(f"{inter['bracket']} on {inter['range']}: {_format_usd(_to_decimal(inter['tax']))}")
        explanation = f"Tax on {_format_usd(income)} ({fs_key.upper()}): " + " + ".join(parts) + f" = {_format_usd(result)}"

        self.traces.append(TraceNode(
            node_id=rule_id,
            rule_id=rule_id,
            rule_pack_version=self.rp.version,
            description=rule["description"],
            inputs={"taxable_income": str(income), "filing_status": fs_key},
            intermediates=intermediates,
            result={"value": str(result), "units": "USD", "rounding": rounding, "precision": precision},
            explanation=explanation,
        ))

    # ─── Safe Expression Evaluator ────────────────────────────

    def _safe_eval(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        """Evaluate a simple expression. Supports: +, -, *, /, max(), min().
        No arbitrary code — just string parsing of a fixed grammar."""
        expr = expr.strip()

        # Handle max(a, b) and min(a, b)
        for func in ("max", "min"):
            if expr.startswith(f"{func}(") and expr.endswith(")"):
                inner = expr[len(func) + 1:-1]
                args = self._split_args(inner)
                vals = [self._safe_eval(a.strip(), variables) for a in args]
                return max(vals) if func == "max" else min(vals)

        # Handle binary operations (left to right, no precedence beyond +/- vs */÷)
        # Simple approach: substitute variables, then evaluate
        result = self._eval_additive(expr, variables)
        return result

    def _split_args(self, s: str) -> list[str]:
        """Split comma-separated args respecting parentheses."""
        depth = 0
        parts = []
        current = []
        for ch in s:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif ch == ',' and depth == 0:
                parts.append(''.join(current))
                current = []
                continue
            current.append(ch)
        parts.append(''.join(current))
        return parts

    def _eval_additive(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        """Parse addition and subtraction."""
        # Find the rightmost + or - not inside parens
        depth = 0
        pos = -1
        op = None
        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch == ')':
                depth += 1
            elif ch == '(':
                depth -= 1
            elif depth == 0 and ch in ('+', '-') and i > 0:
                pos = i
                op = ch
                break

        if pos > 0 and op:
            left = self._eval_additive(expr[:pos].strip(), variables)
            right = self._eval_multiplicative(expr[pos + 1:].strip(), variables)
            return left + right if op == '+' else left - right

        return self._eval_multiplicative(expr, variables)

    def _eval_multiplicative(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        """Parse multiplication and division."""
        depth = 0
        pos = -1
        op = None
        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch == ')':
                depth += 1
            elif ch == '(':
                depth -= 1
            elif depth == 0 and ch in ('*', '/') and i > 0:
                pos = i
                op = ch
                break

        if pos > 0 and op:
            left = self._eval_multiplicative(expr[:pos].strip(), variables)
            right = self._eval_atom(expr[pos + 1:].strip(), variables)
            return left * right if op == '*' else left / right

        return self._eval_atom(expr, variables)

    def _eval_atom(self, expr: str, variables: dict[str, Decimal]) -> Decimal:
        """Parse an atom: number, variable, or parenthesized expression."""
        expr = expr.strip()

        # Handle max/min at atom level too
        for func in ("max", "min"):
            if expr.startswith(f"{func}(") and expr.endswith(")"):
                inner = expr[len(func) + 1:-1]
                args = self._split_args(inner)
                vals = [self._safe_eval(a.strip(), variables) for a in args]
                return max(vals) if func == "max" else min(vals)

        # Parenthesized
        if expr.startswith("(") and expr.endswith(")"):
            return self._eval_additive(expr[1:-1], variables)

        # Variable
        if expr in variables:
            return variables[expr]

        # Numeric literal
        try:
            return Decimal(expr)
        except Exception:
            raise ValueError(f"Cannot evaluate expression atom: '{expr}'")

    def _explain_formula(self, expr: str, inputs: dict[str, Decimal], result: Decimal) -> str:
        parts = [f"{k}={_format_usd(v)}" for k, v in inputs.items()]
        return f"{expr} where {', '.join(parts)} → {_format_usd(result)}"
