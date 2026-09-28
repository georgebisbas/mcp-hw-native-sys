"""GitHub issue/PR search allowlist and state split."""

from __future__ import annotations

import json

import pytest

from mcp_hwnative_sys import tracker


def test_default_repos_are_ptoas_and_pto_isa():
    repos = tracker.resolve_repos("")
    assert [slug for _, slug in repos] == ["hw-native-sys/PTOAS", "hw-native-sys/pto-isa"]


def test_ptoas_alias_and_all_stay_on_the_allowlist():
    assert tracker.resolve_repos("ptoas") == [("PTOAS", "hw-native-sys/PTOAS")]
    slugs = [slug for _, slug in tracker.resolve_repos("all")]
    assert "hw-native-sys/pytorch-hccl-tests" not in slugs
    assert "hw-native-sys/pypto" in slugs
    assert "hw-native-sys/PTOAS" in slugs


def test_unknown_repo_is_rejected():
    with pytest.raises(ValueError, match="Unknown repo"):
        tracker.resolve_repos("pytorch-hccl-tests")


def test_open_issues_and_merged_prs_are_separate_invocations(monkeypatch):
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))

        class Result:
            returncode = 0
            stdout = json.dumps([{"number": 1, "title": "t", "state": "open", "url": "u", "updatedAt": "d", "body": "hello"}])
            stderr = ""

        return Result()

    monkeypatch.setattr(tracker.subprocess, "run", fake_run)
    opened = tracker.search_tracker_impl("TMOV", kind="issues", state="open", max_results=5)
    merged = tracker.search_tracker_impl("TMOV", kind="prs", state="merged", max_results=5)
    assert opened["hits"][0]["kind"] == "issue"
    assert merged["hits"][0]["state"] == "merged"
    assert all(isinstance(call, list) for call in calls)
    assert any("--state" in call and "open" in call for call in calls)
    assert any("--merged" in call for call in calls)
    assert not any("pytorch-hccl-tests" in part for call in calls for part in call)


def test_gh_failure_is_a_structured_error(monkeypatch):
    def fake_run(args, **kwargs):
        class Result:
            returncode = 1
            stdout = ""
            stderr = "authentication required"

        return Result()

    monkeypatch.setattr(tracker.subprocess, "run", fake_run)
    result = tracker.search_tracker_impl("TMOV", kind="issues", state="open")
    assert "error" in result
    assert result["hits"] == []
