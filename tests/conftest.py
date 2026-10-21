"""Skip ``@pytest.mark.workspace`` tests when the sibling repos they read are absent.

``@pytest.mark.workspace("simpler", "PTOAS")`` names the repos a test needs;
a bare ``@pytest.mark.workspace`` never skips. A partial checkout then reports a skip with the missing repos instead of a
failure; on the full workspace (pre-commit hook, ``tools/check_fresh.sh``)
nothing is skipped.
"""

from __future__ import annotations

import pytest

from mcp_hwnative_sys.paths import load_repos_config, workspace_root


def _missing_repos(required: tuple[str, ...]) -> list[str]:
    config = load_repos_config()
    registered = config.get("repositories", {})
    root = workspace_root(config)
    return [n for n in required if not (root / str(registered.get(n, n))).is_dir()]


def pytest_runtest_setup(item: pytest.Item) -> None:
    marker = item.get_closest_marker("workspace")
    if marker is None or not marker.args:
        return
    missing = _missing_repos(tuple(marker.args))
    if missing:
        pytest.skip(f"workspace repo(s) not checked out: {', '.join(missing)}")
