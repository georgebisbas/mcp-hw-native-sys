"""Tests for the agent-skill inventory (mcp_hwnative_sys.skills)."""

from __future__ import annotations

from pathlib import Path

import pytest

import mcp_hwnative_sys.skills as skills_mod

_SKILL_MD = """---
name: compare-codegen
description: >-
  Compare codegen output (.pto files and pass dumps) between branches.
  Use when diffing generated code.
---

# Compare Codegen
"""

_PLAIN_MD = """# Plain Skill

Just a heading and a body paragraph without frontmatter.
"""


@pytest.fixture()
def fake_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    proj = tmp_path / "proj"
    ws = tmp_path
    (proj / "config").mkdir(parents=True)
    (proj / "config" / "skills.json").write_text(
        '{"version":"1.0.0","repos":{"pypto":{"dir":"pypto/.agents/skills"},'
        '"pypto-tooling":{"files":["pypto-tooling/debugging_skills/SKILL.md"]}}}',
        encoding="utf-8",
    )
    (ws / "pypto" / ".agents" / "skills" / "compare-codegen").mkdir(parents=True)
    (ws / "pypto" / ".agents" / "skills" / "compare-codegen" / "SKILL.md").write_text(
        _SKILL_MD, encoding="utf-8"
    )
    (ws / "pypto" / ".agents" / "skills" / "add-op").mkdir(parents=True)
    (ws / "pypto" / ".agents" / "skills" / "add-op" / "SKILL.md").write_text(
        _PLAIN_MD, encoding="utf-8"
    )
    (ws / "pypto-tooling" / "debugging_skills").mkdir(parents=True)
    (ws / "pypto-tooling" / "debugging_skills" / "SKILL.md").write_text(
        _SKILL_MD.replace("compare-codegen", "npu-debug"), encoding="utf-8"
    )
    monkeypatch.setattr(skills_mod, "project_root", lambda: proj)
    monkeypatch.setattr(skills_mod, "workspace_root", lambda: ws)
    return ws


def test_parse_folded_description():
    front = skills_mod._parse_frontmatter(_SKILL_MD)
    assert front["name"] == "compare-codegen"
    assert "branches" in front["description"]


def test_list_skills_indexes_each_configured_repo(fake_workspace: Path):
    index = skills_mod.build_skills_index()
    assert index["total_skills"] == 3
    pypto = index["repos"]["pypto"]
    assert {s["name"] for s in pypto} == {"compare-codegen", "add-op"}
    tooling = index["repos"]["pypto-tooling"]
    assert tooling[0]["name"] == "npu-debug"


def test_list_skills_unknown_repo_raises(fake_workspace: Path):
    with pytest.raises(ValueError, match="Unknown repo"):
        skills_mod.list_skills_impl("nope")


def test_find_skill_matches_name_and_description(fake_workspace: Path):
    result = skills_mod.find_skill_impl("generated code")
    assert result["count"] >= 1
    names = {m["name"] for m in result["matches"]}
    assert "compare-codegen" in names

    scoped = skills_mod.find_skill_impl("generated code", repo="pypto")
    assert {m["name"] for m in scoped["matches"]} == {"compare-codegen"}


def test_find_skill_plain_markdown_fallback(fake_workspace: Path):
    result = skills_mod.find_skill_impl("add op", repo="pypto")
    assert result["count"] == 1
    assert result["matches"][0]["name"] == "add-op"


@pytest.mark.workspace
def test_real_workspace_smoke():
    """Against the real workspace, every configured repo resolves skills."""
    index = skills_mod.build_skills_index()
    assert index["total_skills"] > 10
    assert "pypto" in index["repos"]
    assert "simpler" in index["repos"]
