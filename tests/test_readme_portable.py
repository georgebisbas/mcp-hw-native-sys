"""The published README must stay portable for any reader."""

from __future__ import annotations

import re
from pathlib import Path

_README = Path(__file__).resolve().parents[1] / "README.md"
# Absolute home directories, not a list of people.
_HOME_PATH = re.compile(r"(?:/home/|/Users/|[A-Za-z]:\\Users\\)")


def test_readme_has_no_absolute_home_paths():
    text = _README.read_text(encoding="utf-8")
    assert _HOME_PATH.search(text) is None
