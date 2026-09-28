"""Simpler scheduler catalog."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from mcp_hwnative_sys.paths import workspace_root
from mcp_hwnative_sys.scheduler import explain_scheduler_impl

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from build_simpler_scheduler_index import build_scheduler_index  # noqa: E402


def test_levels_are_emitted_without_a_simpler_checkout(tmp_path: Path):
    index = build_scheduler_index(tmp_path)
    assert [level["id"] for level in index["levels"]] == ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
    assert index["implementations"] == []
    assert index["cards"]["simpler.scheduler.L0"]["kind"] == "level"


def test_explain_scheduler_uses_the_checked_in_catalog():
    card = explain_scheduler_impl("L3")
    assert card["kind"] == "level"
    assert "L3" in card["one_liner"]
    trees = explain_scheduler_impl("a5_tensormap_and_ringbuffer")
    assert trees["kind"] == "implementation"
    assert "a5" in trees["paths"][0]


@pytest.mark.workspace
def test_index_keeps_hierarchical_and_arch_trees_distinct():
    index = build_scheduler_index(workspace_root())
    paths = [item["path"] for item in index["implementations"]]
    assert any(path.endswith("src/common/hierarchical/scheduler.cpp") for path in paths)
    assert any("a2a3" in path and "host_build_graph" in path for path in paths)
    assert any("a5" in path and "tensormap_and_ringbuffer" in path for path in paths)
    assert "ISchedulerLayer" not in index["cards"]


@pytest.mark.workspace
def test_level_docs_still_name_l0_and_l6():
    root = workspace_root()
    text = (root / "simpler/docs/hierarchical-level-runtime.md").read_text(encoding="utf-8")
    assert "L0" in text
    assert "L6" in text


