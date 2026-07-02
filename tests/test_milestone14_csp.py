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

"""CSP hardening tests (Milestone 14).

The Content-Security-Policy must not allow inline scripts or styles, so
these tests enforce three layers: the header itself, the template
sources (no <style>/<script> bodies, style="" attributes, or inline
event handlers), and the served static assets that replaced them.
"""

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.services.database import init_db
from main import app

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TEMPLATES_DIR = _REPO_ROOT / "app" / "templates"
_STATIC_DIR = _REPO_ROOT / "app" / "static"

# Inline event handler attributes (onclick=, onchange=, onsubmit=, ...) are
# blocked by script-src 'self' just like <script> bodies.
_EVENT_HANDLER_RE = re.compile(r"\son[a-z]+\s*=", re.IGNORECASE)
_INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\bsrc=)", re.IGNORECASE)

_STATIC_ASSETS = [
    "css/main.css",
    "js/theme.js",
    "js/submit-guard.js",
    "js/forms.js",
    "js/compare.js",
    "js/rule-editor.js",
]

# Pages renderable without seeded data; covers every template that
# previously carried inline CSS or JS.
_RENDERED_PAGES = ["/", "/dashboard", "/calculate", "/whatif", "/runs", "/import-csv", "/legal", "/rule-packs"]


@pytest.fixture(autouse=True)
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    return TestClient(app, base_url="http://localhost")


def test_csp_has_no_unsafe_inline() -> None:
    resp = _client().get("/legal")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "script-src 'self';" in csp
    assert "style-src 'self';" in csp
    assert "unsafe-inline" not in csp


def test_static_assets_are_served() -> None:
    c = _client()
    for asset in _STATIC_ASSETS:
        resp = c.get(f"/static/{asset}")
        assert resp.status_code == 200, f"/static/{asset} not served"
        assert resp.text.strip(), f"/static/{asset} is empty"


def test_main_css_contains_design_system() -> None:
    css = (_STATIC_DIR / "css" / "main.css").read_text(encoding="utf-8")
    assert ":root" in css
    assert '[data-theme="dark"]' in css
    assert ".site-header" in css


def test_templates_have_no_style_blocks() -> None:
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _TEMPLATES_DIR.rglob("*.html")
        if "<style" in p.read_text(encoding="utf-8").lower()
    ]
    assert not offenders, f"<style> blocks remain: {offenders}"


def test_templates_have_no_style_attributes() -> None:
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _TEMPLATES_DIR.rglob("*.html")
        if 'style="' in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f'style="" attributes remain: {offenders}'


def test_templates_have_no_inline_scripts() -> None:
    offenders = [
        str(p.relative_to(_REPO_ROOT))
        for p in _TEMPLATES_DIR.rglob("*.html")
        if _INLINE_SCRIPT_RE.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"inline <script> blocks remain: {offenders}"


def test_templates_have_no_inline_event_handlers() -> None:
    offenders = []
    for p in _TEMPLATES_DIR.rglob("*.html"):
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
            if _EVENT_HANDLER_RE.search(line):
                offenders.append(f"{p.relative_to(_REPO_ROOT)}:{lineno}")
    assert not offenders, f"inline event handlers remain: {offenders}"


def test_rendered_pages_are_csp_clean() -> None:
    c = _client()
    for page in _RENDERED_PAGES:
        resp = c.get(page, follow_redirects=True)
        assert resp.status_code == 200, f"GET {page} -> {resp.status_code}"
        html = resp.text
        assert '<link rel="stylesheet" href="/static/css/main.css">' in html, page
        assert 'style="' not in html, f"{page} renders a style attribute"
        assert not _INLINE_SCRIPT_RE.search(html), f"{page} renders an inline script"
        assert not _EVENT_HANDLER_RE.search(html), f"{page} renders an inline event handler"


def test_calculate_page_exposes_states_data_attribute() -> None:
    """The former inline availableStatesByYear payload now travels via data-*."""
    resp = _client().get("/calculate")
    assert resp.status_code == 200
    assert "data-states-by-year=" in resp.text
    assert '<script src="/static/js/forms.js"></script>' in resp.text
