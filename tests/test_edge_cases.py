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

"""Boundary and degenerate-input battery (0.9.0 arc, leg 3).

Probes the exact edges of every major federal computation: bracket
boundaries for all filing statuses, the QDCGT 0%/15%/20% stacking
breakpoints, phaseout thresholds (CTC, EIC completion, NIIT,
Additional Medicare), the Social Security provisional-income corners,
the capital-loss limit, zero-income and cents-precision runs.
(Education-credit MAGI edges are pinned in test_education_credits.py.)
Expected ordinary tax is computed inside the test from the
IRS-verified 2024 bracket constants, independent of the pack tables.
"""

from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    Form1099BData,
    Form1099INTData,
    Form1099SSAData,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)
from app.services.form_mapper import map_return_run

FED = {y: RulePack.load(Path("rule_packs") / "federal" / str(y)) for y in (2023, 2024, 2025)}

# IRS Rev. Proc. 2023-34 ordinary brackets (upper bounds per rate).
BRACKETS_2024 = {
    "single": [
        ("11600", "0.10"),
        ("47150", "0.12"),
        ("100525", "0.22"),
        ("191950", "0.24"),
        ("243725", "0.32"),
        ("609350", "0.35"),
        (None, "0.37"),
    ],
    "mfj": [
        ("23200", "0.10"),
        ("94300", "0.12"),
        ("201050", "0.22"),
        ("383900", "0.24"),
        ("487450", "0.32"),
        ("731200", "0.35"),
        (None, "0.37"),
    ],
    "hoh": [
        ("16550", "0.10"),
        ("63100", "0.12"),
        ("100500", "0.22"),
        ("191950", "0.24"),
        ("243700", "0.32"),
        ("609350", "0.35"),
        (None, "0.37"),
    ],
}
STD_2024 = {"single": Decimal("14600"), "mfj": Decimal("29200"), "hoh": Decimal("21900")}


def reference_tax(taxable: Decimal, status: str) -> Decimal:
    """Independent cumulative bracket tax from the constants above."""
    total = Decimal("0")
    lower = Decimal("0")
    for upper, rate in BRACKETS_2024[status]:
        top = Decimal(upper) if upper is not None else taxable
        span = min(taxable, top) - lower
        if span <= 0:
            break
        total += span * Decimal(rate)
        lower = top
    return total.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def _taxpayer(wages: str) -> Taxpayer:
    return Taxpayer(
        role=TaxpayerRole.PRIMARY,
        first_name="Edge",
        last_name="Case",
        w2s=[W2Data(employer_name="Acme", wages=Decimal(wages))] if wages != "0" else [],
    )


def _run(inp: TaxReturnInput) -> tuple[CalculationEngine, ReturnRun]:
    engine = CalculationEngine(FED[inp.tax_year], inp)
    return engine, engine.run()


def _simple(
    wages: str, fs: FilingStatus = FilingStatus.SINGLE, year: int = 2024
) -> tuple[CalculationEngine, ReturnRun]:
    return _run(TaxReturnInput(tax_year=year, filing_status=fs, taxpayers=[_taxpayer(wages)]))


# ─── Ordinary bracket boundaries, every 2024 edge ─────────────


@pytest.mark.parametrize("status", ["single", "mfj", "hoh"])
@pytest.mark.parametrize("offset", [Decimal("0"), Decimal("1")])
def test_every_bracket_edge_matches_reference(status: str, offset: Decimal) -> None:
    """Taxable income exactly at (and $1 above) each bracket edge."""
    fs = FilingStatus(status)
    for upper, _rate in BRACKETS_2024[status][:-1]:
        assert upper is not None
        taxable = Decimal(upper) + offset
        wages = taxable + STD_2024[status]
        e, _ = _simple(str(wages), fs)
        assert e.resolved["fed.2024.taxable_income"] == taxable
        got = e.resolved["fed.2024.tax.brackets"]
        assert got == reference_tax(taxable, status), (status, upper, offset, got)


def test_mfs_brackets_are_half_mfj_at_the_top_edge() -> None:
    """MFS 37% starts at $365,600 (half of MFJ's $731,200)."""
    e, _ = _simple(str(Decimal("365600") + Decimal("14600")), FilingStatus.MFS)
    below = e.resolved["fed.2024.tax.brackets"]
    e, _ = _simple(str(Decimal("365700") + Decimal("14600")), FilingStatus.MFS)
    above = e.resolved["fed.2024.tax.brackets"]
    assert above - below == (Decimal("100") * Decimal("0.37")).quantize(Decimal("1"))


