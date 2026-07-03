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

"""Regression tests for the 0.9.0 deep-review fixes.

Each test pins a defect found in the codebase-wide review: checksum
boundary collisions, literal-shadowing input names, empty min()/max(),
silently-zero headline outputs, integrity-chain corruption via imports
with historical timestamps, the encrypted-restore downgrade, CSV
iterator crashes, YAML import crashes, and the bracket-editor row-gap
data loss.
"""

import json
from contextlib import closing
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import FormData

from app.engine.calculator import CalculationEngine
from app.engine.rule_loader import RulePack, RulePackError, _sha256_files
from app.models.domain import FilingStatus, Taxpayer, TaxpayerRole, TaxReturnInput, W2Data
from app.route_helpers.form_parsing import parse_rule_form
from app.services.csv_import import import_csv
from app.services.database import (
    delete_return_run,
    get_connection,
    init_db,
    save_return_run,
    verify_chain,
)
from app.services.rule_pack_editor import import_yaml
from main import app

CSRF = "test-csrf-token"


def _client() -> TestClient:
    c = TestClient(app, base_url="http://localhost")
    c.cookies.set("csrf", CSRF)
    return c


# ─── Pack checksum: file boundaries must be bound ─────────────


def test_checksum_binds_file_boundaries(tmp_path: Path) -> None:
    """Shifting bytes across file boundaries must change the checksum."""
    a1 = tmp_path / "pack_a"
    a2 = tmp_path / "pack_b"
    a1.mkdir()
    a2.mkdir()
    (a1 / "a.yaml").write_bytes(b"AAA")
    (a1 / "b.yaml").write_bytes(b"BBB")
    (a2 / "a.yaml").write_bytes(b"AAAB")
    (a2 / "b.yaml").write_bytes(b"BB")
    sum1 = _sha256_files([a1 / "a.yaml", a1 / "b.yaml"])
    sum2 = _sha256_files([a2 / "a.yaml", a2 / "b.yaml"])
    assert sum1 != sum2


# ─── Rule pack validation hardening ───────────────────────────


def _write_pack(tmp_path: Path, rules: list[dict]) -> Path:
    (tmp_path / "manifest.yaml").write_text(
        json.dumps(
            {"jurisdiction": "federal", "tax_year": 2024, "version": "1.0.0"}
        )
    )
    (tmp_path / "rules.yaml").write_text(json.dumps({"rules": rules}))
    return tmp_path


def test_numeric_input_name_is_rejected(tmp_path: Path) -> None:
    """An input named "2000" would silently shadow the literal 2000."""
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.x",
                "type": "formula",
                "description": "",
                "expression": "children * 2000",
                "inputs": {
                    "children": {"literal": "3"},
                    "2000": {"literal": "1"},
                },
            }
        ],
    )
    with pytest.raises(RulePackError, match="invalid input names"):
        RulePack.load(pack_dir)


def test_empty_max_call_is_rejected_at_load(tmp_path: Path) -> None:
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.x",
                "type": "formula",
                "description": "",
                "expression": "max() + a",
                "inputs": {"a": {"literal": "1"}},
            }
        ],
    )
    with pytest.raises(RulePackError, match="no arguments"):
        RulePack.load(pack_dir)


def test_missing_headline_outputs_fail_loudly(tmp_path: Path) -> None:
    """A pack that never computes refund_or_owed must not seal a $0 run."""
    pack_dir = _write_pack(
        tmp_path,
        [
            {
                "id": "fed.2024.only_rule",
                "type": "sum",
                "description": "",
                "inputs": {"items": [{"literal": "5"}]},
            }
        ],
    )
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="E", wages=Decimal("1000"))],
            )
        ],
    )
    engine = CalculationEngine(RulePack.load(pack_dir), inp)
    with pytest.raises(RulePackError, match="required output rules"):
        engine.run()
    # evaluate() (rule mechanics only) still works on partial packs.
    engine2 = CalculationEngine(RulePack.load(pack_dir), inp)
    engine2.evaluate()
    assert engine2.resolved["fed.2024.only_rule"] == Decimal("5.00")


# ─── Integrity chain: insertion order, not created_at ─────────


@pytest.fixture()
def _clean_db():  # type: ignore[no-untyped-def]
    init_db()
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")
    yield
    with closing(get_connection()) as conn:
        conn.execute("DELETE FROM return_runs")


def _run_data(run_id: str, created_at: str) -> dict:
    return {
        "id": run_id,
        "tax_year": 2024,
        "filing_status": "single",
        "scenario_name": "baseline",
        "rule_pack_version": "1.0.0",
        "rule_pack_checksum": "abc",
        "created_at": created_at,
        "input_snapshot": {"tax_year": 2024},
        "output": {"agi": "1000"},
        "trace": [],
        "state_outputs": [],
    }


