# SPDX-License-Identifier: GPL-3.0-or-later
"""Tests for Milestone 3: Forms Support.

Covers: form_line on TraceNode, form data models, form mapper,
consistency checks, estimated tax payments, and form routes.
"""

import json as _json
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    AdjustmentsData,
    FilingStatus,
    Form1099DIVData,
    Form1099INTData,
    Form1099SSAData,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    TraceNode,
    W2Data,
)
from app.models.forms import Form1040Lines, FormPacket, Schedule1Lines
from app.services.database import init_db, list_return_runs
from app.services.form_mapper import map_return_run
from main import app

FED = RulePack.load(Path("rule_packs/federal/2024"))

CSRF = "test-csrf-token"


@pytest.fixture()
def _ensure_db() -> None:
    init_db()


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


def test_trace_node_has_form_line() -> None:
    node = TraceNode(
        node_id="test",
        rule_id="test.rule",
        rule_pack_version="1.0.0",
        description="Test",
        inputs={},
        result={"value": "100"},
        explanation="test",
        form_line="1040 Line 1a",
    )
    assert node.form_line == "1040 Line 1a"


def test_trace_node_form_line_defaults_empty() -> None:
    node = TraceNode(
        node_id="test",
        rule_id="test.rule",
        rule_pack_version="1.0.0",
        description="Test",
        inputs={},
        result={"value": "100"},
        explanation="test",
    )
    assert node.form_line == ""


# ═══════════════════════════════════════════════════════════════
# DOMAIN MODEL EXTENSIONS
# ═══════════════════════════════════════════════════════════════


def test_tax_exempt_interest_field() -> None:
    f = Form1099INTData(
        payer_name="Muni Bank",
        interest_income=Decimal("500"),
        tax_exempt_interest=Decimal("200"),
    )
    assert f.tax_exempt_interest == Decimal("200")


def test_estimated_tax_payments_field() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        estimated_tax_payments=Decimal("5000"),
    )
    assert inp.estimated_tax_payments == Decimal("5000")


def test_estimated_tax_payments_defaults_zero() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
    )
    assert inp.estimated_tax_payments == Decimal("0")


def test_total_qualified_dividends() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_divs=[
                    Form1099DIVData(ordinary_dividends=Decimal("1000"), qualified_dividends=Decimal("800")),
                    Form1099DIVData(ordinary_dividends=Decimal("500"), qualified_dividends=Decimal("300")),
                ],
            )
        ],
    )
    assert inp.total_qualified_dividends() == Decimal("1100")


def test_total_tax_exempt_interest() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                form_1099_ints=[
                    Form1099INTData(interest_income=Decimal("500"), tax_exempt_interest=Decimal("200")),
                    Form1099INTData(interest_income=Decimal("300"), tax_exempt_interest=Decimal("100")),
                ],
            )
        ],
    )
    assert inp.total_tax_exempt_interest() == Decimal("300")


# ═══════════════════════════════════════════════════════════════
# FORM DATA MODELS
# ═══════════════════════════════════════════════════════════════


def test_form_1040_lines_defaults() -> None:
    f = Form1040Lines()
    assert f.line_1a == Decimal("0")
    assert f.line_9 == Decimal("0")
    assert f.line_34 == Decimal("0")


def test_schedule_1_lines_defaults() -> None:
    s = Schedule1Lines()
    assert s.line_3 == Decimal("0")
    assert s.line_26 == Decimal("0")


def test_form_packet_construction() -> None:
    pkt = FormPacket(
        tax_year=2024,
        filing_status="mfj",
        form_1040=Form1040Lines(line_1a=Decimal("85000")),
        schedule_1=Schedule1Lines(),
    )
    assert pkt.form_1040.line_1a == Decimal("85000")
    assert pkt.consistency_errors == []


def test_form_packet_serializes_to_json() -> None:
    pkt = FormPacket(
        tax_year=2024,
        filing_status="single",
        form_1040=Form1040Lines(),
        schedule_1=Schedule1Lines(),
    )
    data = pkt.model_dump()
    assert data["tax_year"] == 2024
    assert "line_1a" in data["form_1040"]


# ═══════════════════════════════════════════════════════════════
# ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════


def test_estimated_payments_reduces_owed() -> None:
    """With $50k wages, $6k withheld, $2k estimated -> refund increases by $2k."""
    base = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run_base = CalculationEngine(FED, base).run()

    with_est = base.model_copy(update={"estimated_tax_payments": Decimal("2000")})
    run_est = CalculationEngine(FED, with_est).run()

    assert run_est.output.estimated_tax_payments == Decimal("2000.00")
    assert run_est.output.total_payments == Decimal("8000.00")
    assert run_est.output.refund_or_owed == run_base.output.refund_or_owed + 2000


def test_trace_nodes_have_form_line() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    wages_trace = next(t for t in run.trace if t.rule_id == "fed.2024.gross_income.wages")
    assert wages_trace.form_line == "1040 Line 1a"
    agi_trace = next(t for t in run.trace if t.rule_id == "fed.2024.agi.total")
    assert agi_trace.form_line == "1040 Line 11"


