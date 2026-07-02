# SPDX-License-Identifier: AGPL-3.0-or-later
"""Saved-run listing, comparison, detail, and annotation routes."""

from __future__ import annotations

from math import ceil
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.db_state import load_run_from_row, locked_database_response
from app.route_helpers.form_parsing import MAX_NOTES, form_str
from app.services.database import (
    delete_return_run,
    get_return_run,
    list_return_runs,
    update_run_annotation,
)
from app.services.form_mapper import map_return_run

router = APIRouter(tags=["runs"])


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


_RUNS_PAGE_SIZE = 25


@router.get("/runs", response_class=HTMLResponse)
def past_runs(request: Request, page: int = 1) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    page = max(1, page)
    runs, total_count = list_return_runs(page=page, page_size=_RUNS_PAGE_SIZE)
    total_pages = max(1, ceil(total_count / _RUNS_PAGE_SIZE))
    if page > total_pages:
        # Past-the-end pages redirect to the last real page instead of
        # rendering an empty table.
        return RedirectResponse(url=f"/runs?page={total_pages}", status_code=303)

    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/runs.html",
        {
            "runs": runs,
            "csrf": csrf,
            "page": page,
            "page_size": _RUNS_PAGE_SIZE,
            "total_pages": total_pages,
            "total_count": total_count,
            "showing_start": (page - 1) * _RUNS_PAGE_SIZE + 1 if total_count else 0,
            "showing_end": (page - 1) * _RUNS_PAGE_SIZE + len(runs),
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get("/runs/compare", response_class=HTMLResponse)
def compare_runs(request: Request, a: str = "", b: str = "") -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    if not a or not b:
        return HTMLResponse("Two run IDs are required (a= and b=)", status_code=400)
    run_a_data = get_return_run(a)
    run_b_data = get_return_run(b)
    if not run_a_data or not run_b_data:
        return HTMLResponse("One or both runs not found", status_code=404)

    run_a = load_run_from_row(run_a_data)
    run_b = load_run_from_row(run_b_data)
    output_fields = [
        "gross_income",
        "agi",
        "standard_deduction",
        "itemized_deductions",
        "deduction_applied",
        "taxable_income",
        "tax_before_credits",
        "child_tax_credit",
        "total_credits",
        "federal_tax",
        "total_withholding",
        "estimated_tax_payments",
        "total_payments",
        "refund_or_owed",
    ]
    output_diffs: list[dict[str, Any]] = []
    for field in output_fields:
        val_a = getattr(run_a.output, field)
        val_b = getattr(run_b.output, field)
        delta = val_b - val_a
        output_diffs.append(
            {
                "field": field,
                "val_a": val_a,
                "val_b": val_b,
                "delta": delta,
                "delta_abs": abs(delta),
                "delta_sign": "positive" if delta > 0 else ("negative" if delta < 0 else "zero"),
                "is_refund_field": field == "refund_or_owed",
            }
        )
    return _templates(request).TemplateResponse(
        request,
        "pages/run_compare.html",
        {"run_a": run_a, "run_b": run_b, "output_diffs": output_diffs},
    )


@router.get("/runs/{run_id}", response_class=HTMLResponse)
def view_run(request: Request, run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)

    return _templates(request).TemplateResponse(
        request,
        "pages/dashboard.html",
        {"run": load_run_from_row(run_data), "is_latest": False},
    )


@router.get("/runs/{run_id}/audit", response_class=HTMLResponse)
def view_run_audit(request: Request, run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)

    return _templates(request).TemplateResponse(
        request,
        "pages/audit_trace.html",
        {"run": load_run_from_row(run_data)},
    )


@router.get("/runs/{run_id}/forms", response_class=HTMLResponse)
def view_run_forms(request: Request, run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = load_run_from_row(run_data)
    return _templates(request).TemplateResponse(
        request,
        "pages/forms_view.html",
        {"run": run, "packet": map_return_run(run)},
    )


@router.post("/runs/{run_id}/delete")
async def delete_run(request: Request, run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_return_run(run_id)
    return RedirectResponse(url="/runs", status_code=303)


@router.post("/runs/{run_id}/annotate")
async def annotate_run(request: Request, run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    notes = str(fd.get("notes", "")).strip()
    if len(notes) > MAX_NOTES:
        raise ValueError(f"Notes exceed {MAX_NOTES} characters")
    found = update_run_annotation(run_id, form_str(fd, "tags"), notes)
    if not found:
        return PlainTextResponse(f"Run {run_id!r} not found", status_code=404)
    return RedirectResponse(url="/runs", status_code=303)

