"""Tests for mcp_hwnative_sys.programs (match_program_hints)."""

from __future__ import annotations

from mcp_hwnative_sys import programs


def _config(entries):
    return {"programs": entries}


class TestMatchProgramHints:
    def test_no_programs_returns_empty(self, monkeypatch):
        monkeypatch.setattr(programs, "load_programs_config", lambda: _config([]))
        assert programs.match_program_hints("pypto", "feat/foo") == []

    def test_repo_mismatch_is_excluded(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config([{"repo": "simpler", "branch_pattern": "feat/*", "id": "p1"}]),
        )
        assert programs.match_program_hints("pypto", "feat/foo") == []

    def test_branch_pattern_match(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config(
                [{"repo": "pypto", "branch_pattern": "feat/collectives-*", "id": "p1", "plan": "93"}]
            ),
        )
        hints = programs.match_program_hints("pypto", "feat/collectives-chunking")
        assert len(hints) == 1
        assert hints[0]["program"] == "p1"
        assert hints[0]["plan"] == "93"

    def test_branch_pattern_no_match(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config([{"repo": "pypto", "branch_pattern": "feat/collectives-*", "id": "p1"}]),
        )
        assert programs.match_program_hints("pypto", "fix/unrelated") == []

    def test_missing_branch_pattern_is_skipped(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config([{"repo": "pypto", "id": "p1"}]),
        )
        assert programs.match_program_hints("pypto", "anything") == []

    def test_multiple_matching_programs(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config(
                [
                    {"repo": "pypto", "branch_pattern": "feat/*", "id": "p1"},
                    {"repo": "pypto", "branch_pattern": "feat/collectives-*", "id": "p2"},
                ]
            ),
        )
        hints = programs.match_program_hints("pypto", "feat/collectives-chunking")
        assert {h["program"] for h in hints} == {"p1", "p2"}

    def test_default_fields_are_none_or_empty(self, monkeypatch):
        monkeypatch.setattr(
            programs,
            "load_programs_config",
            lambda: _config([{"repo": "pypto", "branch_pattern": "*", "id": "p1"}]),
        )
        hints = programs.match_program_hints("pypto", "main")
        assert hints[0]["blockers"] == []
        assert hints[0]["plan"] is None


class TestLoadProgramsConfig:
    def test_missing_config_file_returns_empty_programs(self, monkeypatch, tmp_path):
        monkeypatch.setattr(programs, "programs_config_path", lambda: tmp_path / "nonexistent.json")
        assert programs.load_programs_config() == {"programs": []}
