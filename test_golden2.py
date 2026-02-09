"""Tax Copilot — Golden Tests (Milestones 1–5).

Tests cover:
  M1: Federal bracket calc, trace completeness
  M2: Two-person filing, multiple W-2s, 1099s, CSV import
  M3: What-If (MFJ vs MFS comparison)
  M4: Georgia state tax computation
  M5: Audit export (JSON + HTML generation)
"""
import json
import tempfile
from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.engine.whatif import WhatIfEngine
from app.models.domain import (
    FilingStatus, Form1099BData, Form1099INTData, Form1099DIVData,
    Taxpayer, TaxpayerRole, TaxReturnInput, W2Data, ScenarioComparison,
)
from app.services.csv_import import import_csv
from app.services.audit_export import export_json, generate_audit_html

FED = RulePack(Path("rule_packs/federal/2024"))
GA = RulePack(Path("rule_packs/state/GA/2024"))


# ═══════════════════════════════════════════════════════════════
# M1: FEDERAL BASICS
# ═══════════════════════════════════════════════════════════════

def test_single_w2_mfj():
    """$85k wages, MFJ. Tax: 10% on $23,200 + 12% on $32,600 = $6,232."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("85000.00")
    assert run.output.standard_deduction == Decimal("29200")
    assert run.output.taxable_income == Decimal("55800")
    assert run.output.federal_tax == Decimal("6232")
    assert run.output.refund_or_owed == Decimal("5768")


def test_single_filing():
    """$50k single. Taxable $35,400. Tax $4,016."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("50000"), federal_withheld=Decimal("6000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == Decimal("35400")
    assert run.output.federal_tax == Decimal("4016")


def test_zero_income():
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("0"), federal_withheld=Decimal("0"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.federal_tax == Decimal("0")


def test_high_income_single():
    """$300k single → taxable $285,400 → $70,265 tax."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("300000"), federal_withheld=Decimal("80000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.taxable_income == Decimal("285400")
    assert run.output.federal_tax == Decimal("70265")


def test_trace_completeness():
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("100000"), federal_withheld=Decimal("15000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    ids = {t.rule_id for t in run.trace}
    expected = {"fed.2024.gross_income.wages", "fed.2024.gross_income.interest",
                "fed.2024.gross_income.dividends", "fed.2024.gross_income.capital_gains",
                "fed.2024.gross_income.total", "fed.2024.agi.total", "fed.2024.standard_deduction",
                "fed.2024.taxable_income", "fed.2024.tax.brackets",
                "fed.2024.total_withholding", "fed.2024.refund_or_owed"}
    assert expected == ids


# ═══════════════════════════════════════════════════════════════
# M2: TWO-PERSON, MULTIPLE INCOME TYPES, CSV
# ═══════════════════════════════════════════════════════════════

def test_two_person_mfj():
    """Primary $85k + Spouse $35k = $120k combined. MFJ."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="John", last_name="Doe",
                 w2s=[W2Data(employer_name="Army", wages=Decimal("85000"), federal_withheld=Decimal("12000"))]),
        Taxpayer(role=TaxpayerRole.SPOUSE, first_name="Jane", last_name="Doe",
                 w2s=[W2Data(employer_name="Cafe", wages=Decimal("35000"), federal_withheld=Decimal("4000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("120000.00")
    assert run.output.total_withholding == Decimal("16000.00")
    # Taxable: 120000 - 29200 = 90800
    assert run.output.taxable_income == Decimal("90800")


def test_multiple_w2s_per_person():
    """Spouse with 2 W-2s."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))]),
        Taxpayer(role=TaxpayerRole.SPOUSE, first_name="C", last_name="D",
                 w2s=[
                     W2Data(employer_name="Y", wages=Decimal("20000"), federal_withheld=Decimal("2000")),
                     W2Data(employer_name="Z", wages=Decimal("15000"), federal_withheld=Decimal("1500")),
                 ]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.output.gross_income == Decimal("115000.00")
    assert run.output.total_withholding == Decimal("13500.00")


def test_1099_income():
    """W-2 + 1099-INT + 1099-DIV + 1099-B."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"))],
                 form_1099_ints=[Form1099INTData(payer_name="Bank", interest_income=Decimal("500"))],
                 form_1099_divs=[Form1099DIVData(payer_name="Broker", ordinary_dividends=Decimal("1200"))],
                 form_1099_bs=[Form1099BData(description="BTC", proceeds=Decimal("900"), cost_basis=Decimal("200"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    # 80000 + 500 + 1200 + 700 = 82400
    assert run.output.gross_income == Decimal("82400.00")


def test_csv_import_w2():
    csv = """employer_name,wages,federal_withheld,state,state_withheld
US Army,85000,12000,TX,0
Walmart,25000,3000,GA,1500
"""
    records, errors = import_csv(csv, "W2")
    assert len(errors) == 0
    assert len(records) == 2
    assert records[0].employer_name == "US Army"
    assert records[0].wages == Decimal("85000")
    assert records[1].state == "GA"


def test_csv_import_1099b():
    csv = """description,proceeds,cost_basis,is_long_term
BTC sale,900,200,false
ETH sale,5000,3000,true
"""
    records, errors = import_csv(csv, "1099-B")
    assert len(errors) == 0
    assert len(records) == 2
    assert records[0].net_gain == Decimal("700")
    assert records[1].is_long_term is True


# ═══════════════════════════════════════════════════════════════
# M3: WHAT-IF ENGINE
# ═══════════════════════════════════════════════════════════════

def test_whatif_mfj_vs_mfs():
    """For a couple with unequal income, MFJ should beat MFS."""
    base = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))]),
        Taxpayer(role=TaxpayerRole.SPOUSE, first_name="C", last_name="D",
                 w2s=[W2Data(employer_name="Y", wages=Decimal("35000"), federal_withheld=Decimal("4000"))]),
    ])
    whatif = WhatIfEngine(FED)
    comparison = whatif.compare_filing_status(base)

    assert comparison.scenario_a.filing_status == FilingStatus.MFJ
    assert comparison.scenario_b.filing_status == FilingStatus.MFS
    assert len(comparison.diffs) > 0
    # MFJ should produce lower tax for unequal incomes
    assert comparison.scenario_a.total_tax < comparison.scenario_b.total_tax
    assert comparison.recommendation == comparison.scenario_a.scenario_name
    assert comparison.savings > 0


