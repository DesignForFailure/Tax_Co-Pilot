# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database lifecycle and hydration helpers for route modules."""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import HTMLResponse, RedirectResponse

from app import __version__
from app.config import config as encryption_config
from app.log import configure, get_logger
from app.models.domain import ReturnRun
from app.route_helpers.pack_cache import available_years
from app.services.database import (
    DB_PATH,
    get_cached_password,
    init_db,
    list_return_runs,
    set_cached_password,
)
from app.services.encryption import DatabaseState, detect_encryption_state, get_password

logger = get_logger(__name__)


def load_run_from_row(run_data: dict[str, Any]) -> ReturnRun:
    """Hydrate a persisted DB row into a typed ReturnRun."""
    hydrated = dict(run_data)
    hydrated["input_snapshot"] = json.loads(hydrated["input_snapshot_json"])
    hydrated["output"] = json.loads(hydrated["output_json"])
    hydrated["trace"] = json.loads(hydrated["trace_json"])
    hydrated["state_outputs"] = json.loads(hydrated.get("state_outputs_json", "[]"))
    return ReturnRun(**{key: value for key, value in hydrated.items() if not key.endswith("_json")})


def startup() -> None:
    """Initialize logging and the database on application startup."""
    # Logging must be live before any DB or encryption operation runs.
    configure()
    db_state = detect_encryption_state(DB_PATH)
    logger.info(
        "Tax Copilot %s starting (encryption_enabled=%s, db_state=%s, available_years=%s)",
        __version__,
        encryption_config.enabled,
        db_state.value,
        available_years,
    )

    if encryption_config.enabled:
        if db_state == DatabaseState.ENCRYPTED_SQLCIPHER:
            password = get_password(source=encryption_config.password_source)
            if password:
                logger.info(
                    "Startup unlock: password resolved (source=%s)",
                    encryption_config.password_source,
                )
                set_cached_password(password)
                init_db()
            else:
                logger.warning(
                    "Startup unlock deferred: no password available (source=%s); "
                    "web unlock required",
                    encryption_config.password_source,
                )
        elif db_state == DatabaseState.ENCRYPTED_PYTHON:
            logger.error("Startup aborted: Python-layer encrypted database detected")
            raise RuntimeError(
                "Python-layer encrypted databases are unsupported at runtime. "
                "Migrate to SQLCipher encryption."
            )
        else:
            init_db()
    else:
        init_db()


def database_locked() -> bool:
    """Return True when the encrypted database requires an unlock step."""
    if not encryption_config.enabled:
        return False

    db_state = detect_encryption_state(DB_PATH)
    if db_state == DatabaseState.ENCRYPTED_PYTHON:
        raise RuntimeError(
            "Python-layer encrypted databases are unsupported at runtime. "
            "Migrate to SQLCipher encryption."
        )

    return db_state == DatabaseState.ENCRYPTED_SQLCIPHER and not get_cached_password()


def locked_database_response() -> RedirectResponse | HTMLResponse | None:
    """Return a redirect or error response when the database is unavailable."""
    try:
        if database_locked():
            return RedirectResponse(url="/unlock", status_code=303)
    except RuntimeError as exc:
        return HTMLResponse(str(exc), status_code=500)
    return None


def load_latest_run() -> ReturnRun | None:
    """Return the newest saved run, if one exists."""
    runs, _total = list_return_runs(page=1, page_size=1)
    if not runs:
        return None
    return load_run_from_row(runs[0])

