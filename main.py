"""Tax Copilot — FastAPI Application (MVP Vertical Slice)."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus, Form1099BData, TaxpayerRole, Taxpayer,
    TaxReturnInput, W2Data,
)
from app.services.database import init_db, save_return_run, get_return_run, list_return_runs

app = FastAPI(title="Tax Copilot", version="0.1.0")
templates = Jinja2Templates(directory="app/templates")

# Load rule pack at startup
RULE_PACK_DIR = Path("rule_packs/federal/2024")
rule_pack = RulePack(RULE_PACK_DIR)

# In-memory store for most recent run (MVP simplicity)
latest_run = None


@app.on_event("startup")
def startup():
    init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "run": latest_run,
    })


@app.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request):
    return templates.TemplateResponse("pages/calculate.html", {
        "request": request,
    })


@app.post("/calculate")
def calculate_submit(
    request: Request,
    tax_year: int = Form(2024),
    filing_status: str = Form("mfj"),
    p_first: str = Form(""),
    p_last: str = Form(""),
    p_employer: str = Form(""),
    p_wages: str = Form("0"),
    p_withheld: str = Form("0"),
    cg_desc: str = Form(""),
    cg_proceeds: str = Form("0"),
    cg_basis: str = Form("0"),
):
    global latest_run

    # Build taxpayer
    w2 = W2Data(
        employer_name=p_employer,
        wages=Decimal(p_wages or "0"),
        federal_withheld=Decimal(p_withheld or "0"),
    )

    primary = Taxpayer(
        role=TaxpayerRole.PRIMARY,
        first_name=p_first,
        last_name=p_last,
        w2s=[w2],
    )

    # Optional capital gains
    if cg_proceeds and Decimal(cg_proceeds or "0") > 0:
        primary.form_1099_bs.append(Form1099BData(
            description=cg_desc or "Capital gain",
            proceeds=Decimal(cg_proceeds),
            cost_basis=Decimal(cg_basis or "0"),
        ))

    inputs = TaxReturnInput(
        tax_year=tax_year,
        filing_status=FilingStatus(filing_status),
        taxpayers=[primary],
    )

    # Run calculation engine
    engine = CalculationEngine(rule_pack, inputs)
    run = engine.run()
    latest_run = run

    # Persist to DB
    run_dict = json.loads(run.model_dump_json())
    save_return_run(run_dict)

    return RedirectResponse(url="/", status_code=303)


@app.get("/runs", response_class=HTMLResponse)
def past_runs(request: Request):
    runs = list_return_runs()
    return templates.TemplateResponse("pages/runs.html", {
        "request": request,
        "runs": runs,
    })


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def view_run(request: Request, run_id: str):
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)

    # Reconstruct for template (parse JSON fields)
    from app.models.domain import ReturnRun
    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run_data["rule_pack_version"] = run_data["rule_pack_version"]
    run_data["rule_pack_checksum"] = run_data["rule_pack_checksum"]

    run = ReturnRun(**{
        k: v for k, v in run_data.items()
        if k not in ("input_snapshot_json", "output_json", "trace_json")
    })

    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request,
        "run": run,
    })