# ─── QDCGT stacking breakpoints (single, 2024) ────────────────


def _with_ltcg(
    wages: str, gain: str, fs: FilingStatus = FilingStatus.SINGLE
) -> tuple[CalculationEngine, ReturnRun]:
    tp = _taxpayer(wages)
    tp.form_1099_bs.append(
        Form1099BData(
            description="Fund",
            proceeds=Decimal(gain),
            cost_basis=Decimal("0"),
            is_long_term=True,
        )
    )
    return _run(TaxReturnInput(tax_year=2024, filing_status=fs, taxpayers=[tp]))


def test_ltcg_entirely_in_0_percent_bracket() -> None:
    """Ordinary $40k + $5k LTCG: total $45k < $47,025 → LTCG tax $0."""
    e, _ = _with_ltcg("54600", "5000")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("0")


def test_ltcg_straddles_the_0_15_breakpoint() -> None:
    """Ordinary $40k + $10k LTCG: $7,025 at 0%, $2,975 at 15% = $446."""
    e, _ = _with_ltcg("54600", "10000")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("446")


def test_ltcg_straddles_the_15_20_breakpoint() -> None:
    """Ordinary $500k + $30k LTCG: $18,900 at 15% + $11,100 at 20% = $5,055."""
    e, _ = _with_ltcg("514600", "30000")
    assert e.resolved["fed.2024.tax.ltcg"] == Decimal("5055")


# ─── Phaseout thresholds land exactly ─────────────────────────


def test_ctc_phaseout_starts_strictly_above_threshold() -> None:
    """AGI exactly $200k: zero units; $200,001: one $50 unit (ROUND_UP)."""
    e, _ = _run(
        TaxReturnInput(
            tax_year=2024,
            filing_status=FilingStatus.SINGLE,
            qualifying_children=1,
            taxpayers=[_taxpayer("200000")],
        )
    )
    assert e.resolved["fed.2024.credits.ctc.phaseout"] == Decimal("0")
    e, _ = _run(
        TaxReturnInput(
            tax_year=2024,
            filing_status=FilingStatus.SINGLE,
            qualifying_children=1,
            taxpayers=[_taxpayer("200001")],
        )
    )
    assert e.resolved["fed.2024.credits.ctc.phaseout"] == Decimal("50")


def test_eic_reaches_zero_at_completion_point() -> None:
    """Single, 1 child: EIC positive just below $49,084 and zero at it."""
    e, _ = _run(
        TaxReturnInput(
            tax_year=2024,
            filing_status=FilingStatus.SINGLE,
            qualifying_children=1,
            taxpayers=[_taxpayer("49000")],
        )
    )
    assert e.resolved["fed.2024.credits.eic.final"] > 0
    e, _ = _run(
        TaxReturnInput(
            tax_year=2024,
            filing_status=FilingStatus.SINGLE,
            qualifying_children=1,
            taxpayers=[_taxpayer("49084")],
        )
    )
    assert e.resolved["fed.2024.credits.eic.final"] == Decimal("0")


def test_additional_medicare_zero_at_and_pennies_above_threshold() -> None:
    e, _ = _simple("200000")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("0")
    # $1 over: 0.9% x 1 = $0.009 -> rounds to $0
    e, _ = _simple("200001")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("0")
    e, _ = _simple("200100")
    assert e.resolved["fed.2024.addl_medicare.final"] == Decimal("1")


def test_niit_zero_at_threshold_with_investment_income() -> None:
    """Wages $190k + $10k interest = MAGI exactly $200k → NIIT $0."""
    tp = _taxpayer("190000")
    tp.form_1099_ints.append(Form1099INTData(payer_name="Bank", interest_income=Decimal("10000")))
    e, _ = _run(TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[tp]))
    assert e.resolved["fed.2024.niit.final"] == Decimal("0")


# ─── Social Security provisional-income corners ───────────────


def _with_ss(other_income: str, benefits: str) -> tuple[CalculationEngine, ReturnRun]:
    tp = _taxpayer("0")
    if Decimal(other_income) > 0:
        tp.form_1099_ints.append(
            Form1099INTData(payer_name="Bank", interest_income=Decimal(other_income))
        )
    tp.form_1099_ssas.append(Form1099SSAData(total_benefits=Decimal(benefits)))
    return _run(TaxReturnInput(tax_year=2024, filing_status=FilingStatus.SINGLE, taxpayers=[tp]))


