# SPDX-License-Identifier: AGPL-3.0-or-later
"""Static navigation routes."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["navigation"])


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/legal", response_class=HTMLResponse)
def legal_notices(request: Request) -> HTMLResponse:
    """Display third-party license and legal notices."""
    return _templates(request).TemplateResponse(request, "pages/legal.html", {})

