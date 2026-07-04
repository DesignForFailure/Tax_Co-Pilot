# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule-pack list, import, detail, and editor routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.engine.rule_loader import RulePackError
from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.form_parsing import (
    constant_groups_from_form,
    constant_view_groups,
    form_str,
    matrix_view_from_rule,
    parse_constant_form,
    parse_rule_form,
    sum_items_from_rule,
)
from app.route_helpers.pack_cache import available_years, bust_pack_cache, get_federal_pack
from app.services.ai_prompt import build_authoring_prompt
from app.services.ref_catalog import (
    FILING_STATUS_KEY_REF,
    constants_table_paths,
    input_ref_options,
)
from app.services.rule_pack_editor import (
    clone_pack,
    create_empty_pack,
    delete_constant,
    delete_pack,
    delete_rule,
    export_yaml,
    load_pack_detail,
    save_constant,
    save_rule,
    split_combined_yaml,
)
from app.services.rule_pack_editor import (
    import_yaml as import_rule_yaml,
)
from app.services.rule_pack_editor import (
    list_all_packs as list_rule_packs,
)
from app.services.rule_pack_editor import (
    validate_pack as validate_rule_pack,
)

router = APIRouter(tags=["rule-packs"])


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


def _ref_catalog(detail: dict[str, Any], jurisdiction: str, year: int) -> dict[str, list[str]]:
    """Autocomplete options for the rule editor's reference inputs."""
    refs = set(input_ref_options(jurisdiction))
    refs.update(str(rule["id"]) for rule in detail["rules"] if rule.get("id"))
    if jurisdiction.lower() not in {"federal", "fed"}:
        try:
            refs.update(get_federal_pack(year).rule_order)
        except RulePackError:
            # No federal pack for this year — cross-pack targets simply absent.
            pass
    return {
        "ref_options": sorted(refs),
        "key_options": sorted(refs | {FILING_STATUS_KEY_REF}),
        "table_options": constants_table_paths(detail.get("constants", {}) or {}),
    }


def _default_matrix_view() -> dict[str, Any]:
    """Seed grid shown when a rule is not (yet) a matrix_lookup."""
    return {
        "key_refs": [FILING_STATUS_KEY_REF, ""],
        "columns": ["0", "1", "2", "3"],
        "rows": [
            {"key": status, "cells": ["", "", "", ""]}
            for status in ("single", "mfj", "mfs", "hoh", "qss")
        ],
    }


def _editor_context(
    request: Request,
    detail: dict[str, Any],
    *,
    rule: dict[str, Any] | None,
    is_new: bool,
    id_prefix: str = "",
    error: str | None = None,
) -> dict[str, Any]:
    """Template context shared by every rule_editor.html render."""
    matrix_view: dict[str, Any] | None = None
    is_matrix = rule is not None and rule.get("type") == "matrix_lookup"
    if is_matrix and rule is not None:
        matrix_view = matrix_view_from_rule(rule)
    sum_view: list[str] | None = [""]
    is_sum = rule is not None and rule.get("type") == "sum"
    if is_sum and rule is not None:
        sum_view = sum_items_from_rule(rule)
    context: dict[str, Any] = {
        "csrf": get_csrf_token(request),
        "pack": detail,
        "rule": rule,
        "is_new": is_new,
        "id_prefix": id_prefix,
        "catalog": _ref_catalog(detail, str(detail["jurisdiction"]), int(detail["year"])),
        "matrix_view": matrix_view or _default_matrix_view(),
        # Shapes that cannot round-trip through the form (a matrix with
        # more than two dimensions, sum items with literals) swap their
        # section for a YAML-export notice instead of mangling the rule.
        "matrix_editable": (not is_matrix) or matrix_view is not None,
        "sum_view": sum_view or [""],
        "sum_editable": (not is_sum) or sum_view is not None,
    }
    if error is not None:
        context["error"] = error
    return context


