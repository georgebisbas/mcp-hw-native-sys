"""PR watch: CI normalization, review surfaces, AI classification, deltas, CLI."""

from __future__ import annotations

import json

import pytest

from mcp_hwnative_sys import pr_watch


def _check_run(name, conclusion="SUCCESS", status="COMPLETED", required=False):
    return {
        "__typename": "CheckRun",
        "name": name,
        "status": status,
        "conclusion": conclusion,
        "detailsUrl": f"https://example/{name}",
        "startedAt": "2026-11-09T10:00:00Z",
        "completedAt": "2026-11-09T10:01:00Z",
        "isRequired": required,
        "checkSuite": {"app": {"name": "CI"}},
    }


def _status_context(name, state, required=False):
    return {
        "__typename": "StatusContext",
        "context": name,
        "state": state,
        "targetUrl": f"https://example/{name}",
        "description": "status",
        "createdAt": "2026-11-09T10:00:00Z",
        "updatedAt": "2026-11-09T10:01:00Z",
        "isRequired": required,
    }


def _author(login="alice", typename="User"):
    return {"login": login, "__typename": typename}


def _thread_comment(
    comment_id="PRRC_1",
    *,
    login="alice",
    typename="User",
    body="please fix",
    created="2026-11-09T10:00:00Z",
    updated=None,
    reply_to=None,
    copilot=False,
):
    return {
        "id": comment_id,
        "fullDatabaseId": 1,
        "body": body,
        "path": "src/a.cpp",
        "line": 12,
        "originalLine": 10,
        "diffHunk": "@@",
        "url": "https://example/comment",
        "author": _author(login, typename),
        "authorAssociation": "MEMBER",
        "createdAt": created,
        "updatedAt": updated or created,
        "lastEditedAt": None,
        "outdated": False,
        "isCopilotCodeReview": copilot,
        "replyTo": {"fullDatabaseId": 1} if reply_to else None,
        "commit": {"oid": "abc123"},
    }


def _thread(thread_id="PRRT_1", *, resolved=False, comments=None):
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": False,
        "isCollapsed": False,
        "diffSide": "RIGHT",
        "path": "src/a.cpp",
        "line": 12,
        "originalLine": 10,
        "resolvedBy": {"login": "alice"} if resolved else None,
        "viewerCanResolve": True,
        "comments": {
            "nodes": comments or [_thread_comment()],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }


def _review(
    review_id="PRR_1",
    *,
    login="alice",
    typename="User",
    body="please fix",
    state="COMMENTED",
    submitted="2026-11-09T10:00:00Z",
    copilot=False,
):
    return {
        "id": review_id,
        "fullDatabaseId": 2,
        "body": body,
        "url": "https://example/review",
        "state": state,
        "author": _author(login, typename),
        "authorAssociation": "MEMBER",
        "createdAt": submitted,
        "submittedAt": submitted,
        "updatedAt": submitted,
        "lastEditedAt": None,
        "isCopilotCodeReview": copilot,
        "commit": {"oid": "abc123"},
    }


def _issue_comment(comment_id="IC_1", *, login="alice", body="please rebase", created="2026-11-09T10:00:00Z"):
    return {
        "id": comment_id,
        "fullDatabaseId": 3,
        "body": body,
        "url": "https://example/issue-comment",
        "isMinimized": False,
        "author": _author(login),
        "authorAssociation": "MEMBER",
        "createdAt": created,
        "updatedAt": created,
        "lastEditedAt": None,
    }


