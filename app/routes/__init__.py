# SPDX-License-Identifier: AGPL-3.0-or-later
"""Route package exports for application wiring."""

from __future__ import annotations

from app.routes.calculate import router as calculate_router
from app.routes.encryption import router as encryption_router
from app.routes.import_export import router as import_export_router
from app.routes.navigation import router as navigation_router
from app.routes.rule_packs import router as rule_packs_router
from app.routes.runs import router as runs_router

__all__ = [
    "calculate_router",
    "encryption_router",
    "import_export_router",
    "navigation_router",
    "rule_packs_router",
    "runs_router",
]
