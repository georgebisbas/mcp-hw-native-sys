"""Tests for keyword search over the abstraction index
(mcp_hwnative_sys.knowledge.search_abstractions_impl)."""

from __future__ import annotations

from mcp_hwnative_sys import knowledge


def _card(**kwargs):
    base = {
        "layer": "pypto/ir",
        "kind": "op",
        "one_liner": "",
        "tags": [],
        "arch_families": [],
        "repos": [],
        "related": [],
        "downstream": [],
    }
    base.update(kwargs)
    return base


def test_multi_word_query_matches_snake_case_names(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "load_abstractions",
        lambda: {
            "host_collectives_program": _card(one_liner="Host builtin collectives program"),
            "ring_allreduce": _card(one_liner="Ring allreduce composite"),
            "unrelated": _card(one_liner="Something else entirely"),
        },
    )

    result = knowledge.search_abstractions_impl("host collectives", max_results=20)
    names = [m["name"] for m in result["matches"]]

    assert "host_collectives_program" in names
    assert "unrelated" not in names


def test_single_token_query_still_matches(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "load_abstractions",
        lambda: {
            "host_collectives_program": _card(one_liner="Host builtin collectives program"),
        },
    )

    result = knowledge.search_abstractions_impl("collectives", max_results=20)
    assert result["match_count"] >= 1


def test_no_match_returns_empty(monkeypatch):
    monkeypatch.setattr(
        knowledge,
        "load_abstractions",
        lambda: {"host_collectives_program": _card(one_liner="Host collectives")},
    )

    result = knowledge.search_abstractions_impl("zzz qqq notreal", max_results=20)
    assert result["match_count"] == 0
