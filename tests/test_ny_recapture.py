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

"""New York tax table benefit recapture golden tests (0.9.0 leg 2).

Hand-verified against NY Tax Law §601(d-1) / the IT-201 Tax Computation
worksheets: for NYAGI over $107,650 the graduated-bracket benefit is
recaptured, phased in over $50,000 of AGI per range, so tax approaches
a flat rate on ALL taxable income. Every constant is derived from the
2024 rate schedule itself (e.g. the single filers' phase-1 benefit
6% × 80,650 − schedule tax = $568.25 reproduces the published $568);
the 9.65%/10.3%/10.9% recapture ranges are unmodeled (documented).
"""

from decimal import Decimal
from pathlib import Path

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import (
    FilingStatus,
    ReturnRun,
    Taxpayer,
    TaxpayerRole,
    TaxReturnInput,
    W2Data,
)

FED = RulePack.load(Path("rule_packs/federal/2024"))
NY = RulePack.load(Path("rule_packs/state/NY/2024"))


def _run(
    wages: str,
    filing_status: FilingStatus = FilingStatus.SINGLE,
    *,
    yonkers: bool = False,
) -> tuple[CalculationEngine, ReturnRun]:
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=filing_status,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="Golden",
                last_name="Vector",
                w2s=[W2Data(employer_name="Acme", wages=Decimal(wages), state="NY")],
            )
        ],
        yonkers_full_year_resident=yonkers,
    )
    engine = CalculationEngine(FED, inp, state_packs={"NY": NY})
    return engine, engine.run()


def test_single_fully_phased_pays_flat_6_percent() -> None:
    """AGI $168k, taxable $160k: benefit $568.25 recaptured → 6% × 160k."""
    e, _ = _run("168000")
    assert e.resolved["ny.2024.taxable_income"] == Decimal("160000")
    assert e.resolved["ny.2024.recapture.benefit1"] == Decimal("568.25")
    assert e.resolved["ny.2024.recapture.phase1"] == Decimal("1.0000")
    assert e.resolved["ny.2024.tax"] == Decimal("9600")


def test_single_partial_phase_in() -> None:
    """AGI $121,650: phase (121,650−107,650)/50,000 = 0.28 → +$159.11."""
    e, _ = _run("121650")
    assert e.resolved["ny.2024.recapture.phase1"] == Decimal("0.2800")
    assert e.resolved["ny.2024.recapture.total"] == Decimal("159.11")
    assert e.resolved["ny.2024.tax"] == Decimal("6410")


def test_below_threshold_is_unchanged() -> None:
    """AGI ≤ $107,650: no recapture; the pre-recapture M23 vector holds."""
    e, _ = _run("58000")
    assert e.resolved["ny.2024.recapture.total"] == Decimal("0.00")
    assert e.resolved["ny.2024.tax"] == Decimal("2585")


def test_mfj_three_phases_reach_flat_685() -> None:
    """MFJ taxable $383,950, AGI $400k: increments $332.50 + $807.75 +
    $2,747.20 all fully phased → 6.85% flat = $26,301."""
    e, _ = _run("400000", FilingStatus.MFJ)
    assert e.resolved["ny.2024.recapture.benefit1"] == Decimal("332.50")
    assert e.resolved["ny.2024.recapture.benefit2"] == Decimal("1140.25")
    assert e.resolved["ny.2024.recapture.benefit3"] == Decimal("3887.45")
    assert e.resolved["ny.2024.recapture.total"] == Decimal("3887.45")
    assert e.resolved["ny.2024.tax"] == Decimal("26301")


def test_mfj_middle_band_fully_phased_is_flat_6() -> None:
    """MFJ taxable $200k, AGI $216,050: phases 1–2 full → 6% flat = $12,000."""
    e, _ = _run("216050", FilingStatus.MFJ)
    assert e.resolved["ny.2024.taxable_income"] == Decimal("200000")
    assert e.resolved["ny.2024.tax"] == Decimal("12000")


def test_mfj_phase2_partial() -> None:
    """MFJ AGI $201,050: phase 2 = 0.79 → $332.50 + 0.79 × $807.75."""
    e, _ = _run("201050", FilingStatus.MFJ)
    assert e.resolved["ny.2024.recapture.phase2"] == Decimal("0.7900")
    assert e.resolved["ny.2024.recapture.total"] == Decimal("970.62")
    assert e.resolved["ny.2024.tax"] == Decimal("10930")


def test_hoh_fully_phased_is_flat_6() -> None:
    """HoH taxable $196,800, AGI $208k → 6% flat = $11,808."""
    e, _ = _run("208000", FilingStatus.HOH)
    assert e.resolved["ny.2024.tax"] == Decimal("11808")


def test_single_deep_in_685_band_is_flat() -> None:
    """Taxable $500k → 6.85% × 500,000 = $34,250 exactly."""
    e, _ = _run("508000")
    assert e.resolved["ny.2024.tax"] == Decimal("34250")


def test_mfs_uses_the_single_chain() -> None:
    """NY MFS shares the single rate schedule and its recapture chain."""
    e, _ = _run("168000", FilingStatus.MFS)
    assert e.resolved["ny.2024.tax"] == Decimal("9600")


def test_yonkers_surcharge_applies_to_recaptured_tax() -> None:
    """16.75% of the post-recapture net state tax: 9,600 × 0.1675 = $1,608."""
    e, run = _run("168000", yonkers=True)
    assert e.resolved["ny.2024.city_tax.yonkers"] == Decimal("1608")
    assert run.state_outputs[0].state_refund_or_owed == Decimal("-11208")
