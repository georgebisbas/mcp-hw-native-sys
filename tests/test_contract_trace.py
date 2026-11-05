"""Tests for mcp_hwnative_sys.contract_trace (trace_in_stack / trace_contract)."""

from __future__ import annotations

import pytest

from mcp_hwnative_sys import contract_trace


def _abstractions():
    return {
        "EmitBarrier": {
            "layer": "pypto/codegen",
            "repos": ["pypto"],
            "paths": ["pypto/src/codegen/orchestration/barrier.cpp"],
            "related": ["barrier"],
            "downstream": ["simpler"],
            "verify_tasks": ["pypto:unit_tests_fast"],
        },
    }


class TestTraceInStack:
    def test_empty_input_raises(self):
        with pytest.raises(ValueError, match="cannot be empty"):
            contract_trace.trace_in_stack_impl("   ")

    def test_matches_abstraction_case_insensitively(self, monkeypatch):
        monkeypatch.setattr(contract_trace, "load_abstractions", _abstractions)
        result = contract_trace.trace_in_stack_impl("emitbarrier")
        assert result["matched_as"] == "abstraction"
        assert result["name"] == "EmitBarrier"
        assert result["layer"] == "pypto/codegen"

    def test_matches_path_prefix(self, monkeypatch):
        monkeypatch.setattr(contract_trace, "load_abstractions", dict)
        result = contract_trace.trace_in_stack_impl("pypto/src/ir/transforms/fold.cpp")
        assert result["matched_as"] == "path_prefix"
        assert result["repo"] == "pypto"
        assert result["pipeline_stage"] == "passes"

    def test_path_prefix_arch_notes_included_when_present(self, monkeypatch):
        monkeypatch.setattr(contract_trace, "load_abstractions", dict)
        result = contract_trace.trace_in_stack_impl("pto-isa/include/tile.h")
        assert "arch_implications" in result

    def test_path_prefix_arch_notes_omitted_when_absent(self, monkeypatch):
        monkeypatch.setattr(contract_trace, "load_abstractions", dict)
        result = contract_trace.trace_in_stack_impl("pypto/src/codegen/orchestration/foo.cpp")
        assert "arch_implications" not in result

    def test_no_match_returns_hint(self, monkeypatch):
        monkeypatch.setattr(contract_trace, "load_abstractions", dict)
        result = contract_trace.trace_in_stack_impl("totally/unrelated/path.py")
        assert result["matched_as"] == "none"
        assert "hint" in result


class TestTraceContractKeyMatching:
    """Regression coverage for the contract-key lookup in trace_contract_impl.

    Previously: `key.lower() == token.lower() or key in token` mixed a
    case-insensitive equality check with a case-*sensitive* substring check,
    so a differently-cased substring silently failed to match, and ties broke
    on dict iteration order rather than specificity.
    """

    @staticmethod
    def _setup(monkeypatch, artifacts, abstractions=None, open_prs=None):
        monkeypatch.setattr(contract_trace, "load_abstractions", lambda: abstractions or {})
        monkeypatch.setattr(contract_trace, "_load_contract_artifacts", lambda: artifacts)
        monkeypatch.setattr(
            contract_trace,
            "program_status_impl",
            lambda: {"open_prs": open_prs or [], "highlights": []},
        )

    def test_exact_case_insensitive_match(self, monkeypatch):
        self._setup(monkeypatch, {"PTOAS": {"pto_isa": "tmov"}})
        result = contract_trace.trace_contract_impl("ptoas")
        assert result["matched_contract"] == "PTOAS"
        assert result["contract_triangle"]["pto_isa"] == "tmov"

    def test_case_insensitive_substring_match(self, monkeypatch):
        # Token has different casing than the key and the key is only a
        # substring of the token — the old code's `key in token` branch
        # required an exact-case substring and missed this.
        self._setup(monkeypatch, {"codegen_pto": {"pto_mlir": "x"}})
        result = contract_trace.trace_contract_impl("Codegen_PTO lowering details")
        assert result["matched_contract"] == "codegen_pto"

    def test_longest_match_wins_over_shorter_substring(self, monkeypatch):
        self._setup(
            monkeypatch,
            {
                "pto": {"pto_isa": "short"},
                "codegen_pto": {"pto_mlir": "long"},
            },
        )
        result = contract_trace.trace_contract_impl("codegen_pto work item")
        assert result["matched_contract"] == "codegen_pto"
        assert result["contract_triangle"]["pto_mlir"] == "long"

    def test_no_contract_match_falls_back_to_abstraction(self, monkeypatch):
        self._setup(
            monkeypatch,
            {},
            abstractions={
                "EmitBarrier": {
                    "layer": "pypto/codegen",
                    "paths": ["a.cpp"],
                    "downstream": ["simpler"],
                    "verify_tasks": ["pypto:unit_tests_fast"],
                }
            },
        )
        result = contract_trace.trace_contract_impl("EmitBarrier")
        assert "matched_contract" not in result
        assert result["cross_layer_verify"] == ["pypto:unit_tests_fast"]

    def test_pr_links_matched_by_title(self, monkeypatch):
        self._setup(
            monkeypatch,
            {"PTOAS": {}},
            open_prs=[
                {"repo": "pypto", "pr": "#1", "title": "fix(ptoas): handle edge case"},
                {"repo": "pypto", "pr": "#2", "title": "unrelated change"},
            ],
        )
        result = contract_trace.trace_contract_impl("ptoas")
        assert len(result["active_pr_links"]) == 1
        assert "#1" in result["active_pr_links"][0]
