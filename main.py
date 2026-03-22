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

"""Tax Copilot — FastAPI Application (MVP Vertical Slice).

Sections:
- App setup + middleware: localhost hardening defaults.
- Template wiring: Jinja2 HTML rendering.
- Input parsing: strict-ish money parsing and form extraction.
- CSRF: double-submit cookie pattern to protect POSTs.
- Routes: dashboard (latest run), calculate (GET/POST), runs list, run detail,
  what-if comparison, CSV import, audit export, run deletion, run comparison.
- Error handling: return safe 400s for invalid user input.

Future improvements:
- Add security headers (CSP, Referrer-Policy, etc.) if served beyond localhost.
- Add rate limiting if ever exposed over a network.
"""

from __future__ import annotations

import io
import json
import re
import secrets
import sqlite3 as _sqlite3
import tempfile
import urllib.parse
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import config as encryption_config
from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.engine.whatif import WhatIfEngine
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Form1099INTData,
    ItemizedDeductionData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.audit_export import generate_audit_html
from app.services.csv_import import import_csv as _import_csv
from app.services.database import (
    DB_PATH,
    clear_cached_password,
    delete_return_run,
    get_cached_password,
    get_return_run,
    init_db,
    list_return_runs,
    save_return_run,
    set_cached_password,
    update_run_annotation,
    verify_chain,
)
from app.services.encryption import (
    DatabaseState,
    PasswordValidationError,
    detect_encryption_state,
    get_password,
    rotate_key,
    set_password_in_keyring,
    validate_password,
)
from app.services.rule_pack_editor import (
    clone_pack,
    create_empty_pack,
    delete_pack,
    export_yaml,
    load_pack_detail,
)
from app.services.rule_pack_editor import (
    list_all_packs as list_rule_packs,
)
from app.services.rule_pack_editor import (
    validate_pack as validate_rule_pack,
)

# ─── FastAPI app and basic hardening ───────────────────────────
# TrustedHostMiddleware mitigates DNS rebinding / Host header attacks.
# Keep this locked to localhost unless you intentionally expose the service.