def test_zero_estimated_payments_backward_compatible() -> None:
    """Zero estimated payments produces same refund as before."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    assert run.output.estimated_tax_payments == Decimal("0.00")
    assert run.output.total_payments == Decimal("12000.00")
    assert run.output.refund_or_owed == Decimal("5768")


# ═══════════════════════════════════════════════════════════════
# FORM MAPPER
# ═══════════════════════════════════════════════════════════════


def test_map_return_run_basic() -> None:
    """Map a simple W-2 scenario to form lines."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.tax_year == 2024
    assert pkt.filing_status == "mfj"
    assert pkt.form_1040.line_1a == Decimal("85000.00")
    assert pkt.form_1040.line_9 == Decimal("85000.00")
    assert pkt.form_1040.line_11 == Decimal("85000.00")
    assert pkt.form_1040.line_13 == Decimal("29200")
    assert pkt.form_1040.line_15 == Decimal("55800")
    assert pkt.form_1040.line_16 == Decimal("6232")
    assert pkt.form_1040.line_25d == Decimal("12000.00")
    assert pkt.form_1040.line_33 == Decimal("12000.00")
    assert pkt.form_1040.line_34 == Decimal("5768")
    assert pkt.form_1040.line_37 == Decimal("0")


def test_map_return_run_informational_lines() -> None:
    """Qualified dividends and tax-exempt interest appear on form."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
                form_1099_ints=[
                    Form1099INTData(interest_income=Decimal("500"), tax_exempt_interest=Decimal("200")),
                ],
                form_1099_divs=[
                    Form1099DIVData(ordinary_dividends=Decimal("1000"), qualified_dividends=Decimal("800")),
                ],
                form_1099_ssas=[
                    Form1099SSAData(total_benefits=Decimal("18000")),
                ],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.form_1040.line_2a == Decimal("200")
    assert pkt.form_1040.line_3a == Decimal("800")
    assert pkt.form_1040.line_6a == Decimal("18000")


def test_map_return_run_schedule1() -> None:
    """Schedule 1 lines are populated for adjustments."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))],
            )
        ],
        adjustments=AdjustmentsData(
            student_loan_interest=Decimal("2500"),
            educator_expenses=Decimal("300"),
        ),
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.schedule_1.line_21 == Decimal("2500.00")
    assert pkt.schedule_1.line_11 == Decimal("300.00")
    assert pkt.schedule_1.line_26 == Decimal("2800.00")
    assert pkt.form_1040.line_10 == Decimal("2800.00")


def test_map_return_run_amount_owed() -> None:
    """When tax > payments, line_37 shows amount owed."""
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("5000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)

    assert pkt.form_1040.line_37 > 0
    assert pkt.form_1040.line_34 == Decimal("0")


def test_consistency_checks_pass_for_valid_run() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.MFJ,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_consistency_checks_pass_zero_income() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("0"), federal_withheld=Decimal("0"))],
            )
        ],
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_consistency_checks_pass_with_estimated_payments() -> None:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("10000"))],
            )
        ],
        estimated_tax_payments=Decimal("5000"),
    )
    run = CalculationEngine(FED, inp).run()
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []
    assert pkt.form_1040.line_26 == Decimal("5000.00")
    assert pkt.form_1040.line_33 == Decimal("15000.00")


# ═══════════════════════════════════════════════════════════════
# ROUTE TESTS
# ═══════════════════════════════════════════════════════════════


def test_calculate_with_adjustments(_ensure_db: None) -> None:
    client = _client()
    form = {
        "csrf_token": CSRF,
        "tax_year": "2024",
        "filing_status": "single",
        "p_first": "Test",
        "p_last": "User",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "50000",
        "p_w2_0_federal_withheld": "6000",
        "adj_student_loan": "2500",
        "adj_educator": "300",
        "adj_hsa": "1000",
        "adj_ira": "3000",
        "estimated_payments": "2000",
        "other_income": "500",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303

    runs = list_return_runs()
    assert runs


def _create_run(client: TestClient) -> str:
    form = {
        "csrf_token": CSRF,
        "tax_year": "2024",
        "filing_status": "mfj",
        "p_first": "Jane",
        "p_last": "Doe",
        "p_w2_0_employer": "Acme",
        "p_w2_0_wages": "85000",
        "p_w2_0_federal_withheld": "12000",
    }
    r = client.post("/calculate", data=form, follow_redirects=False)
    assert r.status_code == 303
    runs = list_return_runs()
    return str(runs[0]["id"])


def test_forms_view_route(_ensure_db: None) -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/forms")
    assert r.status_code == 200
    assert "Form 1040" in r.text
    assert "Line 1a" in r.text or "1a" in r.text


def test_forms_view_not_found(_ensure_db: None) -> None:
    client = _client()
    r = client.get("/runs/nonexistent-id/forms")
    assert r.status_code == 404


def test_forms_export_route(_ensure_db: None) -> None:
    client = _client()
    run_id = _create_run(client)
    r = client.get(f"/runs/{run_id}/export/forms")
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    data = _json.loads(r.content)
    assert "form_1040" in data
    assert "schedule_1" in data
