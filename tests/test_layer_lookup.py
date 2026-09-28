"""Layer-qualified abstraction lookup."""

from __future__ import annotations

from mcp_hwnative_sys import knowledge


def _cards():
    return {
        "tmov": {"layer": "ptoas/ir", "one_liner": "PTOAS move", "kind": "ir_op", "tags": [], "repos": [], "related": [], "downstream": [], "arch_families": []},
        "TMOV": {"layer": "pto-isa/instruction", "one_liner": "ISA move", "kind": "instruction", "tags": [], "repos": [], "related": [], "downstream": [], "arch_families": []},
    }


def test_folded_name_stays_two_cards(monkeypatch):
    monkeypatch.setattr(knowledge, "load_abstractions", _cards)
    result = knowledge.explain_abstraction_impl("Tmov")
    assert result["ambiguous"] is True
    layers = {item["layer"] for item in result["candidates"]}
    assert layers == {"ptoas/ir", "pto-isa/instruction"}


def test_layer_argument_selects_one_card(monkeypatch):
    monkeypatch.setattr(knowledge, "load_abstractions", _cards)
    result = knowledge.explain_abstraction_impl("Tmov", layer="pto-isa")
    assert result["name"] == "TMOV"
    assert result["layer"] == "pto-isa/instruction"


def test_exact_key_wins_over_the_other_layer(monkeypatch):
    monkeypatch.setattr(knowledge, "load_abstractions", _cards)
    result = knowledge.explain_abstraction_impl("tmov")
    assert result["name"] == "tmov"
    assert result["layer"] == "ptoas/ir"


def test_search_groups_by_layer(monkeypatch):
    monkeypatch.setattr(knowledge, "load_abstractions", _cards)
    result = knowledge.search_abstractions_impl("mov", layer="")
    assert set(result["by_layer"]) == {"ptoas/ir", "pto-isa/instruction"}
    filtered = knowledge.search_abstractions_impl("mov", layer="ptoas")
    assert filtered["match_count"] == 1
    assert filtered["matches"][0]["name"] == "tmov"
