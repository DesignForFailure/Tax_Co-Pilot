# SPDX-License-Identifier: AGPL-3.0-or-later
"""Database lifecycle and hydration helpers for route modules."""

from __future__ import annotations

import json
from typing import Any

from fastapi.responses import HTMLResponse, RedirectResponse

from app.config import config as encryption_config
from app.models.domain import ReturnRun
from app.services.database import (
    DB_PATH,
    get_cached_password,
    init_db,
    list_return_runs,
    set_cached_password,
)
from app.services.encryption import DatabaseState, detect_encryption_state, get_password


def load_run_from_row(run_data: dict[str, Any]) -> ReturnRun:
    """Hydrate a persisted DB row into a typed ReturnRun."""
    hydrated = dict(run_data)
    hydrated["input_snapshot"] = json.loads(hydrated["input_snapshot_json"])
    hydrated["output"] = json.loads(hydrated["output_json"])
    hydrated["trace"] = json.loads(hydrated["trace_json"])
    hydrated["state_outputs"] = json.loads(hydrated.get("state_outputs_json", "[]"))
    return ReturnRun(**{key: value for key, value in hydrated.items() if not key.endswith("_json")})


def startup() -> None:
    """Initialize the database on application startup."""
    if encryption_config.enabled:
        db_state = detect_encryption_state(DB_PATH)

        if db_state == DatabaseState.ENCRYPTED_SQLCIPHER:
            password = get_password(source=encryption_config.password_source)
            if password:
                set_cached_password(password)
                init_db()
        elif db_state == DatabaseState.ENCRYPTED_PYTHON:
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
    runs = list_return_runs()
    if not runs:
        return None
    return load_run_from_row(runs[0])