@asynccontextmanager
async def _lifespan(a: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    _startup()
    yield
    clear_cached_password()


app = FastAPI(title="Tax Copilot", version="0.1.0", lifespan=_lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost"])

# ─── Security headers (defense-in-depth) ───────────────────────
# Even for localhost, these headers reduce the blast radius of common web attacks.
# If you later serve over HTTPS or expose remotely, revisit CSP and add HSTS.

_CSP = (
    "default-src 'self'; "
    "script-src 'self' https://unpkg.com; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Any) -> Response:
    response = await call_next(request)

    # Clickjacking + MIME sniffing defenses
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("X-Content-Type-Options", "nosniff")

    # Privacy defaults
    response.headers.setdefault("Referrer-Policy", "no-referrer")

    # Feature gating (tighten later if you add features like camera/mic)
    response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")

    # Content Security Policy: allow HTMX from unpkg + inline styles (base.html uses inline CSS)
    response.headers.setdefault("Content-Security-Policy", _CSP)

    # Prevent caching of potentially sensitive tax data in shared browser caches.
    response.headers.setdefault("Cache-Control", "no-store")

    return cast(Response, response)


BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

FEDERAL_PACKS_DIR = BASE_DIR / "rule_packs" / "federal"
STATE_PACKS_DIR = BASE_DIR / "rule_packs" / "state"

# Cache: year -> loaded RulePack / state dict
_federal_cache: dict[int, RulePack] = {}
_state_cache: dict[int, dict[str, RulePack]] = {}


def _bust_pack_cache(jurisdiction: str, year: int) -> None:
    """Remove cached packs so next load reads from disk."""
    j = jurisdiction.lower()
    if j in {"federal", "fed"}:
        _federal_cache.pop(year, None)
    else:
        _state_cache.pop(year, None)


def _discover_available_years() -> list[int]:
    """Scan rule_packs/federal/ for available tax years."""
    years: list[int] = []
    if not FEDERAL_PACKS_DIR.exists():
        return years
    for year_dir in sorted(FEDERAL_PACKS_DIR.iterdir()):
        if year_dir.is_dir() and year_dir.name.isdigit():
            years.append(int(year_dir.name))
    return years


def _get_federal_pack(year: int) -> RulePack:
    """Load and cache a federal rule pack for the given year."""
    if year not in _federal_cache:
        pack_dir = FEDERAL_PACKS_DIR / str(year)
        _federal_cache[year] = RulePack.load(pack_dir)
    return _federal_cache[year]


def _get_state_packs(year: int) -> dict[str, RulePack]:
    """Load and cache all state rule packs for the given year."""
    if year not in _state_cache:
        packs: dict[str, RulePack] = {}
        if STATE_PACKS_DIR.exists():
            for state_dir in sorted(STATE_PACKS_DIR.iterdir()):
                if not state_dir.is_dir() or state_dir.name.startswith("_"):
                    continue
                year_dir = state_dir / str(year)
                if year_dir.exists():
                    packs[state_dir.name.upper()] = RulePack.load(year_dir)
        _state_cache[year] = packs
    return _state_cache[year]


available_years = _discover_available_years()

# Pre-warm caches for all discovered years
for _yr in available_years:
    _get_federal_pack(_yr)
    _get_state_packs(_yr)


def _parse_money(
    raw: str,
    *,
    default: str = "0",
    allow_negative: bool = False,
    max_abs: Decimal = Decimal("1000000000"),  # $1B safety cap for MVP
    max_decimals: int = 2,
) -> Decimal:
    """Parse a user-entered currency value to Decimal.

    Accepts common human inputs like "12,345.67".

    Security/QA:
    - Rejects non-finite values (NaN/Inf).
    - Rejects scientific notation ("1e9") to avoid surprising inputs.
    - Enforces a maximum absolute value (default $1B) to prevent pathological values.
    - Enforces max decimal places (default 2). Does NOT silently round extra precision.

    Tuning:
    - Adjust max_abs/max_decimals per-field as the UI and import paths expand.
    """
    s = (raw or "").strip()
    if not s:
        s = default

    # Normalize common formatting
    s = s.replace(",", "")

    # Disallow exponent notation and leading plus for predictability
    if "e" in s.lower() or s.startswith("+"):
        raise ValueError(f"Invalid money value: {raw!r}")

    try:
        d = Decimal(s)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid money value: {raw!r}") from exc

    if not d.is_finite():
        raise ValueError("Money value must be finite")

    if not allow_negative and d < 0:
        raise ValueError("Money value must be non-negative")

    if abs(d) > max_abs:
        raise ValueError("Money value is too large")

    # Enforce decimal precision without silent rounding.
    exp = d.as_tuple().exponent
    if isinstance(exp, int) and exp < -max_decimals:
        raise ValueError(f"Money value has more than {max_decimals} decimal places")

    # Normalize to fixed decimals for consistent storage/display.
    quant = Decimal("1") if max_decimals == 0 else (Decimal(10) ** (-max_decimals))
    return d.quantize(quant)


def _get_csrf_token(request: Request) -> str:
    """Return the current CSRF token or mint one.

    Uses a cookie named `csrf` plus a hidden form field.
    This is the 'double-submit cookie' pattern.
    """
    token: str | None = request.cookies.get("csrf")
    if not token:
        token = secrets.token_urlsafe(32)
    return token


def _verify_csrf(request: Request, form_token: str) -> None:
    """Validate CSRF token.

    Security:
    - Uses constant-time compare via secrets.compare_digest.
    - Rejects missing cookie or mismatch.
    """
    cookie_token = request.cookies.get("csrf")
    if not cookie_token or not secrets.compare_digest(cookie_token, form_token or ""):
        raise ValueError("CSRF validation failed")


def _load_run_from_row(run_data: dict[str, Any]) -> ReturnRun:
    """Hydrate a persisted DB row into a typed ReturnRun."""
    hydrated = dict(run_data)
    hydrated["input_snapshot"] = json.loads(hydrated["input_snapshot_json"])
    hydrated["output"] = json.loads(hydrated["output_json"])
    hydrated["trace"] = json.loads(hydrated["trace_json"])
    hydrated["state_outputs"] = json.loads(hydrated.get("state_outputs_json", "[]"))
    return ReturnRun(**{k: v for k, v in hydrated.items() if not k.endswith("_json")})


def _startup() -> None:
    """Initialize database on startup.

    Handles encryption setup:
    1. If encryption enabled and DB encrypted, password must be provided via env/keyring
    2. If encryption enabled and DB unencrypted, allow access (migration handled via UI)
    3. If encryption disabled, proceed normally
    """
    if encryption_config.enabled:
        db_state = detect_encryption_state(DB_PATH)

        if db_state == DatabaseState.ENCRYPTED_SQLCIPHER:
            # Database is encrypted - try to get password
            password = get_password(source=encryption_config.password_source)
            if password:
                # Password available from env/keyring - cache it
                set_cached_password(password)
                init_db()
            else:
                # Password needed - will redirect to /unlock on first request
                # Don't init_db() yet - will happen after unlock
                pass
        elif db_state == DatabaseState.ENCRYPTED_PYTHON:
            raise RuntimeError(
                "Python-layer encrypted databases are unsupported at runtime. "
                "Migrate to SQLCipher encryption."
            )
        else:
            # Database doesn't exist or is unencrypted - init normally
            init_db()
    else:
        # Encryption disabled - normal init
        init_db()


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> Response:
    # Check if database unlock is needed
    if encryption_config.enabled:
        db_state = detect_encryption_state(DB_PATH)
        if db_state == DatabaseState.ENCRYPTED_SQLCIPHER:
            from app.services.database import get_cached_password

            if not get_cached_password():
                # Redirect to unlock page
                return RedirectResponse(url="/unlock", status_code=303)
        if db_state == DatabaseState.ENCRYPTED_PYTHON:
            return HTMLResponse(
                "Python-layer encrypted databases are unsupported at runtime. "
                "Migrate to SQLCipher encryption.",
                status_code=500,
            )

    runs = list_return_runs()
    run = None
    if runs:
        run_id = runs[0]["id"]
        run_data = get_return_run(run_id)
        if run_data:
            run = _load_run_from_row(run_data)

    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse("pages/dashboard.html", {"request": request, "run": run})
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/calculate.html",
        {"request": request, "csrf": csrf, "available_years": available_years, "available_states": sorted(_get_state_packs(max(available_years)).keys()) if available_years else []},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


# ─── Form parsing helpers ──────────────────────────────────────

_MAX_TEXT = 200
_MAX_INDEXED_ENTRIES = 50  # Cap on dynamic rows per section (defense-in-depth)
_MAX_IMPORT_BYTES = 10 * 1024 * 1024  # 10 MB
_MAX_RESTORE_BYTES = 100 * 1024 * 1024  # 100 MB
_MAX_IMPORT_ENTRIES = 1000
_MAX_NOTES = 2000


def _sanitize_filename(raw: str) -> str:
    """Strip non-alphanumeric chars from a string for safe Content-Disposition."""
    return re.sub(r"[^a-zA-Z0-9_-]", "", raw)
_IDX_RE = re.compile(r"^(\w+?)_(\d+)_(\w+)$")


def _form_str(fd: FormData, key: str, default: str = "") -> str:
    """Extract a trimmed string from form data, bounded to _MAX_TEXT."""
    raw = str(fd.get(key, default) or default).strip()
    if len(raw) > _MAX_TEXT:
        raise ValueError(f"{key} exceeds {_MAX_TEXT} characters")
    return raw


def _form_money(fd: FormData, key: str, default: str = "0") -> Decimal:
    return _parse_money(str(fd.get(key, default) or default), allow_negative=False)


def _collect_indices(fd: FormData, prefix: str) -> list[int]:
    """Find all integer indices for keys matching ``{prefix}_{N}_*``."""
    indices: set[int] = set()
    prefix_under = prefix + "_"
    for key in fd:
        if key.startswith(prefix_under):
            m = _IDX_RE.fullmatch(key)
            if m and m.group(1) == prefix:
                idx = int(m.group(2))
                if idx < _MAX_INDEXED_ENTRIES:
                    indices.add(idx)
    return sorted(indices)


def _parse_w2s(fd: FormData, prefix: str) -> list[W2Data]:
    """Parse W-2 rows from indexed form fields like ``{prefix}_0_wages``."""
    w2s: list[W2Data] = []
    for idx in _collect_indices(fd, prefix):
        p = f"{prefix}_{idx}"
        wages = _form_money(fd, f"{p}_wages")
        withheld = _form_money(fd, f"{p}_federal_withheld")
        employer = _form_str(fd, f"{p}_employer")
        # Skip rows with no data entered
        if wages == 0 and withheld == 0 and not employer:
            continue
        w2s.append(
            W2Data(
                employer_name=employer,
                wages=wages,
                federal_withheld=withheld,
                state=_form_str(fd, f"{p}_state").upper(),
                state_wages=_form_money(fd, f"{p}_state_wages"),
                state_withheld=_form_money(fd, f"{p}_state_withheld"),
            )
        )
    return w2s


def _parse_1099ints(fd: FormData, prefix: str) -> list[Form1099INTData]:
    items: list[Form1099INTData] = []
    for idx in _collect_indices(fd, prefix):
        p = f"{prefix}_{idx}"
        interest = _form_money(fd, f"{p}_interest")
        payer = _form_str(fd, f"{p}_payer")
        if interest == 0 and not payer:
            continue
        items.append(
            Form1099INTData(
                payer_name=payer,
                interest_income=interest,
                federal_withheld=_form_money(fd, f"{p}_federal_withheld"),
            )
        )
    return items


def _parse_1099divs(fd: FormData, prefix: str) -> list[Form1099DIVData]:
    items: list[Form1099DIVData] = []
    for idx in _collect_indices(fd, prefix):
        p = f"{prefix}_{idx}"
        ordinary = _form_money(fd, f"{p}_ordinary")
        payer = _form_str(fd, f"{p}_payer")
        if ordinary == 0 and not payer:
            continue
        items.append(
            Form1099DIVData(
                payer_name=payer,
                ordinary_dividends=ordinary,
                qualified_dividends=_form_money(fd, f"{p}_qualified"),
                federal_withheld=_form_money(fd, f"{p}_federal_withheld"),
            )
        )
    return items


def _parse_1099bs(fd: FormData, prefix: str) -> list[Form1099BData]:
    items: list[Form1099BData] = []
    for idx in _collect_indices(fd, prefix):
        p = f"{prefix}_{idx}"
        proceeds = _form_money(fd, f"{p}_proceeds")
        desc = _form_str(fd, f"{p}_desc")
        if proceeds == 0 and not desc:
            continue
        items.append(
            Form1099BData(
                description=desc or "Capital gain",
                proceeds=proceeds,
                cost_basis=_form_money(fd, f"{p}_basis"),
                is_long_term=str(fd.get(f"{p}_long_term", "")) == "1",
                federal_withheld=_form_money(fd, f"{p}_federal_withheld"),
            )
        )
    return items


def _parse_taxpayer(fd: FormData, prefix: str, role: TaxpayerRole) -> Taxpayer:
    """Build a Taxpayer from indexed form fields under a given prefix (``p`` or ``s``)."""
    first_name = _form_str(fd, f"{prefix}_first")
    last_name = _form_str(fd, f"{prefix}_last")

    if role == TaxpayerRole.PRIMARY:
        if not first_name:
            raise ValueError("first name is required")
        if not last_name:
            raise ValueError("last name is required")

    return Taxpayer(
        role=role,
        first_name=first_name,
        last_name=last_name,
        w2s=_parse_w2s(fd, f"{prefix}_w2"),
        form_1099_ints=_parse_1099ints(fd, f"{prefix}_1099int"),
        form_1099_divs=_parse_1099divs(fd, f"{prefix}_1099div"),
        form_1099_bs=_parse_1099bs(fd, f"{prefix}_1099b"),
    )


def _parse_tax_input_from_form(fd: FormData) -> TaxReturnInput:
    """Convert raw multi-part form data into a validated ``TaxReturnInput``."""
    tax_year = int(str(fd.get("tax_year", "2024") or "2024"))
    if tax_year not in available_years:
        raise ValueError(f"Unsupported tax year: {tax_year}")
    filing_status = FilingStatus(str(fd.get("filing_status", "mfj") or "mfj"))

    primary = _parse_taxpayer(fd, "p", TaxpayerRole.PRIMARY)
    taxpayers: list[Taxpayer] = [primary]

    s_first = _form_str(fd, "s_first")
    s_last = _form_str(fd, "s_last")
    has_spouse_income = bool(
        _collect_indices(fd, "s_w2")
        or _collect_indices(fd, "s_1099int")
        or _collect_indices(fd, "s_1099div")
        or _collect_indices(fd, "s_1099b")
    )

    # MFS returns are per-person, so this single-return form must not aggregate
    # both spouses into one run.
    if filing_status == FilingStatus.MFJ:
        if s_first or s_last or has_spouse_income:
            taxpayers.append(_parse_taxpayer(fd, "s", TaxpayerRole.SPOUSE))
    elif filing_status == FilingStatus.MFS and (s_first or s_last or has_spouse_income):
        raise ValueError("MFS is per-person; submit each spouse as a separate run")

    adjustments = AdjustmentsData(
        student_loan_interest=_form_money(fd, "adj_student_loan"),
        educator_expenses=_form_money(fd, "adj_educator"),
        hsa_contributions=_form_money(fd, "adj_hsa"),
        ira_contributions=_form_money(fd, "adj_ira"),
        self_employment_tax_deduction=_form_money(fd, "adj_se_tax"),
    )

    itemized = ItemizedDeductionData(
        medical_expenses=_form_money(fd, "item_medical"),
        state_local_taxes=_form_money(fd, "item_state_taxes"),
        real_estate_taxes=_form_money(fd, "item_property_taxes"),
        mortgage_interest=_form_money(fd, "item_mortgage"),
        charitable_cash=_form_money(fd, "item_charitable_cash"),
        charitable_noncash=_form_money(fd, "item_charitable_noncash"),
    )

    raw_children = str(fd.get("qualifying_children", "0")).strip()
    qualifying_children = min(int(raw_children), 20) if raw_children.isdigit() else 0

    return TaxReturnInput(
        tax_year=tax_year,
        filing_status=filing_status,
        taxpayers=taxpayers,
        adjustments=adjustments,
        estimated_tax_payments=_form_money(fd, "estimated_payments"),
        other_income=_form_money(fd, "other_income"),
        itemized_deductions=itemized,
        qualifying_children=qualifying_children,
    )


# ─── Calculate route ─────────────────────────────────────────────


@app.post("/calculate")
async def calculate_submit(request: Request) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))

    inputs = _parse_tax_input_from_form(fd)

    states_needed = {
        w.state.upper()
        for tp in inputs.taxpayers
        for w in tp.w2s
        if w.state
    }
    residence = str(fd.get("state_of_residence", "")).strip().upper()
    if residence:
        states_needed.add(residence)
    fed_pack = _get_federal_pack(inputs.tax_year)
    year_state_packs = _get_state_packs(inputs.tax_year)
    active_state_packs = {
        s: year_state_packs[s] for s in states_needed if s in year_state_packs
    }
    run = CalculationEngine(
        fed_pack, inputs, state_packs=active_state_packs
    ).run()
    run_dict = json.loads(run.model_dump_json())
    save_return_run(run_dict)

    return RedirectResponse(url="/", status_code=303)


@app.get("/runs", response_class=HTMLResponse)
def past_runs(request: Request) -> Response:
    runs = list_return_runs()
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/runs.html", {"request": request, "runs": runs, "csrf": csrf}
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


# ─── Run Comparison (declared before /runs/{run_id}) ─────────
# Must come before the {run_id} route so FastAPI does not bind
# the literal string "compare" as a run_id path parameter.


@app.get("/runs/compare", response_class=HTMLResponse)
def compare_runs(request: Request, a: str = "", b: str = "") -> Response:
    if not a or not b:
        return HTMLResponse("Two run IDs are required (a= and b=)", status_code=400)
    run_a_data = get_return_run(a)
    run_b_data = get_return_run(b)
    if not run_a_data or not run_b_data:
        return HTMLResponse("One or both runs not found", status_code=404)
    run_a = _load_run_from_row(run_a_data)
    run_b = _load_run_from_row(run_b_data)
    output_fields = [
        "gross_income",
        "agi",
        "standard_deduction",
        "itemized_deductions",
        "deduction_applied",
        "taxable_income",
        "tax_before_credits",
        "child_tax_credit",
        "total_credits",
        "federal_tax",
        "total_withholding",
        "estimated_tax_payments",
        "total_payments",
        "refund_or_owed",
    ]
    output_diffs: list[dict[str, Any]] = []
    for field in output_fields:
        val_a = getattr(run_a.output, field)
        val_b = getattr(run_b.output, field)
        delta = val_b - val_a
        output_diffs.append(
            {
                "field": field,
                "val_a": val_a,
                "val_b": val_b,
                "delta": delta,
                "delta_abs": abs(delta),
                "delta_sign": "positive" if delta > 0 else ("negative" if delta < 0 else "zero"),
                "is_refund_field": field == "refund_or_owed",
            }
        )
    return templates.TemplateResponse(
        "pages/run_compare.html",
        {
            "request": request,
            "run_a": run_a,
            "run_b": run_b,
            "output_diffs": output_diffs,
        },
    )


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def view_run(request: Request, run_id: str) -> HTMLResponse:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)

    run = _load_run_from_row(run_data)
    return templates.TemplateResponse("pages/dashboard.html", {"request": request, "run": run})


