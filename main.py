# SPDX-License-Identifier: AGPL-3.0-or-later
# Tax_Co-Pilot - Local-first personal tax software system
# Copyright (C) 2026  Tax_Co-Pilot Contributors
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

"""Tax Copilot FastAPI application wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import PlainTextResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.route_helpers.db_state import startup
from app.route_helpers.pack_cache import warm_caches
from app.routes import (
    calculate_router,
    encryption_router,
    import_export_router,
    navigation_router,
    rule_packs_router,
    runs_router,
)
from app.services.database import clear_cached_password

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.base_dir = BASE_DIR
    app.state.templates = TEMPLATES
    startup()
    warm_caches()
    yield
    clear_cached_password()

app = FastAPI(title="Tax Copilot", version=__version__, lifespan=lifespan)
app.state.base_dir = BASE_DIR
app.state.templates = TEMPLATES
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
    response.headers.setdefault("Content-Security-Policy", _CSP)
    response.headers.setdefault("Cache-Control", "no-store")
    return response


app.include_router(calculate_router)
app.include_router(navigation_router)
app.include_router(runs_router)
app.include_router(import_export_router)
app.include_router(encryption_router)
app.include_router(rule_packs_router)


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> PlainTextResponse:
    return PlainTextResponse(str(exc), status_code=400)
