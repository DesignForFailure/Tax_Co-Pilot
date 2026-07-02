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

"""Centralized logging configuration for Tax Copilot.

Security events (unlock attempts, key rotation, run creation/deletion,
hash-chain verification, backup/restore) must be observable, so every
module logs through a child of the single ``tax_copilot`` logger that
:func:`configure` sets up at application startup.

Environment variables:
- ``TAX_COPILOT_LOG_LEVEL``: standard level name (default: ``INFO``).
- ``TAX_COPILOT_LOG_FILE``: enables a rotating file handler. Set to a
  path, or to ``1``/``true`` for the default ``data/tax_copilot.log``.
  Unset (the default) logs to stderr only, matching the local-first
  privacy posture — no log file is written unless explicitly requested.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

LOGGER_NAME = "tax_copilot"

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_MAX_LOG_BYTES = 10 * 1024 * 1024
_LOG_BACKUP_COUNT = 3
_DEFAULT_LOG_PATH = Path("data") / "tax_copilot.log"
# Marker attribute distinguishing handlers owned by configure() from any
# handlers attached externally (e.g., by tests), so reconfiguring never
# stacks duplicates and never removes handlers it did not create.
_OWNED_ATTR = "_tax_copilot_owned"


def get_logger(module_name: str) -> logging.Logger:
    """Return a child logger under the ``tax_copilot`` namespace.

    Pass ``__name__``; the leading ``app.`` package prefix is replaced so
    log lines read ``tax_copilot.services.database`` rather than
    ``app.services.database``.
    """
    suffix = module_name.removeprefix("app.").removeprefix("app")
    if not suffix or suffix == LOGGER_NAME:
        return logging.getLogger(LOGGER_NAME)
    return logging.getLogger(f"{LOGGER_NAME}.{suffix}")


def _resolve_level() -> int:
    """Resolve the configured log level, defaulting to INFO."""
    raw = os.getenv("TAX_COPILOT_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(raw)
    return level if isinstance(level, int) else logging.INFO


def _resolve_log_file() -> Path | None:
    """Resolve the optional log file path from the environment."""
    raw = os.getenv("TAX_COPILOT_LOG_FILE", "").strip()
    if not raw or raw.lower() in {"0", "false", "no", "off"}:
        return None
    if raw.lower() in {"1", "true", "yes", "on"}:
        return _DEFAULT_LOG_PATH
    return Path(raw)


def configure() -> logging.Logger:
    """Configure the application logger and return it.

    Idempotent: safe to call on every startup. Re-reads the environment
    each call, so tests (and long-lived processes) can reconfigure by
    changing the environment and calling again.
    """
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(_resolve_level())

    for handler in [h for h in logger.handlers if getattr(h, _OWNED_ATTR, False)]:
        logger.removeHandler(handler)
        handler.close()

    formatter = logging.Formatter(_LOG_FORMAT)

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    setattr(console, _OWNED_ATTR, True)
    logger.addHandler(console)

    log_file = _resolve_log_file()
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=_MAX_LOG_BYTES, backupCount=_LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        setattr(file_handler, _OWNED_ATTR, True)
        logger.addHandler(file_handler)

    return logger
