from pathlib import Path

FILES_TO_CHECK = [
    Path("main.py"),
    Path("app/engine/calculator.py"),
    Path("app/engine/rule_loader.py"),
    Path("app/services/audit_export.py"),
    Path("app/templates/layouts/base.html"),
    Path("test_golden.py"),
    Path("test_golden2.py"),
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
