"""Tests for status_prs.md parsing (mcp_hwnative_sys.program_status)."""

from __future__ import annotations

import os

import pytest

import mcp_hwnative_sys.program_status as ps

from mcp_hwnative_sys.program_status import (
    _parse_pr_row,
    load_program_status,
    parse_status_prs_markdown,
    re_search_dashboard,
)

_STATUS_MD = """# Program status

<!-- SYNC:ACTIVE_START -->
### pypto
| PR | Title | Branch | Author | CI | Notes |
|----|-------|--------|--------|----|-------|
| [#1942](http://x/1942) | Ring allreduce | `feat/ring` | alice | green | ready |
| [#1900](http://x/1900) | Cross-core skew | `feat/skew` | bob | red | wip |
### simpler
| [#42](http://x/42) | Runtime fix | `fix/rt` | carol | green | ok |
<!-- SYNC:ACTIVE_END -->
"""


def test_parses_open_prs_with_repo_attribution():
    data = parse_status_prs_markdown(_STATUS_MD)
    prs = {row["pr"]: row for row in data["open_prs"]}
    assert set(prs) == {"#1942", "#1900", "#42"}
    assert prs["#1942"]["repo"] == "pypto"
    assert prs["#1942"]["branch"] == "feat/ring"
    assert prs["#42"]["repo"] == "simpler"


def test_header_and_separator_rows_skipped():
    data = parse_status_prs_markdown(_STATUS_MD)
    # Exactly the three data rows, no "PR"/"----" header noise.
    assert len(data["open_prs"]) == 3


def test_empty_document_yields_defaults():
    data = parse_status_prs_markdown("# empty\n")
    assert data["open_prs"] == []
    assert data["dashboard"] == {"open": 0, "merged_all": 0, "merged_90d": 0, "closed": 0}


def test_dashboard_scoped_to_marked_region():
    # A 4-integer table before the region must be ignored in favor of the one
    # inside the SYNC:DASHBOARD markers.
    text = (
        "| 1 | 2 | 3 | 4 |\n"
        "<!-- SYNC:DASHBOARD_START -->\n"
        "| 9 | 27 | 27 | 11 |\n"
        "<!-- SYNC:DASHBOARD_END -->\n"
    )
    assert re_search_dashboard(text) == {
        "open": 9,
        "merged_all": 27,
        "merged_90d": 27,
        "closed": 11,
    }


def test_dashboard_falls_back_to_full_text_without_markers():
    assert re_search_dashboard("| 5 | 6 | 7 | 8 |")["open"] == 5


def test_pr_row_without_digits_is_skipped():
    # First cell starts like a PR link but has no number -> skipped, not crash.
    assert _parse_pr_row(["#", "title", "branch", "author"]) is None


def test_pr_row_extracts_number_from_link():
    row = _parse_pr_row(["[#1942](http://x/1942)", "Title", "`br`", "author", "ci"])
    assert row is not None
    assert row["pr"] == "#1942"


def test_stale_cache_is_reparsed_from_markdown(tmp_path, monkeypatch):
    # status_prs.md is authoritative; a cache older than the markdown must not win.
    notes = tmp_path / "pypto-3.0-notes" / "pr_plans"
    notes.mkdir(parents=True)
    status_md = notes / "status_prs.md"
    status_md.write_text(_STATUS_MD, encoding="utf-8")
    cache = tmp_path / "config" / "program_status.json"
    cache.parent.mkdir()
    cache.write_text('{"open_prs": [], "dashboard": {"open": 16}}', encoding="utf-8")

    monkeypatch.setattr(ps, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ps, "program_status_path", lambda: cache)

    older = status_md.stat().st_mtime - 86_400
    os.utime(cache, (older, older))

    data = load_program_status()
    assert len(data["open_prs"]) == 3


def test_fresh_cache_is_used_without_reparsing(tmp_path, monkeypatch):
    notes = tmp_path / "pypto-3.0-notes" / "pr_plans"
    notes.mkdir(parents=True)
    (notes / "status_prs.md").write_text(_STATUS_MD, encoding="utf-8")
    cache = tmp_path / "config" / "program_status.json"
    cache.parent.mkdir()
    cache.write_text('{"open_prs": [], "dashboard": {"open": 99}}', encoding="utf-8")

    monkeypatch.setattr(ps, "workspace_root", lambda: tmp_path)
    monkeypatch.setattr(ps, "program_status_path", lambda: cache)

    assert load_program_status()["dashboard"]["open"] == 99


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
