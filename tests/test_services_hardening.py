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

"""Regression tests for services-layer hardening.

Covers: CSV header validation, delete_rule validate-before-write, and
rule-id validation in save_rule.
"""

from pathlib import Path

import pytest
import yaml

from app.services.csv_import import import_csv
from app.services.rule_pack_editor import delete_rule, save_rule

# ─── CSV header validation ──────────────────────────────────────


def test_csv_import_rejects_wrong_headers() -> None:
    # 1099-INT headers uploaded as W2: previously imported $0 rows silently.
    csv_text = "payer_name,interest_income\nFirst Bank,500\n"
    records, errors = import_csv(csv_text, "W2")
    assert records == []
    assert len(errors) == 1
    assert "Missing required column(s) for W2" in errors[0]


def test_csv_import_rejects_capitalized_headers() -> None:
    csv_text = "Wages,Federal Withheld\n1000,100\n"
    records, errors = import_csv(csv_text, "W2")
    assert records == []
    assert "Missing required column(s)" in errors[0]


def test_csv_import_unsupported_type_reports_error_even_when_empty() -> None:
    records, errors = import_csv("", "XYZ")
    assert records == []
    assert errors == ["Unsupported record_type: XYZ"]


def test_csv_import_valid_w2_still_works() -> None:
    csv_text = "employer_name,wages,federal_withheld\nAcme,85000,12000\n"
    records, errors = import_csv(csv_text, "W2")
    assert errors == []
    assert len(records) == 1


# ─── Rule pack editor validation ────────────────────────────────


def _make_custom_pack(base_dir: Path) -> None:
    pack_dir = base_dir / "federal" / "2024" / "custom_v1"
    pack_dir.mkdir(parents=True)
    (pack_dir / "manifest.yaml").write_text(
        yaml.safe_dump(
            {"version": "1.0.0", "tax_year": 2024, "jurisdiction": "federal", "custom": True}
        )
    )
    (pack_dir / "rules.yaml").write_text(
        yaml.safe_dump(
            {
                "constants": {},
                "rules": [
                    {
                        "id": "fed.2024.base",
                        "type": "sum",
                        "description": "",
                        "inputs": {"items": [{"literal": "1"}]},
                    },
                    {
                        "id": "fed.2024.dependent",
                        "type": "sum",
                        "description": "",
                        "inputs": {"items": [{"ref": "fed.2024.base"}]},
                    },
                ],
            }
        )
    )


def test_delete_rule_refuses_to_break_references(tmp_path: Path) -> None:
    _make_custom_pack(tmp_path)
    with pytest.raises(ValueError, match="Validation failed"):
        delete_rule("federal", 2024, "custom_v1", "fed.2024.base", base_dir=tmp_path)

    # Pack on disk must still be loadable and contain both rules.
    rules = yaml.safe_load(
        (tmp_path / "federal" / "2024" / "custom_v1" / "rules.yaml").read_text()
    )
    assert len(rules["rules"]) == 2


def test_delete_rule_removes_unreferenced_rule(tmp_path: Path) -> None:
    _make_custom_pack(tmp_path)
    delete_rule("federal", 2024, "custom_v1", "fed.2024.dependent", base_dir=tmp_path)
    rules = yaml.safe_load(
        (tmp_path / "federal" / "2024" / "custom_v1" / "rules.yaml").read_text()
    )
    assert [r["id"] for r in rules["rules"]] == ["fed.2024.base"]


def test_save_rule_rejects_malformed_rule_id(tmp_path: Path) -> None:
    _make_custom_pack(tmp_path)
    with pytest.raises(ValueError, match="Rule id must look like"):
        save_rule(
            "federal",
            2024,
            "custom_v1",
            "fed.2024.x');alert(1);//",
            {"id": "fed.2024.x');alert(1);//", "type": "sum", "inputs": {"items": []}},
            base_dir=tmp_path,
        )
