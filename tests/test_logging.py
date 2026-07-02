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

"""Structured logging tests (Milestone 13).

Covers the app.log configuration module, security-event log entries for
run lifecycle / unlock / CSRF / hash verification, and a source-level
guard asserting that no ``except Exception`` block swallows an error
without a logger call.
"""

import ast
import logging
import logging.handlers
import sys
import types
from contextlib import closing
from pathlib import Path

import pytest

from app import __version__
from app.log import LOGGER_NAME, configure, get_logger
from app.route_helpers.db_state import startup
from app.services.database import (
    delete_return_run,
    get_connection,
    init_db,
    save_return_run,
    verify_chain,
)
from app.services.encryption import (
    PasswordValidationError,
    get_password_from_keyring,
    set_password_in_keyring,
    validate_password,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _owned_handlers(logger: logging.Logger) -> list[logging.Handler]:
    return [h for h in logger.handlers if getattr(h, "_tax_copilot_owned", False)]


@pytest.fixture(autouse=True)
def _restore_logging_config():  # type: ignore[no-untyped-def]
    """Reconfigure from the (test-clean) environment after each test."""
    yield
    configure()


def _run(run_id: str, created_at: str) -> dict:
    return {
        "id": run_id,
        "tax_year": 2024,
        "filing_status": "single",
        "scenario_name": "baseline",
        "rule_pack_version": "1.0.0",
        "rule_pack_checksum": "abc",
        "created_at": created_at,
        "input_snapshot": {"tax_year": 2024},
        "output": {"agi": "1000"},
        "trace": [],
        "state_outputs": [],
    }


@pytest.fixture()
def _clean_db():  # type: ignore[no-untyped-def]
    init_db()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")
    yield
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")


# ─── app.log configuration ─────────────────────────────────────


def test_configure_is_idempotent() -> None:
    configure()
    configure()
    logger = logging.getLogger(LOGGER_NAME)
    assert len(_owned_handlers(logger)) == 1


def test_configure_default_level_is_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAX_COPILOT_LOG_LEVEL", raising=False)
    logger = configure()
    assert logger.level == logging.INFO


def test_configure_level_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAX_COPILOT_LOG_LEVEL", "DEBUG")
    logger = configure()
    assert logger.level == logging.DEBUG


def test_configure_invalid_level_falls_back_to_info(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TAX_COPILOT_LOG_LEVEL", "NOT_A_LEVEL")
    logger = configure()
    assert logger.level == logging.INFO


def test_configure_file_handler(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "app.log"
    monkeypatch.setenv("TAX_COPILOT_LOG_FILE", str(log_path))
    logger = configure()
    file_handlers = [
        h for h in _owned_handlers(logger)
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    logger.info("file handler smoke test")
    file_handlers[0].flush()
    assert log_path.exists()
    assert "file handler smoke test" in log_path.read_text(encoding="utf-8")


def test_configure_no_file_handler_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TAX_COPILOT_LOG_FILE", raising=False)
    logger = configure()
    assert not any(
        isinstance(h, logging.handlers.RotatingFileHandler) for h in _owned_handlers(logger)
    )


def test_get_logger_namespacing() -> None:
    assert get_logger("app.services.database").name == "tax_copilot.services.database"
    assert get_logger("app.log").name == "tax_copilot.log"


# ─── Security event logging ────────────────────────────────────


def test_startup_logs_version_state_and_years(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        startup()
    text = caplog.text
    assert f"Tax Copilot {__version__} starting" in text
    assert "encryption_enabled=" in text
    assert "db_state=" in text
    assert "available_years=" in text


def test_run_creation_and_deletion_are_logged(
    _clean_db: None, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        save_return_run(_run("log-run-1", "2024-06-01T00:00:00Z"))
        delete_return_run("log-run-1")
    assert "Return run created (id=log-run-1, tax_year=2024, filing_status=single)" in caplog.text
    assert "Return run deleted (id=log-run-1)" in caplog.text


def test_verify_chain_logs_pass(_clean_db: None, caplog: pytest.LogCaptureFixture) -> None:
    save_return_run(_run("log-run-2", "2024-06-01T00:00:00Z"))
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        assert verify_chain() == []
    assert "Hash chain verification passed (1 run(s))" in caplog.text


def test_verify_chain_logs_failure(_clean_db: None, caplog: pytest.LogCaptureFixture) -> None:
    save_return_run(_run("log-run-3", "2024-06-01T00:00:00Z"))
    with closing(get_connection()) as conn:
        conn.execute(
            "UPDATE return_runs SET integrity_hash = 'bogus' WHERE id = ?", ("log-run-3",)
        )
    with caplog.at_level(logging.ERROR, logger=LOGGER_NAME):
        errors = verify_chain()
    assert errors
    assert "Hash chain verification failed" in caplog.text


def test_password_validation_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        with pytest.raises(PasswordValidationError):
            validate_password("short")
    assert "Password validation failed" in caplog.text


def test_keyring_read_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    broken = types.ModuleType("keyring")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("keyring backend unavailable")

    broken.get_password = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", broken)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert get_password_from_keyring() is None
    assert "Keyring read failed" in caplog.text


def test_keyring_write_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    broken = types.ModuleType("keyring")

    def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("keyring backend unavailable")

    broken.set_password = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "keyring", broken)
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        assert set_password_in_keyring("a-valid-password") is False
    assert "Keyring write failed" in caplog.text


def test_csrf_failure_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    from fastapi.testclient import TestClient

    from main import app

    init_db()
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("csrf", "good-token")
    with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
        response = client.post(
            "/import-csv",
            data={"csrf_token": "bad-token", "csv_text": "", "record_type": "W2"},
        )
    assert response.status_code == 400
    assert "CSRF validation failed (path=/import-csv)" in caplog.text


def test_csv_import_route_logs_summary(caplog: pytest.LogCaptureFixture) -> None:
    from fastapi.testclient import TestClient

    from main import app

    init_db()
    client = TestClient(app, base_url="http://localhost")
    client.cookies.set("csrf", "good-token")
    csv_text = "employer_name,wages\nAcme,50000\n"
    with caplog.at_level(logging.INFO, logger=LOGGER_NAME):
        response = client.post(
            "/import-csv",
            data={"csrf_token": "good-token", "csv_text": csv_text, "record_type": "W2"},
        )
    assert response.status_code == 200
    assert "CSV import: record_type=W2, count=1, error_count=0" in caplog.text


# ─── Source-level guard ────────────────────────────────────────


def _catches_broad_exception(handler: ast.ExceptHandler) -> bool:
    """True when the handler catches Exception (bare or inside a tuple)."""
    node = handler.type
    if node is None:
        return False
    candidates = node.elts if isinstance(node, ast.Tuple) else [node]
    return any(isinstance(c, ast.Name) and c.id == "Exception" for c in candidates)


def _handler_logs(handler: ast.ExceptHandler) -> bool:
    """True when the handler body contains a logger.<method>() call."""
    for node in ast.walk(handler):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            return True
    return False


def test_no_except_exception_without_logger_call() -> None:
    """M13 acceptance: no except Exception block may swallow silently."""
    offenders: list[str] = []
    for path in sorted((_REPO_ROOT / "app").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ExceptHandler)
                and _catches_broad_exception(node)
                and not _handler_logs(node)
            ):
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{node.lineno}")
    assert not offenders, f"except Exception without logger call: {offenders}"
