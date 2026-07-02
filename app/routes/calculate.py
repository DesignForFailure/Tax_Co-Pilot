# SPDX-License-Identifier: AGPL-3.0-or-later
"""Home, dashboard, calculate, and what-if routes."""

from __future__ import annotations

import json
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.engine.whatif import WhatIfEngine
from app.models.domain import ReturnRun
from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.db_state import (
    database_locked,
    load_latest_run,
    load_run_from_row,
    locked_database_response,
)
from app.route_helpers.form_parsing import form_str, parse_tax_input_from_form
from app.route_helpers.pack_cache import (
    available_states_by_year,
    available_years,
    get_federal_pack,
    get_state_packs,
)
from app.services.database import list_return_runs, save_return_run
from app.services.rule_pack_editor import _pack_path
from app.services.rule_pack_editor import list_all_packs as list_rule_packs

router = APIRouter(tags=["calculate"])


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/", response_class=HTMLResponse)
def home(request: Request) -> Response:
    csrf = get_csrf_token(request)
    try:
        locked = database_locked()
    except RuntimeError as exc:
        return HTMLResponse(str(exc), status_code=500)

    recent_runs: list[dict[str, Any]] = []
    latest_run: ReturnRun | None = None
    run_count = 0
    if not locked:
        # The home page only needs the newest five runs plus a total count —
        # never the full table.
        recent_runs, run_count = list_return_runs(page=1, page_size=5)
        if recent_runs:
            latest_run = load_run_from_row(recent_runs[0])

    latest_year = max(available_years, default=0)
    response = _templates(request).TemplateResponse(
        request,
        "pages/home.html",
        {
            "locked": locked,
            "latest_run": latest_run,
            "recent_runs": recent_runs,
            "run_count_display": "Locked" if locked else run_count,
            "available_years": available_years,
            "latest_state_count": len(get_state_packs(latest_year)) if latest_year else 0,
            "pack_count": len(list_rule_packs()),
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/dashboard.html",
        {"run": load_latest_run(), "is_latest": True},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request) -> HTMLResponse:
    csrf = get_csrf_token(request)
    states_by_year = available_states_by_year()
    default_year = 2024 if 2024 in available_years else max(available_years, default=0)
    response = _templates(request).TemplateResponse(
        request,
        "pages/calculate.html",
        {
            "csrf": csrf,
            "available_years": available_years,
            "available_states": states_by_year.get(default_year, []),
            "available_states_by_year": states_by_year,
            "default_year": default_year,
            "pack_variants": list_rule_packs(),
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/calculate")
async def calculate_submit(request: Request) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    csrf = get_csrf_token(request)

    try:
        inputs = parse_tax_input_from_form(fd, available_years)

        states_needed = {
            w2.state.upper()
            for taxpayer in inputs.taxpayers
            for w2 in taxpayer.w2s
            if w2.state
        }
        residence = str(fd.get("state_of_residence", "")).strip().upper()
        if residence:
            states_needed.add(residence)

        pack_variant = form_str(fd, "pack_variant") or "standard"
        if pack_variant != "standard":
            fed_custom_dir = _pack_path("federal", inputs.tax_year, pack_variant)
            if not fed_custom_dir.exists():
                # Falling back to the standard pack would save a run the user
                # believes used their custom rules.
                raise ValueError(
                    f"Selected rule pack variant {pack_variant!r} no longer exists"
                )
            fed_pack = RulePack.load(fed_custom_dir)
        else:
            fed_pack = get_federal_pack(inputs.tax_year)

        year_state_packs = get_state_packs(inputs.tax_year)
        active_state_packs = {
            state_code: year_state_packs[state_code]
            for state_code in sorted(states_needed)
            if state_code in year_state_packs
        }
        run = CalculationEngine(fed_pack, inputs, state_packs=active_state_packs).run()
        save_return_run(json.loads(run.model_dump_json()))
        return RedirectResponse(url="/dashboard", status_code=303)
    except ValueError as exc:
        states_by_year = available_states_by_year()
        raw_year = str(fd.get("tax_year", "") or "")
        # Must not raise inside the error handler: a non-numeric year would
        # replace the form re-render with a raw plaintext 400.
        posted_year = int(raw_year) if raw_year.isdigit() else 0
        if posted_year in available_years:
            default_year = posted_year
        else:
            default_year = 2024 if 2024 in available_years else max(available_years, default=0)
        response = _templates(request).TemplateResponse(
            request,
            "pages/calculate.html",
            {
                "csrf": csrf,
                "available_years": available_years,
                "available_states": states_by_year.get(default_year, []),
                "available_states_by_year": states_by_year,
                "default_year": default_year,
                "default_filing": str(fd.get("filing_status", "")),
                "pack_variants": list_rule_packs(),
                "error": str(exc),
            },
            status_code=400,
        )
        response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return response


@router.get("/whatif", response_class=HTMLResponse)
def whatif_form(request: Request) -> Response:
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/whatif.html",
        {"csrf": csrf, "available_years": available_years, "selected_year": 2024},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/whatif", response_class=HTMLResponse)
async def whatif_submit(request: Request) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    csrf = get_csrf_token(request)
    raw_year = str(fd.get("tax_year", "2024") or "2024")
    selected_year = int(raw_year) if raw_year.isdigit() else 2024
    context: dict[str, Any] = {
        "csrf": csrf,
        "available_years": available_years,
        "selected_year": selected_year,
    }
    status_code = 200
    try:
        inputs = parse_tax_input_from_form(fd, available_years)
        context["comparison"] = WhatIfEngine(get_federal_pack(inputs.tax_year)).compare_filing_status(inputs)
        context["selected_year"] = inputs.tax_year
    except ValueError as exc:
        context["error"] = str(exc)
        status_code = 400

    response = _templates(request).TemplateResponse(
        request,
        "pages/whatif.html",
        context,
        status_code=status_code,
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response

