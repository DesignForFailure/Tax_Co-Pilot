# SPDX-License-Identifier: AGPL-3.0-or-later
"""Rule-pack list, import, detail, and editor routes."""

from __future__ import annotations

from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.form_parsing import form_str, parse_rule_form
from app.route_helpers.pack_cache import available_years, bust_pack_cache
from app.services.rule_pack_editor import (
    clone_pack,
    create_empty_pack,
    delete_pack,
    delete_rule,
    export_yaml,
    load_pack_detail,
    save_rule,
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
        {"csrf": csrf, "error": None},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rule-packs/import", response_class=HTMLResponse)
async def rule_packs_import_post(request: Request) -> Response:
    """Handle YAML file upload and import as a new custom pack."""
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    custom_name = form_str(fd, "custom_name")
    manifest_field = fd.get("manifest_file")
    rules_field = fd.get("rules_file")
    csrf = get_csrf_token(request)

    def render_error(message: str) -> HTMLResponse:
        response = _templates(request).TemplateResponse(
            request,
            "pages/rule_pack_import.html",
            {"csrf": csrf, "error": message},
            status_code=400,
        )
        response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return response

    if not isinstance(manifest_field, UploadFile) or not isinstance(rules_field, UploadFile):
        return render_error("Both manifest_file and rules_file are required.")

    max_rule_pack_size = 2 * 1024 * 1024
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
    csrf = get_csrf_token(request)
    detail = load_pack_detail(jurisdiction, year, variant)
    id_prefix = "fed." if jurisdiction.lower() in {"federal", "fed"} else f"{jurisdiction.lower()}."
    id_prefix += f"{year}."
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_editor.html",
        {
            "csrf": csrf,
            "pack": detail,
            "rule": None,
            "is_new": True,
            "id_prefix": id_prefix,
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
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
        csrf = get_csrf_token(request)
        response = _templates(request).TemplateResponse(
            request,
            "pages/rule_editor.html",
            {
                "csrf": csrf,
                "pack": load_pack_detail(jurisdiction, year, variant),
                "rule": rule_data,
                "is_new": True,
                "error": str(exc),
                "id_prefix": "",
            },
        )
        response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return response


@router.get("/rule-packs/{jurisdiction}/{year}/{variant}/rules/{rule_id}", response_class=HTMLResponse)
def rule_edit_form(
    request: Request,
    jurisdiction: str,
    year: int,
    variant: str,
    rule_id: str,
) -> HTMLResponse:
    csrf = get_csrf_token(request)
    detail: dict[str, Any] = load_pack_detail(jurisdiction, year, variant)
    rule = next((candidate for candidate in detail["rules"] if candidate["id"] == rule_id), None)
    if rule is None:
        return HTMLResponse(content="Rule not found", status_code=404)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rule_editor.html",
        {
            "csrf": csrf,
            "pack": detail,
            "rule": rule,
            "is_new": False,
            "id_prefix": "",
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
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
        csrf = get_csrf_token(request)
        response = _templates(request).TemplateResponse(
            request,
            "pages/rule_editor.html",
            {
                "csrf": csrf,
                "pack": load_pack_detail(jurisdiction, year, variant),
                "rule": rule_data,
                "is_new": False,
                "error": str(exc),
                "id_prefix": "",
            },
        )
        response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
        return response