def test_whatif_equal_income():
    """Equal incomes — MFJ should still beat MFS due to bracket structure."""
    base = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("60000"), federal_withheld=Decimal("8000"))]),
        Taxpayer(role=TaxpayerRole.SPOUSE, first_name="C", last_name="D",
                 w2s=[W2Data(employer_name="Y", wages=Decimal("60000"), federal_withheld=Decimal("8000"))]),
    ])
    whatif = WhatIfEngine(FED)
    comparison = whatif.compare_filing_status(base)
    # MFJ should produce lower or equal tax (MFS brackets are narrower)
    assert comparison.scenario_a.total_tax <= comparison.scenario_b.total_tax
    assert comparison.savings >= 0


# ═══════════════════════════════════════════════════════════════
# M4: GEORGIA STATE TAX
# ═══════════════════════════════════════════════════════════════

def test_georgia_state_tax():
    """GA: $85k AGI, MFJ. GA deduction $7100, exemption $7400. Taxable: $70,500. Tax: $70,500 * 5.39% = $3,800."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 domicile_state="GA",
                 w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"),
                             state="GA", state_wages=Decimal("85000"), state_withheld=Decimal("4000"))]),
    ])
    run = CalculationEngine(FED, inp, {"GA": GA}).run()

    assert len(run.state_outputs) == 1
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    assert ga.state_agi == Decimal("85000.00")
    assert ga.state_standard_deduction == Decimal("7100")
    # personal exemption MFJ = 7400
    # taxable = 85000 - 7100 - 7400 = 70500
    assert ga.state_taxable_income == Decimal("70500")
    # tax = 70500 * 0.0539 = 3799.95 → 3800
    assert ga.state_tax == Decimal("3800")
    assert ga.state_withholding == Decimal("4000.00")
    assert ga.state_refund_or_owed == Decimal("200")


def test_texas_no_state_tax():
    """TX has no income tax — should produce no state outputs."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 domicile_state="TX",
                 w2s=[W2Data(employer_name="X", wages=Decimal("80000"), federal_withheld=Decimal("10000"),
                             state="TX")]),
    ])
    # TX not in STATE_PACKS — should be skipped
    run = CalculationEngine(FED, inp, {}).run()
    assert len(run.state_outputs) == 0


