"""The published README must not contain a personal home path or username."""

from __future__ import annotations

from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"
_BANNED = ("/home/", "georgios", "gb4018", "gbismpas", "georgebisbas")


def test_readme_has_no_personal_paths_or_usernames():
    text = _README.read_text(encoding="utf-8").lower()
    for banned in _BANNED:
        assert banned not in text, banned
