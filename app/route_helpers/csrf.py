# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSRF helpers for double-submit-cookie validation."""

from __future__ import annotations

import secrets

from fastapi import Request

from app.log import get_logger

logger = get_logger(__name__)


def get_csrf_token(request: Request) -> str:
    """Return the current CSRF token or mint one."""
    token = request.cookies.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
    return token


def verify_csrf(request: Request, form_token: str) -> None:
    """Validate the submitted CSRF token."""
    cookie_token = request.cookies.get("csrf")
    # Compare bytes: compare_digest raises TypeError (a 500) on non-ASCII str.
    if not cookie_token or not secrets.compare_digest(
        cookie_token.encode("utf-8"), (form_token or "").encode("utf-8")
    ):
        logger.warning("CSRF validation failed (path=%s)", request.url.path)
        raise ValueError("CSRF validation failed")

