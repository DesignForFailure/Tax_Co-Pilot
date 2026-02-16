"""Tax Copilot — FastAPI Application (MVP Vertical Slice).

Sections:
- App setup + middleware: localhost hardening defaults.
- Template wiring: Jinja2 HTML rendering.
- Input parsing: strict-ish money parsing and form extraction.
- CSRF: double-submit cookie pattern to protect POSTs.
- Routes: dashboard (latest run), calculate (GET/POST), runs list, run detail.
- Error handling: return safe 400s for invalid user input.

Future improvements:
- Add security headers (CSP, Referrer-Policy, etc.) if served beyond localhost.
- Add rate limiting if ever exposed over a network.
- Add multi-taxpayer form support and CSV import endpoints.
"""

from __future__ import annotations

import json
import secrets
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import config as encryption_config
from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.database import (
    DB_PATH,
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

    return response


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
            from app.models.domain import ReturnRun

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


@app.post("/calculate")
def calculate_submit(
    request: Request,
    csrf_token: str = Form(""),
    tax_year: int = Form(2024),
    filing_status: str = Form("mfj"),
    p_first: str = Form(""),
    p_last: str = Form(""),
    p_employer: str = Form(""),
    p_wages: str = Form("0"),
    p_withheld: str = Form("0"),
    cg_desc: str = Form(""),
    cg_proceeds: str = Form("0"),
    cg_basis: str = Form("0"),
) -> RedirectResponse:
    _verify_csrf(request, csrf_token)

    # Bound string inputs to prevent oversized payloads (defense-in-depth).
    _MAX_TEXT = 200
    for label, val in [
        ("first name", p_first),
        ("last name", p_last),
        ("employer", p_employer),
        ("description", cg_desc),
    ]:
        if len(val or "") > _MAX_TEXT:
            raise ValueError(f"{label} exceeds {_MAX_TEXT} characters")

    # W-2 amounts must be non-negative; wages/withholding are monetary values.
    first_name = (p_first or "").strip()
    last_name = (p_last or "").strip()
    if not first_name:
        raise ValueError("first name is required")
    if not last_name:
        raise ValueError("last name is required")

    w2 = W2Data(
        employer_name=(p_employer or "").strip(),
        wages=_parse_money(p_wages, allow_negative=False),
        federal_withheld=_parse_money(p_withheld, allow_negative=False),
    )

    primary = Taxpayer(
        role=TaxpayerRole.PRIMARY,
        first_name=first_name,
        last_name=last_name,
        w2s=[w2],
    )

    # 1099-B proceeds/basis must be non-negative; (losses appear via proceeds < basis).
    proceeds = _parse_money(cg_proceeds, allow_negative=False)
    if proceeds > 0:
        primary.form_1099_bs.append(
            Form1099BData(
                description=(cg_desc or "Capital gain").strip(),
                proceeds=proceeds,
                cost_basis=_parse_money(cg_basis, allow_negative=False),
            )
        )

    inputs = TaxReturnInput(
        tax_year=tax_year,
        filing_status=FilingStatus(filing_status),
        taxpayers=[primary],
    )

    run = CalculationEngine(rule_pack, inputs).run()
    run_dict = json.loads(run.model_dump_json())
    save_return_run(run_dict)

    return RedirectResponse(url="/", status_code=303)


@app.get("/runs", response_class=HTMLResponse)
def past_runs(request: Request) -> HTMLResponse:
    runs = list_return_runs()
    return templates.TemplateResponse("pages/runs.html", {"request": request, "runs": runs})


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def view_run(request: Request, run_id: str) -> HTMLResponse:
    run_data = get_return_run(run_id)
    if not run_data:
        return HTMLResponse("Run not found", status_code=404)

    run_data["input_snapshot"] = json.loads(run_data["input_snapshot_json"])
    run_data["output"] = json.loads(run_data["output_json"])
    run_data["trace"] = json.loads(run_data["trace_json"])

    from app.models.domain import ReturnRun

    run = ReturnRun(**{k: v for k, v in run_data.items() if not k.endswith("_json")})
    return templates.TemplateResponse("pages/dashboard.html", {"request": request, "run": run})


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