def test_multistate_ga_and_tx():
    """Primary in TX (no state tax), spouse in GA (state tax)."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="John", last_name="Doe",
                 domicile_state="TX", is_active_duty_military=True,
                 w2s=[W2Data(employer_name="Army", wages=Decimal("85000"), federal_withheld=Decimal("12000"),
                             state="TX")]),
        Taxpayer(role=TaxpayerRole.SPOUSE, first_name="Jane", last_name="Doe",
                 domicile_state="GA",
                 w2s=[W2Data(employer_name="Cafe", wages=Decimal("35000"), federal_withheld=Decimal("4000"),
                             state="GA", state_wages=Decimal("35000"), state_withheld=Decimal("1800"))]),
    ])
    run = CalculationEngine(FED, inp, {"GA": GA}).run()
    # Federal: $120k combined
    assert run.output.gross_income == Decimal("120000.00")
    # GA state: should exist (spouse works in GA)
    assert len(run.state_outputs) == 1
    ga = run.state_outputs[0]
    assert ga.state == "GA"
    assert ga.state_withholding == Decimal("1800.00")


# ═══════════════════════════════════════════════════════════════
# M5: AUDIT EXPORT
# ═══════════════════════════════════════════════════════════════

def test_json_export():
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("85000"), federal_withheld=Decimal("12000"))]),
    ])
    run = CalculationEngine(FED, inp).run()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = Path(f.name)
    export_json(run, path)

    data = json.loads(path.read_text())
    assert data["tax_year"] == 2024
    assert data["output"]["federal_tax"] == "6232"
    assert len(data["trace"]) > 0
    assert "input_snapshot" in data
    path.unlink()


def test_html_audit_report():
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="John", last_name="Doe",
                 domicile_state="GA", is_active_duty_military=True,
                 w2s=[W2Data(employer_name="Army", wages=Decimal("85000"), federal_withheld=Decimal("12000"),
                             state="GA", state_wages=Decimal("85000"), state_withheld=Decimal("4000"))]),
    ])
    run = CalculationEngine(FED, inp, {"GA": GA}).run()
    html = generate_audit_html(run)

    assert "Tax Copilot" in html
    assert "John Doe" in html
    assert "85,000" in html
    assert "Georgia" in html or "GA" in html
    assert "Disclaimer" in html
    assert "fed.2024.tax.brackets" in html


def test_immutable_snapshot():
    """ReturnRun must contain a frozen input snapshot + rule checksums."""
    inp = TaxReturnInput(tax_year=2024, filing_status=FilingStatus.MFJ, taxpayers=[
        Taxpayer(role=TaxpayerRole.PRIMARY, first_name="A", last_name="B",
                 w2s=[W2Data(employer_name="X", wages=Decimal("75000"), federal_withheld=Decimal("10000"))]),
    ])
    run = CalculationEngine(FED, inp).run()
    assert run.input_snapshot.taxpayers[0].w2s[0].wages == Decimal("75000")
    assert run.rule_pack_version == "1.0.0"
    assert len(run.rule_pack_checksum) == 64


# ═══════════════════════════════════════════════════════════════
# RUNNER
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    tests = [
        # M1
        test_single_w2_mfj, test_single_filing, test_zero_income,
        test_high_income_single, test_trace_completeness,
        # M2
        test_two_person_mfj, test_multiple_w2s_per_person, test_1099_income,
        test_csv_import_w2, test_csv_import_1099b,
        # M3
        test_whatif_mfj_vs_mfs, test_whatif_equal_income,
        # M4
        test_georgia_state_tax, test_texas_no_state_tax, test_multistate_ga_and_tx,
        # M5
        test_json_export, test_html_audit_report, test_immutable_snapshot,
    ]
    passed = failed = 0
    for t in tests:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