# ─── What-If Comparison ──────────────────────────────────────


@app.get("/whatif", response_class=HTMLResponse)
def whatif_form(request: Request) -> Response:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/whatif.html",
        {"request": request, "csrf": csrf, "available_years": available_years},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/whatif", response_class=HTMLResponse)
async def whatif_submit(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    inputs = _parse_tax_input_from_form(fd)
    engine = WhatIfEngine(_get_federal_pack(inputs.tax_year))
    comparison = engine.compare_filing_status(inputs)
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/whatif.html",
        {
            "request": request,
            "csrf": csrf,
            "comparison": comparison,
            "available_years": available_years,
            "selected_year": inputs.tax_year,
        },
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


# ─── CSV Import ───────────────────────────────────────────────


@app.get("/import-csv", response_class=HTMLResponse)
def import_csv_form(request: Request) -> Response:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/import_csv.html", {"request": request, "csrf": csrf}
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/import-csv", response_class=HTMLResponse)
async def import_csv_submit(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    csv_text = str(fd.get("csv_text", "") or "")
    record_type = str(fd.get("record_type", "W2") or "W2")
    records_raw, errors = _import_csv(csv_text, record_type)
    record_dicts = [r.model_dump() for r in records_raw]
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/import_csv.html",
        {
            "request": request,
            "csrf": csrf,
            "records": record_dicts,
            "errors": errors,
            "record_type": record_type,
        },
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


# ─── Audit Export ─────────────────────────────────────────────


@app.get("/runs/{run_id}/export/json")
def export_run_json(run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = _load_run_from_row(run_data)
    # Serialize to indented JSON matching what export_json() would write to disk.
    json_bytes = json.dumps(
        json.loads(run.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="run_{_sanitize_filename(run_id)}.json"'},
    )


@app.get("/runs/{run_id}/export/html")
def export_run_html(run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = _load_run_from_row(run_data)
    html_content = generate_audit_html(run)
    return StreamingResponse(
        io.BytesIO(html_content.encode("utf-8")),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="audit_{_sanitize_filename(run_id)}.html"'},
    )


# ─── Form-Oriented View ──────────────────────────────────────


@app.get("/runs/{run_id}/forms", response_class=HTMLResponse)
def view_run_forms(request: Request, run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = _load_run_from_row(run_data)

    from app.services.form_mapper import map_return_run

    packet = map_return_run(run)
    return templates.TemplateResponse(
        "pages/forms_view.html", {"request": request, "run": run, "packet": packet}
    )


@app.get("/runs/{run_id}/export/forms")
def export_run_forms(run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run = _load_run_from_row(run_data)

    from app.services.form_mapper import map_return_run

    packet = map_return_run(run)
    json_bytes = json.dumps(
        json.loads(packet.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="forms_{_sanitize_filename(run_id)}.json"'},
    )


# ─── Run Deletion ─────────────────────────────────────────────


@app.post("/runs/{run_id}/delete")
async def delete_run(request: Request, run_id: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_return_run(run_id)
    return RedirectResponse(url="/runs", status_code=303)


@app.get("/legal", response_class=HTMLResponse)
def legal_notices(request: Request) -> HTMLResponse:
    """Display third-party license and legal notices."""
    return templates.TemplateResponse("pages/legal.html", {"request": request})


@app.get("/unlock", response_class=HTMLResponse)
def unlock_form(request: Request, error: str | None = None) -> HTMLResponse:
    """Show password unlock form for encrypted database."""
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/unlock.html", {"request": request, "csrf": csrf, "error": error}
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/unlock")
def unlock_submit(request: Request, password: str = Form(""), csrf_token: str = Form("")) -> RedirectResponse:
    """Handle password unlock submission."""
    _verify_csrf(request, csrf_token)

    if not password:
        return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus('Password is required')}", status_code=303)

    try:
        # Validate password format
        validate_password(password)

        # Try to open database with this password
        db_state = detect_encryption_state(DB_PATH)
        if db_state == DatabaseState.ENCRYPTED_PYTHON:
            return RedirectResponse(
                url="/unlock?error=Python-layer+encryption+is+unsupported;+use+SQLCipher",
                status_code=303,
            )
        if db_state != DatabaseState.ENCRYPTED_SQLCIPHER:
            return RedirectResponse(
                url="/unlock?error=Database+is+not+encrypted", status_code=303
            )

        # Test the password by attempting to connect
        from app.services.database import get_connection

        conn = get_connection(password=password)
        # Test read access
        conn.execute("SELECT count(*) FROM sqlite_master")
        conn.close()

        # Password works - cache it
        set_cached_password(password)

        # Store in keyring for future use
        set_password_in_keyring(password)

        # Initialize database if not already done
        init_db()

        # Redirect to dashboard with fresh CSRF token
        resp = RedirectResponse(url="/", status_code=303)
        resp.set_cookie("csrf", secrets.token_urlsafe(32), httponly=True, samesite="strict")
        return resp

    except PasswordValidationError as e:
        return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus(str(e)[:100])}", status_code=303)
    except ValueError:
        # Wrong password or corrupted database
        return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus('Incorrect password or corrupted database')}", status_code=303)
    except Exception as e:
        return RedirectResponse(url=f"/unlock?error={urllib.parse.quote_plus(f'Unlock failed: {str(e)[:50]}')}", status_code=303)


@app.post("/runs/{run_id}/annotate")
async def annotate_run(request: Request, run_id: str) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    tags = _form_str(fd, "tags")
    notes = str(fd.get("notes", "")).strip()
    if len(notes) > _MAX_NOTES:
        raise ValueError(f"Notes exceed {_MAX_NOTES} characters")
    update_run_annotation(run_id, tags, notes)
    return RedirectResponse(url="/runs", status_code=303)


@app.get("/export-all")
def export_all_runs() -> Response:
    rows = list_return_runs()
    hydrated = []
    for r in rows:
        try:
            run = _load_run_from_row(r)
            hydrated.append(json.loads(run.model_dump_json()))
        except Exception:
            hydrated.append({"error": f"Failed to hydrate run {r.get('id', '?')}", "id": r.get("id")})
    return Response(
        content=json.dumps(hydrated, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=tax_copilot_runs.json"},
    )


@app.post("/import-returns", response_class=HTMLResponse)
async def import_returns(request: Request) -> HTMLResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    upload = fd.get("file")
    if not upload or not hasattr(upload, "read"):
        return HTMLResponse("No file uploaded", status_code=400)
    content = (await upload.read()).decode("utf-8")
    if len(content.encode("utf-8")) > _MAX_IMPORT_BYTES:
        return HTMLResponse(f"File too large (max {_MAX_IMPORT_BYTES // (1024*1024)} MB)", status_code=400)
    try:
        entries = json.loads(content)
    except json.JSONDecodeError as e:
        return HTMLResponse(f"Invalid JSON: {e}", status_code=400)
    if not isinstance(entries, list):
        return HTMLResponse("Expected a JSON array", status_code=400)
    if len(entries) > _MAX_IMPORT_ENTRIES:
        return HTMLResponse(f"Too many entries (max {_MAX_IMPORT_ENTRIES})", status_code=400)
    imported = 0
    errors: list[str] = []
    for i, entry in enumerate(entries):
        try:
            run = ReturnRun(**entry)
            year = run.tax_year
            if year in _federal_cache:
                expected = _federal_cache[year].checksum
                if run.rule_pack_checksum and run.rule_pack_checksum != expected:
                    errors.append(f"Entry {i}: checksum mismatch (pack may differ)")
                    continue
            run_dict = json.loads(run.model_dump_json())
            save_return_run(run_dict)
            imported += 1
        except Exception as e:
            errors.append(f"Entry {i}: {e}")
    result = f"Imported {imported} run(s)."
    if errors:
        result += f" {len(errors)} error(s): " + "; ".join(errors[:5])
    return HTMLResponse(result, status_code=200)


@app.get("/backup")
def backup_database() -> Response:
    if not DB_PATH.exists():
        return HTMLResponse("No database file found", status_code=404)
    return Response(
        content=DB_PATH.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={DB_PATH.name}"},
    )


@app.post("/restore", response_class=HTMLResponse)
async def restore_database(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    upload = fd.get("file")
    if not upload or not hasattr(upload, "read"):
        return HTMLResponse("No file uploaded", status_code=400)
    content = await upload.read()
    if len(content) > _MAX_RESTORE_BYTES:
        return HTMLResponse(f"File too large (max {_MAX_RESTORE_BYTES // (1024*1024)} MB)", status_code=400)
    if not content[:16].startswith(b"SQLite format 3"):
        return HTMLResponse("Not a valid SQLite database file", status_code=400)
    # Verify it's a real SQLite database, not just matching magic bytes
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name
    try:
        test_conn = _sqlite3.connect(tmp_path)
        result = test_conn.execute("PRAGMA integrity_check").fetchone()
        test_conn.close()
        if not result or result[0] != "ok":
            return HTMLResponse("Uploaded file is not a valid SQLite database", status_code=400)
    except Exception:
        return HTMLResponse("Uploaded file is not a valid SQLite database", status_code=400)
    finally:
        Path(tmp_path).unlink(missing_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    DB_PATH.write_bytes(content)
    try:
        init_db()
    except Exception as e:
        return HTMLResponse(
            f"Database restored but failed to initialize: {e}. "
            "If the backup is encrypted, ensure the same password is active.",
            status_code=500,
        )
    return RedirectResponse(url="/runs", status_code=303)


@app.get("/rotate-key", response_class=HTMLResponse)
def rotate_key_form(request: Request, error: str | None = None, success: str | None = None) -> Response:
    """Show key rotation form."""
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/rotate_key.html",
        {"request": request, "csrf": csrf, "error": error, "success": success},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rotate-key")
async def rotate_key_submit(request: Request) -> RedirectResponse:
    """Handle key rotation."""
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))

    current_password = str(fd.get("current_password", ""))
    new_password = str(fd.get("new_password", ""))
    confirm = str(fd.get("confirm_new_password", ""))

    if not current_password or not new_password:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('All fields are required')}",
            status_code=303,
        )
    if new_password != confirm:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('New passwords do not match')}",
            status_code=303,
        )

    if current_password != get_cached_password():
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus('Current password is incorrect')}",
            status_code=303,
        )

    try:
        validate_password(new_password)
        rotate_key(current_password, new_password)
        set_cached_password(new_password)
        set_password_in_keyring(new_password)
        return RedirectResponse(
            url=f"/rotate-key?success={urllib.parse.quote_plus('Key rotated successfully')}",
            status_code=303,
        )
    except Exception as e:
        return RedirectResponse(
            url=f"/rotate-key?error={urllib.parse.quote_plus(str(e)[:100])}",
            status_code=303,
        )


@app.get("/audit/verify")
def audit_verify() -> Response:
    """Walk the hash chain and report integrity status."""
    errors = verify_chain()
    status = "ok" if not errors else "integrity_errors"
    return Response(
        content=json.dumps({"status": status, "errors": errors}, indent=2),
        media_type="application/json",
    )


# ── Rule Pack Editor routes ────────────────────────────────────
# IMPORTANT: literal routes (/rule-packs/create, /rule-packs/import) MUST come
# before the parameterized route /rule-packs/{jurisdiction}/... to avoid
# FastAPI treating "create" or "import" as a jurisdiction path segment.


@app.get("/rule-packs", response_class=HTMLResponse)
def rule_packs_list(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    packs = list_rule_packs()
    resp = templates.TemplateResponse(
        "pages/rule_packs.html",
        {"request": request, "csrf": csrf, "packs": packs, "available_years": available_years},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/create")
async def rule_packs_create(request: Request) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    jurisdiction = _form_str(fd, "jurisdiction")
    year = int(_form_str(fd, "year") or "0")
    custom_name = _form_str(fd, "custom_name")
    info = create_empty_pack(jurisdiction, year, custom_name)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@app.get("/rule-packs/import", response_class=HTMLResponse)
def rule_packs_import_form(request: Request) -> HTMLResponse:
    """Stub for Task 5 — renders a placeholder import page."""
    csrf = _get_csrf_token(request)
    resp = HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><title>Import Rule Pack</title></head>"
            "<body><h1>Import YAML</h1><p>Full import form coming in Task 5.</p>"
            "<p><a href='/rule-packs'>Back to Rule Packs</a></p></body></html>"
        )
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/import", response_class=HTMLResponse)
async def rule_packs_import_post(request: Request) -> HTMLResponse:
    """Stub for Task 5 — accepts upload but just redirects back."""
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    return HTMLResponse(
        content=(
            "<!DOCTYPE html><html><head><title>Import Rule Pack</title></head>"
            "<body><h1>Import received</h1><p>Full processing coming in Task 5.</p>"
            "<p><a href='/rule-packs'>Back to Rule Packs</a></p></body></html>"
        )
    )


@app.get("/rule-packs/{jurisdiction}/{year}/{variant}", response_class=HTMLResponse)
def rule_pack_detail(
    request: Request, jurisdiction: str, year: int, variant: str
) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    detail = load_pack_detail(jurisdiction, year, variant)
    resp = templates.TemplateResponse(
        "pages/rule_pack_detail.html",
        {"request": request, "csrf": csrf, "pack": detail},
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/clone")
async def rule_pack_clone(
    request: Request, jurisdiction: str, year: int, variant: str
) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    custom_name = _form_str(fd, "custom_name")
    info = clone_pack(jurisdiction, year, variant, custom_name)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(
        url=f"/rule-packs/{info.jurisdiction}/{info.year}/{info.variant}",
        status_code=303,
    )


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/delete")
async def rule_pack_delete(
    request: Request, jurisdiction: str, year: int, variant: str
) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    delete_pack(jurisdiction, year, variant)
    _bust_pack_cache(jurisdiction, year)
    return RedirectResponse(url="/rule-packs", status_code=303)


@app.post("/rule-packs/{jurisdiction}/{year}/{variant}/validate", response_class=HTMLResponse)
async def rule_pack_validate(
    request: Request, jurisdiction: str, year: int, variant: str
) -> HTMLResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    errors = validate_rule_pack(jurisdiction, year, variant)
    detail = load_pack_detail(jurisdiction, year, variant)
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/rule_pack_detail.html",
        {
            "request": request,
            "csrf": csrf,
            "pack": detail,
            "validation_errors": errors,
            "validated": True,
        },
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.get("/rule-packs/{jurisdiction}/{year}/{variant}/export")
def rule_pack_export(
    request: Request, jurisdiction: str, year: int, variant: str
) -> Response:
    manifest_bytes, rules_bytes = export_yaml(jurisdiction, year, variant)
    combined = b"# === MANIFEST ===\n" + manifest_bytes + b"\n# === RULES ===\n" + rules_bytes
    filename = f"{jurisdiction}_{year}_{variant}.yaml"
    return Response(
        content=combined,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> HTMLResponse:
    return HTMLResponse(str(exc), status_code=400)
