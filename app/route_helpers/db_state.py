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
from app.services.encryption import (
    DatabaseState,
    detect_encryption_state,
    get_password,
    migrate_to_encrypted,
)

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
        elif db_state == DatabaseState.NONE:
            # Fresh install with encryption enabled: the database must be
            # created encrypted, never silently plaintext. Without a password
            # here, creation is deferred to the /unlock bootstrap flow.
            password = get_password(source=encryption_config.password_source)
            if password:
                set_cached_password(password)
                init_db()
                logger.info(
                    "Encrypted database created at startup (source=%s)",
                    encryption_config.password_source,
                )
            else:
                logger.warning(
                    "Encryption enabled but no password available (source=%s); "
                    "database creation deferred to the web unlock page",
                    encryption_config.password_source,
                )
        else:  # DatabaseState.UNENCRYPTED
            # Existing plaintext database with encryption enabled: migrate it
            # now if a password is available (the promised migration path).
            password = get_password(source=encryption_config.password_source)
            if password:
                migrate_to_encrypted(
                    DB_PATH,
                    password,
                    provider_type=encryption_config.provider,
                    kdf_iterations=encryption_config.key_derivation_iterations,
                )
                set_cached_password(password)
                init_db()
                logger.info("Plaintext database migrated to encrypted at startup")
            else:
                logger.warning(
                    "Encryption enabled but the existing database is unencrypted "
                    "and no password is available (source=%s); data remains "
                    "PLAINTEXT until a password is provided via the unlock page",
                    encryption_config.password_source,
                )
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

    if db_state == DatabaseState.NONE:
        # Encryption enabled but no database yet and no password came from
        # env/keyring at startup: creation is deferred to /unlock so the
        # database is never silently created plaintext.
        return not get_cached_password()

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

