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

"""What-if scenario engine.

MVP: compare filing statuses (MFJ vs MFS) by re-running the same input snapshot.
"""

from __future__ import annotations

from copy import deepcopy

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack
from app.models.domain import FilingStatus, ScenarioComparison, ScenarioRun, TaxReturnInput


class WhatIfEngine:
    """Compare tax outcomes across different filing strategies.

    MVP: compares MFJ vs MFS for the same household inputs.
    """

    def __init__(self, federal_pack: RulePack):
        self.fed = federal_pack

    def compare_filing_status(self, base: TaxReturnInput) -> ScenarioComparison:
        a_inp = deepcopy(base)
        a_inp.filing_status = FilingStatus.MFJ
        b_inp = deepcopy(base)
        b_inp.filing_status = FilingStatus.MFS

        a_run = CalculationEngine(self.fed, a_inp).run()
        b_run = CalculationEngine(self.fed, b_inp).run()

        a_tax = a_run.output.federal_tax
        b_tax = b_run.output.federal_tax

        scenario_a = ScenarioRun(
            scenario_name="mfj",
            filing_status=FilingStatus.MFJ,
            total_tax=a_tax,
            refund_or_owed=a_run.output.refund_or_owed,
        )
        scenario_b = ScenarioRun(
            scenario_name="mfs",
            filing_status=FilingStatus.MFS,
            total_tax=b_tax,
            refund_or_owed=b_run.output.refund_or_owed,
        )

        savings = b_tax - a_tax
        recommendation = "mfj" if savings >= 0 else "mfs"

        diffs = [
            {"metric": "federal_tax", "mfj": str(a_tax), "mfs": str(b_tax)},
            {
                "metric": "refund_or_owed",
                "mfj": str(a_run.output.refund_or_owed),
                "mfs": str(b_run.output.refund_or_owed),
            },
        ]

        return ScenarioComparison(
            scenario_a=scenario_a,
            scenario_b=scenario_b,
            diffs=diffs,
            recommendation=recommendation,
            savings=abs(savings),
        )
