"""Package version must match the version declared in pyproject.toml."""

from __future__ import annotations

import re
from pathlib import Path

import mcp_hwnative_sys as pkg


def test_package_version_matches_pyproject():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "no top-level version in pyproject.toml"
    assert pkg.__version__ == match.group(1)
