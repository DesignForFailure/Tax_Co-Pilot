# SPDX-License-Identifier: AGPL-3.0-or-later
"""CSV import, run export, backup, and restore routes."""

from __future__ import annotations

import io
import json
import os
import sqlite3 as sqlite3_stdlib
import tempfile
from contextlib import closing
from pathlib import Path
from typing import Any, cast

from fastapi import APIRouter, Request
from fastapi.responses import (
    HTMLResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates
from starlette.datastructures import UploadFile

from app.config import config as encryption_config
from app.log import get_logger
from app.models.domain import ReturnRun
from app.route_helpers.csrf import get_csrf_token, verify_csrf
from app.route_helpers.db_state import load_run_from_row, locked_database_response
from app.route_helpers.form_parsing import (
    MAX_IMPORT_BYTES,
    MAX_IMPORT_ENTRIES,
    MAX_RESTORE_BYTES,
    sanitize_filename,
)
from app.route_helpers.pack_cache import federal_cache
from app.services.audit_export import generate_audit_html
from app.services.csv_import import import_csv as import_csv_records
from app.services.database import (
    DB_PATH,
    get_connection,
    get_return_run,
    init_db,
    list_all_return_runs,
    save_return_run,
)
from app.services.encryption import DatabaseState, detect_encryption_state
from app.services.form_mapper import map_return_run

router = APIRouter(tags=["import-export"])

logger = get_logger(__name__)


def _templates(request: Request) -> Jinja2Templates:
    return cast(Jinja2Templates, request.app.state.templates)


@router.get("/import-csv", response_class=HTMLResponse)
def import_csv_form(request: Request) -> Response:
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/import_csv.html",
        {"csrf": csrf},
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.post("/import-csv", response_class=HTMLResponse)
async def import_csv_submit(request: Request) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    csv_text = str(fd.get("csv_text", "") or "")
    if len(csv_text.encode("utf-8", errors="ignore")) > MAX_IMPORT_BYTES:
        return HTMLResponse(
            f"CSV text too large (max {MAX_IMPORT_BYTES // (1024 * 1024)} MB)",
            status_code=400,
        )
    record_type = str(fd.get("record_type", "W2") or "W2")
    records_raw, errors = import_csv_records(csv_text, record_type)
    logger.info(
        "CSV import: record_type=%s, count=%d, error_count=%d",
        record_type,
        len(records_raw),
        len(errors),
    )
    csrf = get_csrf_token(request)
    response = _templates(request).TemplateResponse(
        request,
        "pages/import_csv.html",
        {
            "csrf": csrf,
            "records": [record.model_dump() for record in records_raw],
            "errors": errors,
            "record_type": record_type,
            "csv_text": csv_text,
        },
    )
    response.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return response


@router.get("/runs/{run_id}/export/json")
def export_run_json(run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = load_run_from_row(run_data)
    json_bytes = json.dumps(
        json.loads(run.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="run_{sanitize_filename(run_id)}.json"'},
    )


@router.get("/runs/{run_id}/export/html")
def export_run_html(run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = load_run_from_row(run_data)
    return StreamingResponse(
        io.BytesIO(generate_audit_html(run).encode("utf-8")),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="audit_{sanitize_filename(run_id)}.html"'},
    )


@router.get("/runs/{run_id}/export/forms")
def export_run_forms(run_id: str) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    packet = map_return_run(load_run_from_row(run_data))
    json_bytes = json.dumps(
        json.loads(packet.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="forms_{sanitize_filename(run_id)}.json"'},
    )


@router.get("/export-all")
def export_all_runs() -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    hydrated: list[dict[str, Any]] = []
    for row in list_all_return_runs():
        try:
            hydrated.append(json.loads(load_run_from_row(row).model_dump_json()))
        except Exception:
            logger.warning("Export-all: failed to hydrate run %s", row.get("id"), exc_info=True)
            hydrated.append({"error": f"Failed to hydrate run {row.get('id', '?')}", "id": row.get("id")})
    return Response(
        content=json.dumps(hydrated, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=tax_copilot_runs.json"},
    )


@router.post("/import-returns", response_class=HTMLResponse)
async def import_returns(request: Request) -> Response:
    locked_response = locked_database_response()
    if locked_response is not None:
        return locked_response

    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    upload = fd.get("file")
    if not isinstance(upload, UploadFile):
        return HTMLResponse("No file uploaded", status_code=400)
    raw_bytes = await upload.read()
    if len(raw_bytes) > MAX_IMPORT_BYTES:
        return HTMLResponse(f"File too large (max {MAX_IMPORT_BYTES // (1024 * 1024)} MB)", status_code=400)
    try:
        content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return HTMLResponse("File must be UTF-8 encoded JSON", status_code=400)
    try:
        entries = json.loads(content)
    except json.JSONDecodeError as exc:
        return PlainTextResponse(f"Invalid JSON: {exc}", status_code=400)
    if not isinstance(entries, list):
        return HTMLResponse("Expected a JSON array", status_code=400)
    if len(entries) > MAX_IMPORT_ENTRIES:
        return HTMLResponse(f"Too many entries (max {MAX_IMPORT_ENTRIES})", status_code=400)

    imported = 0
    errors: list[str] = []
    for idx, entry in enumerate(entries):
        try:
            run = ReturnRun(**entry)
            expected_pack = federal_cache.get(run.tax_year)
            if expected_pack and run.rule_pack_checksum and run.rule_pack_checksum != expected_pack.checksum:
                errors.append(f"Entry {idx}: checksum mismatch (pack may differ)")
                continue
            if get_return_run(run.id):
                errors.append(f"Entry {idx}: run {run.id!r} already exists, skipped")
                continue
            save_return_run(json.loads(run.model_dump_json()))
            imported += 1
        except Exception as exc:
            logger.warning("Bulk import: entry %d rejected: %s", idx, exc)
            errors.append(f"Entry {idx}: {exc}")

    logger.info(
        "Bulk import complete: imported=%d, skipped_or_errors=%d", imported, len(errors)
    )
    result = f"Imported {imported} run(s)."
    if errors:
        result += f" {len(errors)} error(s): " + "; ".join(errors[:5])
    return PlainTextResponse(result, status_code=200)


@router.get("/backup")
def backup_database() -> Response:
    if not DB_PATH.exists():
        return HTMLResponse("No database file found", status_code=404)
    try:
        with closing(get_connection()) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception:
        logger.warning("Backup: WAL checkpoint failed", exc_info=True)
        wal_path = Path(str(DB_PATH) + "-wal")
        if wal_path.exists() and wal_path.stat().st_size > 0:
            # Serving only the main file now would silently omit committed
            # transactions still sitting in the write-ahead log.
            return HTMLResponse(
                "Backup unavailable: recent changes are still in the "
                "write-ahead log and could not be flushed. Unlock the "
                "database and try again.",
                status_code=409,
            )
    logger.info("Backup downloaded (db=%s)", DB_PATH.name)
    return Response(
        content=DB_PATH.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{DB_PATH.name}"'},
    )


@router.post("/restore", response_class=HTMLResponse)
async def restore_database(request: Request) -> Response:
    fd = await request.form()
    verify_csrf(request, str(fd.get("csrf_token", "")))
    locked = locked_database_response()
    if locked is not None:
        # A locked encrypted database must never be silently replaced —
        # restoring requires the active password to verify the result.
        return locked
    upload = fd.get("file")
    if not isinstance(upload, UploadFile):
        return HTMLResponse("No file uploaded", status_code=400)
    content = await upload.read()
    if len(content) > MAX_RESTORE_BYTES:
        return HTMLResponse(
            f"File too large (max {MAX_RESTORE_BYTES // (1024 * 1024)} MB)",
            status_code=400,
        )
    is_plaintext_sqlite = content[:16].startswith(b"SQLite format 3")
    if not is_plaintext_sqlite and not encryption_config.enabled:
        return HTMLResponse("Not a valid SQLite database file", status_code=400)
    if (
        is_plaintext_sqlite
        and encryption_config.enabled
        and detect_encryption_state(DB_PATH) == DatabaseState.ENCRYPTED_SQLCIPHER
    ):
        # Silently swapping an encrypted database for a plaintext upload
        # would irreversibly downgrade encryption-at-rest.
        logger.warning("Restore rejected: plaintext backup over an encrypted database")
        return HTMLResponse(
            "Refusing to overwrite the encrypted database with an unencrypted "
            "backup. Import the runs via Import Returns instead, or disable "
            "encryption first.",
            status_code=400,
        )

    if is_plaintext_sqlite:
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            test_conn = sqlite3_stdlib.connect(tmp_path)
            result = test_conn.execute("PRAGMA integrity_check").fetchone()
            test_conn.close()
            if not result or result[0] != "ok":
                logger.warning("Restore rejected: uploaded file failed integrity check")
                return HTMLResponse(
                    "Uploaded file is not a valid SQLite database", status_code=400
                )
        except Exception:
            logger.warning(
                "Restore rejected: uploaded file is not readable as SQLite", exc_info=True
            )
            return HTMLResponse("Uploaded file is not a valid SQLite database", status_code=400)
        finally:
            Path(tmp_path).unlink(missing_ok=True)
    # else: with encryption enabled the upload may be a SQLCipher backup,
    # whose header is indistinguishable from random bytes. init_db() below
    # verifies it with the active password; failure rolls back.

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_copy = DB_PATH.with_suffix(".pre_restore_backup") if DB_PATH.exists() else None
    if backup_copy:
        import shutil

        shutil.copy2(DB_PATH, backup_copy)

    # Write to a temp file in the same directory and swap atomically, and
    # drop stale WAL/SHM sidecars: the app runs in WAL mode, and replacing
    # only the main file could let SQLite replay the OLD database's WAL
    # frames into the restored file on next open.
    with tempfile.NamedTemporaryFile(
        dir=DB_PATH.parent, suffix=".restore.tmp", delete=False
    ) as tmp:
        tmp.write(content)
        tmp.flush()
        os.fsync(tmp.fileno())
        staged_path = Path(tmp.name)
    for suffix in ("-wal", "-shm"):
        Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
    os.replace(staged_path, DB_PATH)

    try:
        init_db()
    except Exception as exc:
        logger.exception("Restore failed; original database preserved")
        if backup_copy and backup_copy.exists():
            for suffix in ("-wal", "-shm"):
                Path(str(DB_PATH) + suffix).unlink(missing_ok=True)
            os.replace(backup_copy, DB_PATH)
        return PlainTextResponse(
            f"Restore failed — original database has been preserved. Error: {exc}. "
            "If the backup is encrypted, ensure the same password is active.",
            status_code=400,
        )
    if backup_copy and backup_copy.exists():
        backup_copy.unlink(missing_ok=True)
    logger.info("Database restored from uploaded backup")
    return RedirectResponse(url="/runs", status_code=303)
