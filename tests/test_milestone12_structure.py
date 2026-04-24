# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structural regression tests for Milestone 12 routing split."""

from __future__ import annotations

from pathlib import Path


def test_main_module_stays_under_100_lines() -> None:
    """main.py should remain a thin application-wiring module."""
    main_path = Path(__file__).resolve().parent.parent / "main.py"
    line_count = len(main_path.read_text(encoding="utf-8").splitlines())
    assert line_count < 100
