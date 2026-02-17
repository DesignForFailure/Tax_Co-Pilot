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

"""Tests that source files are valid UTF-8 and free of mojibake encoding artifacts."""

from pathlib import Path

FILES_TO_CHECK = [
    Path("main.py"),
    Path("app/engine/calculator.py"),
    Path("app/engine/rule_loader.py"),
    Path("app/services/audit_export.py"),
    Path("app/templates/layouts/base.html"),
    Path("tests/test_golden.py"),
    Path("tests/test_golden2.py"),
]

MOJIBAKE_TOKENS = ["â", "Ã", "�"]


def test_target_files_are_valid_utf8() -> None:
    for path in FILES_TO_CHECK:
        path.read_bytes().decode("utf-8")


def test_target_files_have_no_known_mojibake_tokens() -> None:
    for path in FILES_TO_CHECK:
        text = path.read_text(encoding="utf-8")
        for token in MOJIBAKE_TOKENS:
            assert token not in text, f"Found mojibake token {token!r} in {path}"
