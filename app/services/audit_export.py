"""Audit exports (MVP).

Provides:
- export_json(ReturnRun, path)
- generate_audit_html(ReturnRun) -> str
"""

from __future__ import annotations

import html
import json
from pathlib import Path

from app.models.domain import ReturnRun


def export_json(run: ReturnRun, path: Path) -> None:
    data = json.loads(run.model_dump_json())
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def generate_audit_html(run: ReturnRun) -> str:
    tp_names = ", ".join(
        f"{t.first_name} {t.last_name}".strip() for t in run.input_snapshot.taxpayers
    )

    def esc(s: str) -> str:
        return html.escape(s, quote=True)

    rows = []
    for t in run.trace:
        rid = esc(t.rule_id)
        desc = esc(t.description)
        val = esc(str(t.result.get("value")))
        expl = esc(t.explanation)
        rows.append(
            f"<tr><td><code>{rid}</code></td><td>{desc}</td><td>{val}</td><td>{expl}</td></tr>"
        )

    state_bits = ""
    if run.state_outputs:
        so = run.state_outputs[0]
        state_bits = (
            f"<p><strong>Georgia</strong>: taxable {esc(str(so.state_taxable_income))}, "
            f"tax {esc(str(so.state_tax))}</p>"
        )

    return f"""
<!doctype html>
<html lang=\"en\">
<head>
  <meta charset=\"utf-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1\" />
  <title>Tax Copilot â€” Audit Report</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; padding: 24px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #ddd; text-align: left; padding: 8px; vertical-align: top; }}
    code {{ background: #f4f4f4; padding: 2px 4px; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Tax Copilot â€” Audit Report</h1>
  <p><strong>Tax year:</strong> {run.tax_year} &nbsp; <strong>Filing status:</strong> {esc(run.filing_status.value.upper())}</p>
  <p><strong>Taxpayers:</strong> {esc(tp_names)}</p>
  <p><strong>Gross income:</strong> {esc(f"{run.output.gross_income:,.0f}")} &nbsp; <strong>Federal tax:</strong> {esc(str(run.output.federal_tax))}</p>
  {state_bits}
  <h2>Trace</h2>
  <table>
    <thead><tr><th>Rule</th><th>Description</th><th>Result</th><th>Explanation</th></tr></thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
  <hr />
  <p><strong>Disclaimer:</strong> This is a personal, offline tool for estimation and auditability. It is not tax advice.</p>
</body>
</html>
"""
