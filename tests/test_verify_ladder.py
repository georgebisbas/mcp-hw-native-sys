"""Tests for verify-ladder rule matching (mcp_hwnative_sys.verify_ladder)."""

from __future__ import annotations

import pytest

from mcp_hwnative_sys.verify_ladder import verify_ladder_impl


def test_empty_paths_raises():
    with pytest.raises(ValueError):
        verify_ladder_impl([])


def test_codegen_orchestration_greedy_prefix_wins():
    result = verify_ladder_impl(["pypto/src/codegen/orchestration/foo.cpp"])
    # Longer, more specific prefix must match before "pypto/src/codegen/".
    assert result["suggested_tasks"] == ["pypto:codegen_tests", "pypto:unit_tests_fast"]


def test_host_orch_substring_rule():
    result = verify_ladder_impl(["pypto/src/ir/foo_host_orch_bar.cpp"])
    assert "pypto-docker:host_collectives_ut_sim" in result["suggested_tasks"]


def test_tasks_deduplicated_preserving_order():
    result = verify_ladder_impl(
        [
            "pypto/src/codegen/pto/a.cpp",
            "pypto/src/codegen/b.cpp",
        ]
    )
    tasks = result["suggested_tasks"]
    assert len(tasks) == len(set(tasks))
    assert tasks[0] == "pypto:codegen_tests"


def test_unmatched_path_yields_no_tasks():
    result = verify_ladder_impl(["README.md"])
    assert result["suggested_tasks"] == []
    assert result["matched_rules"] == []


def test_cpp_change_requires_clang_tidy():
    result = verify_ladder_impl(["pypto/src/codegen/pto/foo.cc"])
    assert result["static_checks"] == ["clang-tidy"]
    assert "clang-tidy" in result["note"]


def test_header_in_include_requires_clang_tidy_even_without_task_match():
    # pypto/include/ matches no verify rule but is still a C++ change needing clang-tidy.
    result = verify_ladder_impl(["pypto/include/pypto/ir/expr.h"])
    assert result["static_checks"] == ["clang-tidy"]
    assert result["suggested_tasks"] == []


def test_python_and_markdown_do_not_require_clang_tidy():
    for path in ["pypto/python/pypto/language/distributed/op/collective_api.py", "README.md"]:
        result = verify_ladder_impl([path])
        assert result["static_checks"] == [], path


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


def test_production_change_without_tests_warns():
    result = verify_ladder_impl(["pypto/src/ir/transforms/foo.cpp"])
    presence = result["test_presence"]
    assert presence["test_files"] == []
    assert len(presence["warnings"]) == 1
    assert "pypto" in presence["warnings"][0]


def test_production_change_with_tests_does_not_warn():
    result = verify_ladder_impl(
        ["pypto/src/ir/transforms/foo.cpp", "pypto/tests/ut/ir/transforms/test_foo.py"]
    )
    assert result["test_presence"]["warnings"] == []
    assert result["test_presence"]["test_files"] == ["pypto/tests/ut/ir/transforms/test_foo.py"]


def test_docs_only_change_does_not_warn():
    result = verify_ladder_impl(["pypto/docs/en/user/foo.md", "pypto/README.md"])
    assert result["test_presence"]["warnings"] == []


def test_test_presence_is_per_repo():
    result = verify_ladder_impl(
        ["pypto/src/codegen/a.cpp", "simpler/src/b.cpp", "simpler/tests/ut/test_b.py"]
    )
    warnings = result["test_presence"]["warnings"]
    assert len(warnings) == 1 and warnings[0].startswith("pypto:")


def test_pypto_lib_model_change_does_not_warn():
    result = verify_ladder_impl(["pypto-lib/models/qwen3/kernel.py"])
    assert result["test_presence"]["warnings"] == []


def test_ptoas_lit_and_pto_isa_tests_count_as_tests():
    result = verify_ladder_impl(
        [
            "PTOAS/lib/PTO/Transforms/foo.cpp",
            "PTOAS/test/lit/pto/foo.pto",
            "pto-isa/include/pto/tadd.hpp",
            "pto-isa/tests/cpu/st/testcase/tadd/main.cpp",
        ]
    )
    presence = result["test_presence"]
    assert presence["warnings"] == []
    assert set(presence["test_files"]) == {
        "PTOAS/test/lit/pto/foo.pto",
        "pto-isa/tests/cpu/st/testcase/tadd/main.cpp",
    }


def test_ptoas_change_runs_ir_smoke_then_lit():
    result = verify_ladder_impl(["PTOAS/lib/PTO/Transforms/foo.cpp"])
    assert result["suggested_tasks"] == ["PTOAS:ir_smoke", "PTOAS:lit_tests"]
    assert all(e["found"] for e in result["ladder"])


def test_ptodsl_change_adds_ctest_before_lit():
    result = verify_ladder_impl(["PTOAS/ptodsl/foo.py"])
    assert result["suggested_tasks"] == ["PTOAS:ptodsl_ctest", "PTOAS:lit_tests"]
    assert all(e["found"] for e in result["ladder"])


def test_pto_isa_header_change_runs_coverage_check_and_cpu_st():
    result = verify_ladder_impl(["pto-isa/include/pto/cpu/tadd.hpp"])
    assert result["suggested_tasks"] == ["pto-isa:validate_op_coverage", "pto-isa:cpu_st_tests"]
    assert all(e["found"] for e in result["ladder"])


def test_pto_isa_test_change_validates_testcase_names():
    result = verify_ladder_impl(["pto-isa/tests/cpu/st/testcase/tadd/main.cpp"])
    assert result["suggested_tasks"][0] == "pto-isa:validate_testcase_names"


def test_docs_only_changes_in_ptoas_and_pto_isa_suggest_no_tasks():
    result = verify_ladder_impl(["PTOAS/docs/isa/foo.md", "pto-isa/docs/bar.md"])
    assert result["suggested_tasks"] == []
