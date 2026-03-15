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
    FilingStatus,
    Form1099BData,
    Form1099DIVData,
    Form1099INTData,
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
    delete_return_run,
    get_return_run,
    init_db,
    list_return_runs,
    save_return_run,
    set_cached_password,
)
from app.services.encryption import (
    DatabaseState,
    PasswordValidationError,
    detect_encryption_state,
    get_password,
    set_password_in_keyring,
    validate_password,
)

# ─── FastAPI app and basic hardening ───────────────────────────
# TrustedHostMiddleware mitigates DNS rebinding / Host header attacks.
# Keep this locked to localhost unless you intentionally expose the service.
app = FastAPI(title="Tax Copilot", version="0.1.0")
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

RULE_PACK_DIR = BASE_DIR / "rule_packs" / "federal" / "2024"
rule_pack = RulePack.load(RULE_PACK_DIR)


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


@app.on_event("startup")
def startup() -> None:
    """Initialize database on startup.

    Handles encryption setup:
    1. If encryption enabled and DB encrypted, password must be provided via env/keyring
    2. If encryption enabled and DB unencrypted, allow access (migration handled via UI)
    3. If encryption disabled, proceed normally
    """
    if encryption_config.enabled:
        db_state = detect_encryption_state(DB_PATH)

        if db_state in (DatabaseState.ENCRYPTED_SQLCIPHER, DatabaseState.ENCRYPTED_PYTHON):
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
        if db_state in (DatabaseState.ENCRYPTED_SQLCIPHER, DatabaseState.ENCRYPTED_PYTHON):
            from app.services.database import get_cached_password

            if not get_cached_password():
                # Redirect to unlock page
                return RedirectResponse(url="/unlock", status_code=303)

    runs = list_return_runs()
    run = None
    if runs:
        run_id = runs[0]["id"]
        run_data = get_return_run(run_id)
        if run_data:
            run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
            run_data["output"] = json.loads(run_data["output_json"])
            run_data["trace"] = json.loads(run_data["trace_json"])
            run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})

    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse("pages/dashboard.html", {"request": request, "run": run})
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.get("/calculate", response_class=HTMLResponse)
def calculate_form(request: Request) -> HTMLResponse:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse("pages/calculate.html", {"request": request, "csrf": csrf})
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


# ─── Form parsing helpers ──────────────────────────────────────

_MAX_TEXT = 200
_MAX_INDEXED_ENTRIES = 50  # Cap on dynamic rows per section (defense-in-depth)
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
    filing_status = FilingStatus(str(fd.get("filing_status", "mfj") or "mfj"))

    primary = _parse_taxpayer(fd, "p", TaxpayerRole.PRIMARY)
    taxpayers: list[Taxpayer] = [primary]

    # Spouse is only expected for MFJ/MFS
    if filing_status in (FilingStatus.MFJ, FilingStatus.MFS):
        s_first = _form_str(fd, "s_first")
        s_last = _form_str(fd, "s_last")
        # Only add spouse if they provided at least a name or income data
        has_spouse_income = bool(
            _collect_indices(fd, "s_w2")
            or _collect_indices(fd, "s_1099int")
            or _collect_indices(fd, "s_1099div")
            or _collect_indices(fd, "s_1099b")
        )
        if s_first or s_last or has_spouse_income:
            taxpayers.append(_parse_taxpayer(fd, "s", TaxpayerRole.SPOUSE))

    return TaxReturnInput(
        tax_year=tax_year,
        filing_status=filing_status,
        taxpayers=taxpayers,
    )


# ─── Calculate route ─────────────────────────────────────────────


@app.post("/calculate")
async def calculate_submit(request: Request) -> RedirectResponse:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))

    inputs = _parse_tax_input_from_form(fd)

    run = CalculationEngine(rule_pack, inputs).run()
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
    run_a_data["input_snapshot"] = json.loads(run_a_data["input_snapshot_json"])
    run_a_data["output"] = json.loads(run_a_data["output_json"])
    run_a_data["trace"] = json.loads(run_a_data["trace_json"])
    run_a = ReturnRun(**{k: v for k, v in run_a_data.items() if not k.endswith("_json")})
    run_b_data["input_snapshot"] = json.loads(run_b_data["input_snapshot_json"])
    run_b_data["output"] = json.loads(run_b_data["output_json"])
    run_b_data["trace"] = json.loads(run_b_data["trace_json"])
    run_b = ReturnRun(**{k: v for k, v in run_b_data.items() if not k.endswith("_json")})
    output_fields = [
        "gross_income",
        "agi",
        "standard_deduction",
        "taxable_income",
        "federal_tax",
        "total_withholding",
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

    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})
    return templates.TemplateResponse("pages/dashboard.html", {"request": request, "run": run})


# ─── What-If Comparison ──────────────────────────────────────


@app.get("/whatif", response_class=HTMLResponse)
def whatif_form(request: Request) -> Response:
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/whatif.html", {"request": request, "csrf": csrf}
    )
    resp.set_cookie("csrf", csrf, httponly=True, samesite="strict")
    return resp


@app.post("/whatif", response_class=HTMLResponse)
async def whatif_submit(request: Request) -> Response:
    fd = await request.form()
    _verify_csrf(request, str(fd.get("csrf_token", "")))
    inputs = _parse_tax_input_from_form(fd)
    engine = WhatIfEngine(rule_pack)
    comparison = engine.compare_filing_status(inputs)
    csrf = _get_csrf_token(request)
    resp = templates.TemplateResponse(
        "pages/whatif.html",
        {"request": request, "csrf": csrf, "comparison": comparison},
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
    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})
    # Serialize to indented JSON matching what export_json() would write to disk.
    json_bytes = json.dumps(
        json.loads(run.model_dump_json()), indent=2, ensure_ascii=False
    ).encode("utf-8")
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="run_{run_id}.json"'},
    )


@app.get("/runs/{run_id}/export/html")
def export_run_html(run_id: str) -> Response:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)
    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])
    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})
    html_content = generate_audit_html(run)
    return StreamingResponse(
        io.BytesIO(html_content.encode("utf-8")),
        media_type="text/html",
        headers={"Content-Disposition": f'attachment; filename="audit_{run_id}.html"'},
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
        return RedirectResponse(url="/unlock?error=Password+is+required", status_code=303)

    try:
        # Validate password format
        validate_password(password)

        # Try to open database with this password
        db_state = detect_encryption_state(DB_PATH)
        if db_state not in (DatabaseState.ENCRYPTED_SQLCIPHER, DatabaseState.ENCRYPTED_PYTHON):
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

        # Redirect to dashboard
        return RedirectResponse(url="/", status_code=303)

    except PasswordValidationError as e:
        error_msg = str(e).replace(" ", "+")
        return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)
    except ValueError:
        # Wrong password or corrupted database
        error_msg = "Incorrect+password+or+corrupted+database"
        return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)
    except Exception as e:
        error_msg = f"Unlock+failed:+{str(e)[:50]}"
        return RedirectResponse(url=f"/unlock?error={error_msg}", status_code=303)


@app.exception_handler(ValueError)
def value_error_handler(request: Request, exc: ValueError) -> HTMLResponse:
    return HTMLResponse(str(exc), status_code=400)
