# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database unlock, key rotation, and audit verification routes."""

from __future__ import annotations

import json
import secrets
import urllib.parse
from typing import cast

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.db_state import locked_database_response
from app.services.database import (
    DB_PATH,
    get_cached_password,
    get_connection,
    init_db,
    set_cached_password,
    verify_chain,
)
from app.services.encryption import (
    DatabaseState,
    PasswordValidationError,
    detect_encryption_state,
    rotate_key,
    set_password_in_keyring,
    validate_password,
)

router = APIRouter(tags=["encryption"])


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/unlock", response_class=HTMLResponse)
def unlock_form(request: Request, error: str | None = None) -> HTMLResponse:
    """Show the password-unlock form for encrypted databases."""
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/unlock.html",
        {"csrf": csrf, "error": error},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/unlock")
def unlock_submit(
    request: Request,
    password: str = Form(""),
    csrf_token: str = Form(""),
) -> RedirectResponse:
    """Handle password unlock submission."""
    verify_csrf(request, csrf_token)

    if not password:
        return RedirectResponse(
            url=f"/unlock?error={urllib.parse.quote_plus('Password is required')}",
            status_code=303,
        )

    try:
        validate_password(password)

        db_state = detect_encryption_state(DB_PATH)
        if db_state == DatabaseState.ENCRYPTED_PYTHON:
            return RedirectResponse(
                url="/unlock?error=Python-layer+encryption+is+unsupported;+use+SQLCipher",
                status_code=303,
            )
        if db_state != DatabaseState.ENCRYPTED_SQLCIPHER:
            return RedirectResponse(
                url="/unlock?error=Database+is+not+encrypted",
                status_code=303,
            )

        conn = get_connection(password=password)
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()

        set_cached_password(password)
        set_password_in_keyring(password)
        init_db()

        response = RedirectResponse(url="/dashboard", status_code=303)
        response.set_cookie("csrf", secrets.token_urlsafe(32), httponly=True, samesite="strict")
        return response
    except PasswordValidationError as exc:
        return RedirectResponse(
            url=f"/unlock?error={urllib.parse.quote_plus(str(exc)[:100])}",
            status_code=303,
        )
    except ValueError:
        return RedirectResponse(
            url=f"/unlock?error={urllib.parse.quote_plus('Incorrect password or corrupted database')}",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/unlock?error={urllib.parse.quote_plus(f'Unlock failed: {str(exc)[:50]}')}",
            status_code=303,
        )


@router.get("/rotate-key", response_class=HTMLResponse)
def rotate_key_form(
    request: Request,
    error: str | None = None,
    success: str | None = None,
) -> Response:
    """Show the key-rotation form."""
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/rotate_key.html",
        {"csrf": csrf, "error": error, "success": success},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/rotate-key")
async def rotate_key_submit(request: Request) -> RedirectResponse:
    """Handle key rotation."""
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))

    current_password = str(fd.get("current_password", ""))
    new_password = str(fd.get("new_password", ""))
    confirm = str(fd.get("confirm_new_password", ""))

    if not current_password or not new_password:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('All fields are required')}",
            status_code=303,
        )
    if new_password != confirm:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('New passwords do not match')}",
            status_code=303,
        )
    if not secrets.compare_digest(current_password, get_cached_password() or ""):
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('Current password is incorrect')}",
            status_code=303,
        )
    if secrets.compare_digest(current_password, new_password):
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('New password must differ from current password')}",
            status_code=303,
        )

    try:
        validate_password(new_password)
        rotate_key(current_password, new_password)
        set_cached_password(new_password)
        set_password_in_keyring(new_password)
        return RedirectResponse(
            url=f"/rotate-key?success={urllib.parse.quote_plus('Key rotated successfully')}",
            status_code=303,
        )
    except Exception as exc:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus(str(exc)[:100])}",
            status_code=303,
        )


@router.get("/audit/verify")
def audit_verify() -> Response:
    """Walk the hash chain and report integrity status."""
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    errors = verify_chain()
    return Response(
        content=json.dumps({"status": "ok" if not errors else "integrity_errors", "errors": errors}, indent=2),
        media_type="application/json",
    )