def test_import_with_historical_timestamp_keeps_chain_intact(_clean_db: None) -> None:
    """A restored run whose created_at predates existing rows (the
    /import-returns flow preserves original timestamps) must not corrupt
    the chain, and deleting around it must relink cleanly."""
    save_return_run(_run_data("run-a", "2026-01-02T00:00:00"))
    save_return_run(_run_data("run-b", "2026-01-03T00:00:00"))
    # Imported run with an OLDER timestamp than both existing rows.
    save_return_run(_run_data("run-c", "2026-01-01T00:00:00"))
    assert verify_chain() == []

    delete_return_run("run-c")
    assert verify_chain() == []

    delete_return_run("run-a")
    assert verify_chain() == []


# ─── Restore must not downgrade encryption ────────────────────


def test_restore_rejects_plaintext_over_encrypted(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routes.import_export as ie
    from app.services.encryption import DatabaseState

    init_db()
    monkeypatch.setattr(ie.encryption_config, "enabled", True)
    monkeypatch.setattr(
        ie, "detect_encryption_state", lambda _: DatabaseState.ENCRYPTED_SQLCIPHER
    )
    # database_locked() consults the real (plaintext, unlocked) test DB, so
    # the request reaches the downgrade check.
    plaintext_sqlite = b"SQLite format 3\x00" + b"\x00" * 100
    resp = _client().post(
        "/restore",
        data={"csrf_token": CSRF},
        files={"file": ("backup.db", plaintext_sqlite, "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "Refusing to overwrite" in resp.text


# ─── CSV import: iterator errors are structured, not 500s ─────


def test_csv_oversized_field_returns_structured_error() -> None:
    huge = "x" * 200_000
    csv_text = f'employer_name,wages,federal_withheld\n"{huge}",100,10\n'
    records, errors = import_csv(csv_text, "W2")
    assert records == []
    assert any("CSV structure error" in e for e in errors)


def test_csv_import_route_survives_oversized_field() -> None:
    huge = "x" * 200_000
    resp = _client().post(
        "/import-csv",
        data={
            "csrf_token": CSRF,
            "record_type": "W2",
            "csv_text": f'employer_name,wages,federal_withheld\n"{huge}",100,10\n',
        },
    )
    assert resp.status_code == 200
    assert "CSV structure error" in resp.text


# ─── Rule pack import/editor hardening ────────────────────────


def test_malformed_manifest_yaml_raises_value_error() -> None:
    with pytest.raises(ValueError, match="not valid YAML"):
        import_yaml(b"a: [", b"rules: []", "broken")


def test_rule_pack_create_rejects_non_numeric_year() -> None:
    resp = _client().post(
        "/rule-packs/create",
        data={"csrf_token": CSRF, "jurisdiction": "federal", "year": "abc"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "Year must be a whole number" in resp.text


def test_bracket_editor_keeps_rows_after_a_gap() -> None:
    """Deleting a middle editor row leaves an index gap; the rows after
    the gap must survive parsing instead of being silently dropped."""
    fd = FormData(
        [
            ("rule_id", "fed.2024.tax.brackets"),
            ("rule_type", "bracket_table"),
            ("description", "test"),
            ("form_line", ""),
            ("bracket_input_ref", "fed.2024.taxable_income"),
            ("bracket_key_ref", "input.filing_status"),
            ("bracket_single_0_lower", "0"),
            ("bracket_single_0_upper", "10000"),
            ("bracket_single_0_rate", "0.10"),
            # Row 1 was removed in the editor: indices jump 0 -> 2.
            ("bracket_single_2_lower", "10000"),
            ("bracket_single_2_upper", ""),
            ("bracket_single_2_rate", "0.20"),
        ]
    )
    rule = parse_rule_form(fd)
    brackets = rule["tables"]["single"]
    assert len(brackets) == 2
    assert brackets[1] == {"lower": "10000", "upper": None, "rate": "0.20"}


# ─── Charitable combined AGI cap ──────────────────────────────


def test_charitable_combined_cap_binds() -> None:
    """AGI $100k with $60k cash + $30k noncash gifts: the per-category
    caps allow 90k, but the combined 60%-of-AGI cap holds it to 60k."""
    from app.models.domain import ItemizedDeductionData

    fed = RulePack.load(Path("rule_packs/federal/2024"))
    inp = TaxReturnInput(
        tax_year=2024,
        filing_status=FilingStatus.SINGLE,
        taxpayers=[
            Taxpayer(
                role=TaxpayerRole.PRIMARY,
                first_name="A",
                last_name="B",
                w2s=[W2Data(employer_name="E", wages=Decimal("100000"))],
            )
        ],
        itemized_deductions=ItemizedDeductionData(
            charitable_cash=Decimal("60000"),
            charitable_noncash=Decimal("30000"),
        ),
    )
    engine = CalculationEngine(fed, inp)
    engine.run()
    assert engine.resolved["fed.2024.itemized.charitable"] == Decimal("60000.00")