def test_ss_untaxed_at_provisional_exactly_25k() -> None:
    """Interest $15k + half of $20k SS = provisional exactly $25,000 → $0."""
    e, _ = _with_ss("15000", "20000")
    assert e.resolved["fed.2024.gross_income.social_security"] == Decimal("0")


def test_ss_50_percent_band_midpoint() -> None:
    """Provisional $30k: min(50% × $5k excess, 50% × SS) = $2,500."""
    e, _ = _with_ss("20000", "20000")
    assert e.resolved["fed.2024.gross_income.social_security"] == Decimal("2500")


def test_ss_85_percent_band() -> None:
    """Provisional $40k: 85% × $6k + $4,500 = $9,600 (under 85% × SS)."""
    e, _ = _with_ss("30000", "20000")
    assert e.resolved["fed.2024.gross_income.social_security"] == Decimal("9600")


# ─── Capital loss limit edges ─────────────────────────────────


def _with_loss(
    loss: str, fs: FilingStatus = FilingStatus.SINGLE
) -> tuple[CalculationEngine, ReturnRun]:
    tp = _taxpayer("50000")
    tp.form_1099_bs.append(
        Form1099BData(
            description="Stock",
            proceeds=Decimal("0"),
            cost_basis=Decimal(loss),
            is_long_term=False,
        )
    )
    return _run(TaxReturnInput(tax_year=2024, filing_status=fs, taxpayers=[tp]))


def test_capital_loss_at_exactly_the_limit() -> None:
    e, _ = _with_loss("3000")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000")


def test_capital_loss_beyond_the_limit_is_clamped() -> None:
    e, _ = _with_loss("10000")
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-3000")


def test_capital_loss_mfs_limit_is_1500() -> None:
    e, _ = _with_loss("3000", FilingStatus.MFS)
    assert e.resolved["fed.2024.gross_income.capital_gains_limited"] == Decimal("-1500")


# ─── Degenerate inputs ────────────────────────────────────────


def test_zero_income_run_is_all_zeros_and_consistent() -> None:
    e, run = _simple("0")
    assert run.output.agi == Decimal("0")
    assert run.output.federal_tax == Decimal("0")
    assert run.output.refund_or_owed == Decimal("0")
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_cents_precision_survives_the_whole_chain() -> None:
    """Wages with cents: AGI keeps cents, taxable/tax are whole dollars,
    and the form packet stays internally consistent."""
    e, run = _simple("50000.55")
    assert e.resolved["fed.2024.agi.total"] == Decimal("50000.55")
    assert e.resolved["fed.2024.taxable_income"] == Decimal("35401")
    assert e.resolved["fed.2024.tax.brackets"] == e.resolved[
        "fed.2024.tax.brackets"
    ].quantize(Decimal("1"))
    pkt = map_return_run(run)
    assert pkt.consistency_errors == []


def test_qss_uses_mfj_deduction_and_brackets() -> None:
    e_qss, _ = _simple("100000", FilingStatus.QSS)
    e_mfj, _ = _simple("100000", FilingStatus.MFJ)
    assert (
        e_qss.resolved["fed.2024.taxable_income"]
        == e_mfj.resolved["fed.2024.taxable_income"]
    )
    assert e_qss.resolved["fed.2024.tax.brackets"] == e_mfj.resolved["fed.2024.tax.brackets"]


# ─── Cross-year spot checks ───────────────────────────────────


def test_2023_first_bracket_edge() -> None:
    """2023 single 10% bracket tops at $11,000."""
    e, _ = _simple(str(Decimal("11000") + Decimal("13850")), year=2023)
    assert e.resolved["fed.2023.taxable_income"] == Decimal("11000")
    assert e.resolved["fed.2023.tax.brackets"] == Decimal("1100")


def test_2025_obbba_standard_deduction_edge() -> None:
    """2025 single: OBBBA $15,750 standard deduction zeroes wages at it."""
    e, _ = _simple("15750", year=2025)
    assert e.resolved["fed.2025.taxable_income"] == Decimal("0")
    e, _ = _simple("15751", year=2025)
    assert e.resolved["fed.2025.taxable_income"] == Decimal("1")