@router.get("/rule-packs", response_class=HTMLResponse)
def rule_packs_list(request: Request) -> HTMLResponse:
    csrf = get_csrf_token(request)
    packs = list_rule_packs()
    create_jurisdictions = [("federal", "Federal")] + [
        (code, code)
        for code in sorted(
            {
                pack.jurisdiction.upper()
                for pack in packs
                if pack.jurisdiction.lower() != "federal"
            }
        )
    ]
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_packs.html",
        {
            "csrf": csrf,
            "packs": packs,
            "available_years": available_years,
            "create_jurisdictions": create_jurisdictions,
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/create")
async def rule_packs_create(request: Request) -> RedirectResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    raw_year = form_str(fd, "year")
    if not raw_year.isdigit():
        raise ValueError("Year must be a whole number (e.g. 2024)")
    info = create_empty_pack(
        form_str(fd, "jurisdiction"),
        int(raw_year),
        form_str(fd, "custom_name"),
    )
    bust_pack_cache(info.jurisdiction, info.year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@router.get("/rule-packs/import", response_class=HTMLResponse)
def rule_packs_import_form(request: Request) -> HTMLResponse:
    """Render the YAML import form."""
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_pack_import.html",
        {"csrf": csrf, "error": None, "combined_text": "", "custom_name": ""},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/import", response_class=HTMLResponse)
async def rule_packs_import_post(request: Request) -> Response:
    """Handle YAML import — two uploaded files or one pasted combined document."""
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    custom_name = form_str(fd, "custom_name")
    manifest_field = fd.get("manifest_file")
    rules_field = fd.get("rules_file")
    combined_field = fd.get("combined_text")
    combined_text = combined_field.strip() if isinstance(combined_field, str) else ""
    csrf = get_csrf_token(request)
    max_rule_pack_size = 2 * 1024 * 1024

    def render_error(message: str) -> HTMLResponse:
        response = _templates(request).TemplateResponse(
            request,
            "pages/rule_pack_import.html",
            {
                "csrf": csrf,
                "error": message,
                # Preserve the paste so a failed AI round-trip is editable
                # in place instead of forcing a fresh copy from the chat.
                "combined_text": combined_text,
                "custom_name": custom_name,
            },
            status_code=400,
        )
        response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return response

    if combined_text:
        if len(combined_text) > max_rule_pack_size:
            return render_error("Pasted YAML exceeds the 2 MiB size limit.")
        try:
            manifest_bytes, rules_bytes = split_combined_yaml(combined_text)
            info = import_rule_yaml(manifest_bytes, rules_bytes, custom_name)
        except ValueError as exc:
            return render_error(str(exc))
        bust_pack_cache(info.jurisdiction, info.year)
        return RedirectResponse(
            url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
            status_code=303,
        )

    if not isinstance(manifest_field, UploadFile) or not isinstance(rules_field, UploadFile):
        return render_error(
            "Either paste a combined YAML document or upload both "
            "manifest_file and rules_file."
        )

    manifest_bytes = await manifest_field.read()
    rules_bytes = await rules_field.read()
    if len(manifest_bytes) > max_rule_pack_size or len(rules_bytes) > max_rule_pack_size:
        return render_error("Uploaded file exceeds the 2 MiB size limit.")

    try:
        info = import_rule_yaml(manifest_bytes, rules_bytes, custom_name)
    except ValueError as exc:
        return render_error(str(exc))

    bust_pack_cache(info.jurisdiction, info.year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@router.get("/rule-packs/ai-assist", response_class=HTMLResponse)
def rule_packs_ai_assist_form(request: Request) -> HTMLResponse:
    """Render the AI authoring assistant (prompt generator) page."""
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_pack_ai_assist.html",
        {
            "csrf": csrf,
            "error": None,
            "prompt": None,
            "jurisdiction": "federal",
            "year": max(available_years) if available_years else 2024,
            "description": "",
            "known_jurisdictions": _known_jurisdictions(),
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/ai-assist", response_class=HTMLResponse)
async def rule_packs_ai_assist_post(request: Request) -> HTMLResponse:
    """Generate the copy-paste authoring prompt. Local only — no AI is called."""
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    csrf = get_csrf_token(request)
    jurisdiction = form_str(fd, "jurisdiction")
    raw_year = form_str(fd, "year")
    description_field = fd.get("description")
    description = description_field if isinstance(description_field, str) else ""

    prompt: str | None = None
    error: str | None = None
    if not raw_year.isdigit():
        error = "Year must be a whole number (e.g. 2024)"
    else:
        try:
            prompt = build_authoring_prompt(jurisdiction, int(raw_year), description)
        except ValueError as exc:
            error = str(exc)

    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_pack_ai_assist.html",
        {
            "csrf": csrf,
            "error": error,
            "prompt": prompt,
            "jurisdiction": jurisdiction,
            "year": raw_year,
            "description": description,
            "known_jurisdictions": _known_jurisdictions(),
        },
        status_code=400 if error else 200,
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


def _known_jurisdictions() -> list[str]:
    """Jurisdictions with shipped packs, for the ai-assist datalist."""
    codes = {
        pack.jurisdiction.upper()
        for pack in list_rule_packs()
        if pack.jurisdiction.lower() != "federal"
    }
    return ["federal"] + sorted(codes)


@router.get("/rule-packs/{jurisdiction}/{year}/{variant}", response_class=HTMLResponse)
def rule_pack_detail(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
) -> HTMLResponse:
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_pack_detail.html",
        {"csrf": csrf, "pack": load_pack_detail(jurisdiction, year, variant)},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/clone")
async def rule_pack_clone(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
) -> RedirectResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    info = clone_pack(jurisdiction, year, variant, form_str(fd, "custom_name"))
    bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/delete")
async def rule_pack_delete(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
) -> RedirectResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_pack(jurisdiction, year, variant)
    bust_pack_cache(jurisdiction, year)
    return RedirectResponse(url="/rule-packs", status_code=303)


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/validate", response_class=HTMLResponse)
async def rule_pack_validate(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
) -> HTMLResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_pack_detail.html",
        {
            "csrf": csrf,
            "pack": load_pack_detail(jurisdiction, year, variant),
            "validation_errors": validate_rule_pack(jurisdiction, year, variant),
            "validated": True,
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get("/rule-packs/{jurisdiction}/{year}/{variant}/export")
def rule_pack_export(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
) -> Response:
    try:
        manifest_bytes, rules_bytes = export_yaml(jurisdiction, year, variant)
    except ValueError:
        return PlainTextResponse(
            f"Rule pack not found: {jurisdiction}/{year}/{variant}", status_code=404
        )
    filename = f"{jurisdiction}_{year}_{variant}.yaml"
    return Response(
        content=b"# === MANIFEST ===\n" + manifest_bytes + b"\n# === RULES ===\n" + rules_bytes,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/rule-packs/{jurisdiction}/{year}/{variant}/rules/add", response_class=HTMLResponse)
def rule_add_form(request: Request, jurisdiction: str, year: int, variant: str) -> HTMLResponse:
    detail = load_pack_detail(jurisdiction, year, variant)
    id_prefix = "fed." if jurisdiction.lower() in {"federal", "fed"} else f"{jurisdiction.lower()}."
    id_prefix += f"{year}."
    context = _editor_context(request, detail, rule=None, is_new=True, id_prefix=id_prefix)
    response = _templates(request).TemplateResponse(request, "pages/rule_editor.html", context)
    response.set_cookie("csrf", str(context["csrf"]), httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/add")
async def rule_add_submit(request: Request, jurisdiction: str, year: int, variant: str) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    rule_data = parse_rule_form(fd)
    try:
        save_rule(jurisdiction, year, variant, str(rule_data["id"]), rule_data)
        bust_pack_cache(jurisdiction, year)
        return RedirectResponse(
            url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
            status_code=303,
        )
    except ValueError as exc:
        detail = load_pack_detail(jurisdiction, year, variant)
        context = _editor_context(
            request, detail, rule=rule_data, is_new=True, error=str(exc)
        )
        response = _templates(request).TemplateResponse(
            request, "pages/rule_editor.html", context
        )
        response.set_cookie("csrf", str(context["csrf"]), httponly=True, samesite="strict")
        return response


@router.get("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}", response_class=HTMLResponse)
def rule_edit_form(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
) -> HTMLResponse:
    detail: dict[str, Any] = load_pack_detail(jurisdiction, year, variant)
    rule = next((candidate for candidate in detail["rules"] if candidate["id"] == rule_id), None)
    if rule is None:
        return HTMLResponse(content="Rule not found", status_code=404)
    context = _editor_context(request, detail, rule=rule, is_new=False)
    response = _templates(request).TemplateResponse(request, "pages/rule_editor.html", context)
    response.set_cookie("csrf", str(context["csrf"]), httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}/delete")
async def rule_delete_submit(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
) -> RedirectResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_rule(jurisdiction, year, variant, rule_id)
    bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
        status_code=303,
    )


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}")
async def rule_save_submit(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    rule_data = parse_rule_form(fd)
    try:
        save_rule(jurisdiction, year, variant, rule_id, rule_data)
        bust_pack_cache(jurisdiction, year)
        return RedirectResponse(
            url=f"/rule-packs/{jurisdiction}/{year}/{variant}",
            status_code=303,
        )
    except ValueError as exc:
        detail = load_pack_detail(jurisdiction, year, variant)
        context = _editor_context(
            request, detail, rule=rule_data, is_new=False, error=str(exc)
        )
        response = _templates(request).TemplateResponse(
            request, "pages/rule_editor.html", context
        )
        response.set_cookie("csrf", str(context["csrf"]), httponly=True, samesite="strict")
        return response


def _pack_redirect(jurisdiction: str, year: int, variant: str) -> RedirectResponse:
    """303 back to the pack detail page.

    The segments were already validated by the service call that preceded
    every use (raising before any redirect), so this cannot fire for real
    traffic; the explicit local-path check is the containment barrier
    static URL-redirection analysis recognizes.
    """
    target = f"/rule-packs/{jurisdiction}/{year}/{variant}"
    if not target.startswith("/rule-packs/") or target.startswith("//") or "\\" in target:
        raise ValueError("Unsafe redirect target")
    return RedirectResponse(url=target, status_code=303)


def _constant_editor_response(
    request: Request,
    detail: dict[str, Any],
    *,
    constant_name: str,
    groups: list[dict[str, Any]],
    is_new: bool,
    error: str | None = None,
    editable: bool = True,
) -> HTMLResponse:
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/constant_editor.html",
        {
            "csrf": csrf,
            "pack": detail,
            "constant_name": constant_name,
            "groups": groups,
            "is_new": is_new,
            "error": error,
            # False when the constant's shape cannot round-trip through the
            # filing-status grid — the template shows a YAML-export notice.
            "editable": editable,
        },
        status_code=400 if error else 200,
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get(
    "/rule-packs/{jurisdiction}/{year}/{variant}/constants/add", response_class=HTMLResponse
)
def constant_add_form(
    request: Request, jurisdiction: str, year: int, variant: str
) -> HTMLResponse:
    detail = load_pack_detail(jurisdiction, year, variant)
    return _constant_editor_response(
        request, detail, constant_name="", groups=[], is_new=True
    )


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/constants/add")
async def constant_add_submit(
    request: Request, jurisdiction: str, year: int, variant: str
) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    try:
        name, value = parse_constant_form(fd)
        save_constant(jurisdiction, year, variant, name, value)
    except ValueError as exc:
        detail = load_pack_detail(jurisdiction, year, variant)
        raw_name = str(fd.get("constant_name", "") or "").strip()[:100]
        return _constant_editor_response(
            request,
            detail,
            constant_name=raw_name,
            # Echo what was typed so a rejected save is editable in place.
            groups=constant_groups_from_form(fd),
            is_new=True,
            error=str(exc),
        )
    bust_pack_cache(jurisdiction, year)
    return _pack_redirect(jurisdiction, year, variant)


@router.get(
    "/rule-packs/{jurisdiction}/{year}/{variant}/constants/{name}",
    response_class=HTMLResponse,
)
def constant_edit_form(
    request: Request, jurisdiction: str, year: int, variant: str, name: str
) -> HTMLResponse:
    detail = load_pack_detail(jurisdiction, year, variant)
    value = (detail.get("constants") or {}).get(name)
    if not isinstance(value, dict):
        return HTMLResponse(content="Constant not found", status_code=404)
    groups = constant_view_groups(value)
    return _constant_editor_response(
        request,
        detail,
        constant_name=name,
        groups=groups or [],
        is_new=False,
        editable=groups is not None,
    )


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/constants/{name}")
async def constant_save_submit(
    request: Request, jurisdiction: str, year: int, variant: str, name: str
) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    try:
        # The path segment names the constant being edited; the readonly
        # form field is display-only and never trusted for the write.
        _, value = parse_constant_form(fd)
        save_constant(jurisdiction, year, variant, name, value)
    except ValueError as exc:
        detail = load_pack_detail(jurisdiction, year, variant)
        return _constant_editor_response(
            request,
            detail,
            constant_name=name,
            # Echo what was typed so a rejected save is editable in place.
            groups=constant_groups_from_form(fd),
            is_new=False,
            error=str(exc),
        )
    bust_pack_cache(jurisdiction, year)
    return _pack_redirect(jurisdiction, year, variant)


@router.post("/rule-packs/{jurisdiction}/{year}/{variant}/constants/{name}/delete")
async def constant_delete_submit(
    request: Request, jurisdiction: str, year: int, variant: str, name: str
) -> RedirectResponse:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    # A ValueError (unknown constant, still referenced by a lookup rule)
    # propagates to the global handler as a 400, matching rule deletion.
    delete_constant(jurisdiction, year, variant, name)
    bust_pack_cache(jurisdiction, year)
    return _pack_redirect(jurisdiction, year, variant)

