"""Tests for framework-layer docs, skills, and rules."""

from __future__ import annotations

from mcp_hwnative_sys.layer_guide import layer_guide_impl


def test_simpler_guide_includes_scheduler_docs_skills_and_rules():
    guide = layer_guide_impl("simpler")
    blob = " ".join(item["path"] for item in guide["docs"]["canonical"])
    assert "docs/scheduler.md" in blob
    assert "hierarchical-level-runtime.md" in blob
    assert guide["skills"]
    rule_paths = " ".join(item["path"] for item in guide["rules"])
    assert ".claude/rules/ascend.md" in rule_paths


def test_ptoas_guide_includes_rule_files_beyond_claude():
    guide = layer_guide_impl("ptoas")
    rule_paths = [item["path"] for item in guide["rules"]]
    assert any(path.endswith("CLAUDE.md") for path in rule_paths)
    assert any("cross-layer-sync.md" in path for path in rule_paths)
    assert len(rule_paths) > 1


def test_all_covers_five_framework_layers():
    guide = layer_guide_impl("all")
    names = [item["layer"] for item in guide["layers"]]
    assert names == ["pypto", "ptoas", "pto-isa", "simpler", "pypto-lib"]