def _pull(*, contexts=None, threads=None, reviews=None, comments=None, page_size_info=None):
    info = page_size_info or {"hasNextPage": False, "endCursor": None}
    return {
        "id": "PR_1",
        "number": 3248,
        "title": "Test PR",
        "url": "https://example/pr/3248",
        "state": "OPEN",
        "isDraft": False,
        "createdAt": "2026-11-09T09:00:00Z",
        "updatedAt": "2026-11-09T10:05:00Z",
        "mergeable": "MERGEABLE",
        "mergeStateStatus": "BLOCKED",
        "reviewDecision": "REVIEW_REQUIRED",
        "headRefName": "feature",
        "headRefOid": "abc123def",
        "baseRefName": "main",
        "baseRefOid": "def456abc",
        "additions": 10,
        "deletions": 2,
        "changedFiles": 3,
        "author": _author("georgebisbas"),
        "statusCheckRollup": {
            "state": "PENDING",
            "contexts": {
                "nodes": contexts or [],
                "pageInfo": {"hasNextPage": False, "endCursor": None},
            },
        },
        "reviewThreads": {"nodes": threads or [], "pageInfo": info},
        "reviews": {
            "nodes": reviews or [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
        "comments": {
            "nodes": comments or [],
            "pageInfo": {"hasNextPage": False, "endCursor": None},
        },
    }


def _snapshot(monkeypatch, pull):
    def fake_run(query, variables, **kwargs):
        return {"repository": {"pullRequest": pull}}, None

    monkeypatch.setattr(pr_watch, "_run_gh_graphql", fake_run)


def _impl(monkeypatch, pull, **kwargs):
    _snapshot(monkeypatch, pull)
    return pr_watch.pr_watch_impl("pypto", 3248, **kwargs)


# ---------------------------------------------------------------------------
# CI
# ---------------------------------------------------------------------------


def test_ci_rollup_normalizes_check_run_and_status_context():
    ci = pr_watch.normalize_ci(
        {
            "state": "FAILURE",
            "contexts": {
                "nodes": [
                    _check_run("build", "SUCCESS", required=True),
                    _check_run("pytest", "FAILURE"),
                    _check_run("lint", None, status="IN_PROGRESS"),
                    _status_context("CodeRabbit", "SUCCESS"),
                ]
            },
        }
    )
    assert ci["overall"] == "fail"
    assert ci["counts"] == {"total": 4, "passing": 2, "failing": 1, "pending": 1, "skipped": 0}
    assert ci["failing"] == [{"name": "pytest", "details_url": "https://example/pytest"}]
    assert ci["pending"] == [{"name": "lint", "status": "IN_PROGRESS"}]


def test_coderabbit_success_does_not_mask_failing_check_run():
    ci = pr_watch.normalize_ci(
        {
            "state": "SUCCESS",
            "contexts": {
                "nodes": [
                    _check_run("pytest", "FAILURE"),
                    _status_context("CodeRabbit", "SUCCESS"),
                ]
            },
        }
    )
    assert ci["overall"] == "fail"
    assert [item["name"] for item in ci["failing"]] == ["pytest"]


def test_exact_name_duplicate_prefers_check_run():
    ci = pr_watch.normalize_ci(
        {
            "state": "FAILURE",
            "contexts": {
                "nodes": [
                    _check_run("build", "SUCCESS"),
                    _status_context("build", "FAILURE"),
                ]
            },
        }
    )
    assert ci["overall"] == "pass"
    assert ci["counts"]["total"] == 1
    assert any("duplicate" in warning for warning in ci["warnings"])


# ---------------------------------------------------------------------------
# AI classification and noise
# ---------------------------------------------------------------------------


def test_ai_classification_by_login_marker_and_copilot_flag():
    assert pr_watch.classify_author("chatgpt-codex-connector", "Bot") == ("codex", True)
    assert pr_watch.classify_author("github-actions[bot]", "Bot", "<!-- pypto-codex-review -->") == (
        "codex",
        True,
    )
    assert pr_watch.classify_author("github-actions[bot]", "Bot", "plain bot comment") == (None, True)
    assert pr_watch.classify_author("coderabbitai[bot]", "Bot") == ("coderabbit", True)
    assert pr_watch.classify_author("copilot-pull-request-reviewer", "Bot") == ("copilot", True)
    assert pr_watch.classify_author("alice", "User") == (None, False)


def test_codex_summary_is_noise_not_a_finding():
    review = pr_watch._normalize_review(
        _review(login="github-actions", typename="Bot", body="## Codex Review\nFound one P2.")
    )
    assert review["ai"] == "codex"
    assert review["noise_reason"] == "codex_summary"
    assert review["actionable"] is False


def test_codex_summary_fallback_raises_attention_but_not_actionable():
    review = pr_watch._normalize_review(
        _review(
            login="github-actions",
            typename="Bot",
            body="## Codex Review\nReported code location: src/a.cpp:1",
        )
    )
    assert review["attention_required"] is True
    assert review["actionable"] is False


def test_coderabbit_walkthrough_is_noise():
    comment = pr_watch._normalize_comment(
        _issue_comment(
            login="coderabbitai[bot]",
            body="<!-- This is an auto-generated comment: summarize by coderabbit.ai -->",
        )
    )
    assert comment["ai"] == "coderabbit"
    assert comment["noise_reason"] == "coderabbit_walkthrough"
    assert comment["actionable"] is False


def test_human_one_liner_is_actionable():
    comment = pr_watch._normalize_comment(_issue_comment(login="alice", body="please rebase"))
    assert comment["actionable"] is True
    assert comment["noise_reason"] is None


# ---------------------------------------------------------------------------
# Snapshot and delta
# ---------------------------------------------------------------------------


def test_first_snapshot_marks_new_and_hides_resolved(monkeypatch):
    pull = _pull(
        threads=[
            _thread("PRRT_open", comments=[_thread_comment("PRRC_open", login="chatgpt-codex-connector", typename="Bot", body="P2 finding")]),
            _thread("PRRT_done", resolved=True),
        ],
        reviews=[_review(login="github-actions", typename="Bot", body="## Codex Review")],
        comments=[_issue_comment()],
    )
    result = _impl(monkeypatch, pull)
    assert result["complete"] is True
    assert result["cursor"]["next_since"]
    assert [thread["id"] for thread in result["threads"]] == ["PRRT_open"]
    thread = result["threads"][0]
    assert thread["ai"] == "codex"
    assert thread["actionable"] is True
    assert result["delta"]["first_snapshot"] is True
    assert result["delta"]["new_thread_ids"] == ["PRRT_open"]
    assert result["delta"]["new_reply_count"] == 0
    assert result["reviews"][0]["noise_reason"] == "codex_summary"
    assert result["comments"][0]["actionable"] is True


def test_second_snapshot_reports_no_changes(monkeypatch):
    pull = _pull(threads=[_thread()])
    first = _impl(monkeypatch, pull)
    second = _impl(
        monkeypatch,
        pull,
        since=first["cursor"]["next_since"],
        seen_ids=first["cursor"]["seen_ids"],
    )
    assert second["delta"]["first_snapshot"] is False
    assert second["delta"]["new_item_ids"] == []
    assert second["threads"] == []


def test_new_reply_in_seen_thread_is_surfaced(monkeypatch):
    pull = _pull(threads=[_thread()])
    first = _impl(monkeypatch, pull)
    pull["reviewThreads"]["nodes"][0]["comments"]["nodes"].append(
        _thread_comment(
            "PRRC_reply",
            login="chatgpt-codex-connector",
            typename="Bot",
            body="follow-up",
            created="2026-11-09T10:10:00Z",
            reply_to=1,
        )
    )
    second = _impl(
        monkeypatch,
        pull,
        since="2026-11-09T10:05:00Z",
        seen_ids=first["cursor"]["seen_ids"],
    )
    assert second["threads"][0]["has_new_comments"] is True
    assert second["delta"]["new_reply_count"] == 1
    assert second["threads"][0]["comments"][-1]["is_new"] is True


def test_edited_seen_comment_is_updated_not_new(monkeypatch):
    pull = _pull(threads=[_thread()])
    first = _impl(monkeypatch, pull)
    pull["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["body"] = "edited finding"
    pull["reviewThreads"]["nodes"][0]["comments"]["nodes"][0]["updatedAt"] = "2026-11-09T10:10:00Z"
    result = _impl(
        monkeypatch,
        pull,
        since="2026-11-09T10:05:00Z",
        seen_ids=first["cursor"]["seen_ids"],
    )
    comment = result["threads"][0]["comments"][0]
    assert comment["is_new"] is False
    assert comment["is_updated"] is True
    assert comment["body_hash"] != ""


def test_incomplete_snapshot_has_no_cursor(monkeypatch):
    pull = _pull(threads=[_thread()], page_size_info={"hasNextPage": True, "endCursor": "c1"})

    def fake_run(query, variables, **kwargs):
        return {"repository": {"pullRequest": pull}}, None

    monkeypatch.setattr(pr_watch, "_run_gh_graphql", fake_run)
    result = pr_watch.pr_watch_impl("pypto", 3248, max_pages=1)
    assert result["complete"] is False
    assert "cursor" not in result
    assert result["truncated"] is True


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_threads_paginate(monkeypatch):
    first = _pull(threads=[_thread("PRRT_1")], page_size_info={"hasNextPage": True, "endCursor": "c1"})
    second = _pull(threads=[_thread("PRRT_2")])

    def fake_run(query, variables, **kwargs):
        if "reviewThreads(first: 100, after: $cursor)" in query:
            return {"repository": {"pullRequest": second}}, None
        return {"repository": {"pullRequest": first}}, None

    monkeypatch.setattr(pr_watch, "_run_gh_graphql", fake_run)
    result = pr_watch.pr_watch_impl("pypto", 3248)
    assert [thread["id"] for thread in result["threads"]] == ["PRRT_1", "PRRT_2"]
    assert result["complete"] is True


def test_repeated_pagination_cursor_is_incomplete(monkeypatch):
    pull = _pull(threads=[_thread()], page_size_info={"hasNextPage": True, "endCursor": "c1"})

    def fake_run(query, variables, **kwargs):
        return {"repository": {"pullRequest": pull}}, None

    monkeypatch.setattr(pr_watch, "_run_gh_graphql", fake_run)
    result = pr_watch.pr_watch_impl("pypto", 3248, max_pages=2)
    assert result["complete"] is False
    assert "cursor" not in result


# ---------------------------------------------------------------------------
# Transport errors
# ---------------------------------------------------------------------------


def _fake_run(returncode=0, stdout="", stderr=""):
    class Result:
        pass

    result = Result()
    result.returncode = returncode
    result.stdout = stdout
    result.stderr = stderr
    return result


def test_gh_missing_is_structured_error(monkeypatch):
    def fake_run(args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(pr_watch.subprocess, "run", fake_run)
    data, error = pr_watch._run_gh_graphql("query{}", {"owner": "a"})
    assert data is None
    assert error["kind"] == "gh_missing"


def test_rate_limit_is_structured_error(monkeypatch):
    monkeypatch.setattr(pr_watch.subprocess, "run", lambda args, **kwargs: _fake_run(1, "", "API rate limit exceeded"))
    data, error = pr_watch._run_gh_graphql("query{}", {"owner": "a"})
    assert data is None
    assert error["kind"] == "rate_limit"


def test_bad_json_is_structured_error(monkeypatch):
    monkeypatch.setattr(pr_watch.subprocess, "run", lambda args, **kwargs: _fake_run(0, "not json"))
    data, error = pr_watch._run_gh_graphql("query{}", {"owner": "a"})
    assert data is None
    assert error["kind"] == "bad_json"


def test_graphql_errors_are_reported(monkeypatch):
    payload = json.dumps({"errors": [{"message": "Field does not exist"}]})
    monkeypatch.setattr(pr_watch.subprocess, "run", lambda args, **kwargs: _fake_run(0, payload))
    data, error = pr_watch._run_gh_graphql("query{}", {"owner": "a"})
    assert data is None
    assert error["kind"] == "graphql_errors"
    assert "Field does not exist" in error["message"]


# ---------------------------------------------------------------------------
# Repo / since validation
# ---------------------------------------------------------------------------


def test_repo_must_be_single():
    assert pr_watch._resolve_one_repo("pypto") == ("hw-native-sys", "pypto")
    with pytest.raises(ValueError, match="exactly one"):
        pr_watch._resolve_one_repo("all")


def test_bad_since_raises():
    with pytest.raises(ValueError, match="ISO-8601"):
        pr_watch._parse_since("not-a-date")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_cli_state_roundtrip(monkeypatch, tmp_path, capsys):
    pull = _pull(threads=[_thread()])
    _snapshot(monkeypatch, pull)
    state_path = tmp_path / "state.json"
    args = [
        "--repo",
        "pypto",
        "--pr",
        "3248",
        "--state-file",
        str(state_path),
        "--update-state",
        "--format",
        "summary",
    ]
    assert pr_watch.main(args) == 0
    state = json.loads(state_path.read_text())
    assert state["number"] == 3248
    assert state["seen_ids"]
    assert state["head_sha"] == "abc123def"
    capsys.readouterr()
    assert pr_watch.main(args) == 0
    second = json.loads(state_path.read_text())
    assert second["hashes"] == state["hashes"]
    assert second["posted_ids"] == []


def test_coderabbit_follow_up_review_requires_attention():
    review = pr_watch._normalize_review(
        _review(
            login="coderabbitai[bot]",
            typename="Bot",
            body="## Follow-up Comments\n824-826: Minor · Functional Correctness · Quick win",
        )
    )
    assert review["ai"] == "coderabbit"
    assert review["noise_reason"] is None
    assert review["attention_required"] is True
    assert review["actionable"] is False
