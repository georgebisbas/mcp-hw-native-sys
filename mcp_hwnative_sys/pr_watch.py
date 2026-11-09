"""Read-only PR snapshot/delta: CI, review threads, reviews, and comments.

One call returns the current PR state plus a cursor the caller can pass back on
the next poll. The module is intentionally free of MCP/pydantic imports so it
can be tested and used from the ``hw-native-sys-pr-watch`` CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from mcp_hwnative_sys.tracker import resolve_repos

_TIMEOUT_SECONDS = 30
_MAX_PAGES = 20
_MAX_SEEN_IDS = 5000
_OVERLAP_SECONDS = 60
_STATE_VERSION = 1

_CHECK_FAIL = frozenset({"FAILURE", "ERROR", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"})
_CHECK_SKIP = frozenset({"SKIPPED", "NEUTRAL", "CANCELLED", "STALE"})

_CODEX_LOGIN = "chatgpt-codex-connector"
_CODEX_MARKER = "<!-- pypto-codex-review -->"
_CODEX_ATTENTION_MARKERS = (
    "Reported code location",
    "not published inline",
    "Existing review thread",
    "finding(s) posted as inline comments",
)

_COPILOT_LOGINS = frozenset({"copilot-pull-request-reviewer", "github-copilot", "copilot"})

_CONTEXT_NODE = """
__typename
... on CheckRun {
  name status conclusion detailsUrl startedAt completedAt
  isRequired(pullRequestNumber: $number)
  checkSuite { app { name } }
}
... on StatusContext {
  context state targetUrl description createdAt updatedAt
  isRequired(pullRequestNumber: $number)
}
"""

_THREAD_COMMENT_NODE = """
id fullDatabaseId body path line originalLine diffHunk url
author { login __typename } authorAssociation
createdAt updatedAt lastEditedAt outdated isCopilotCodeReview
replyTo { fullDatabaseId }
commit { oid }
"""

_THREAD_NODE = (
    """
id isResolved isOutdated isCollapsed diffSide path line originalLine
resolvedBy { login } viewerCanResolve
comments(first: 100) {
  nodes {"""
    + _THREAD_COMMENT_NODE
    + """}
  pageInfo { hasNextPage endCursor }
}
"""
)

_REVIEW_NODE = """
id fullDatabaseId body url state
author { login __typename } authorAssociation
createdAt submittedAt updatedAt lastEditedAt
isCopilotCodeReview commit { oid }
"""

_COMMENT_NODE = """
id fullDatabaseId body url isMinimized
author { login __typename } authorAssociation
createdAt updatedAt lastEditedAt
"""

_PR_QUERY = (
    """
query PrWatch($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      id number title url state isDraft createdAt updatedAt
      mergeable mergeStateStatus reviewDecision
      headRefName headRefOid baseRefName baseRefOid
      additions deletions changedFiles
      author { login __typename }
      statusCheckRollup {
        state
        contexts(first: 100) {
          nodes {"""
    + _CONTEXT_NODE
    + """}
          pageInfo { hasNextPage endCursor }
        }
      }
      reviewThreads(first: 100) {
        nodes {"""
    + _THREAD_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
      reviews(first: 100) {
        nodes {"""
    + _REVIEW_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
      comments(first: 100) {
        nodes {"""
    + _COMMENT_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
)

_CONTEXT_PAGE_QUERY = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      statusCheckRollup {
        contexts(first: 100, after: $cursor) {
          nodes {"""
    + _CONTEXT_NODE
    + """}
          pageInfo { hasNextPage endCursor }
        }
      }
    }
  }
}
"""
)

_THREAD_PAGE_QUERY = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviewThreads(first: 100, after: $cursor) {
        nodes {"""
    + _THREAD_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
)

_THREAD_COMMENTS_QUERY = (
    """
query($thread: ID!, $cursor: String) {
  node(id: $thread) {
    ... on PullRequestReviewThread {
      comments(first: 100, after: $cursor) {
        nodes {"""
    + _THREAD_COMMENT_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
)

_REVIEW_PAGE_QUERY = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      reviews(first: 100, after: $cursor) {
        nodes {"""
    + _REVIEW_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
)

_COMMENT_PAGE_QUERY = (
    """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      comments(first: 100, after: $cursor) {
        nodes {"""
    + _COMMENT_NODE
    + """}
        pageInfo { hasNextPage endCursor }
      }
    }
  }
}
"""
)


# ---------------------------------------------------------------------------
# gh / GraphQL transport
# ---------------------------------------------------------------------------


def _error(kind: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {"kind": kind, "message": message[:500], "retryable": retryable}


def _run_gh_graphql(
    query: str,
    variables: dict[str, Any],
    *,
    timeout: int = _TIMEOUT_SECONDS,
    attempts: int = 3,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Run one GraphQL query through ``gh api graphql``.

    Returns ``(data, error)`` where ``data`` is the ``data`` object of the
    response. Retries only transient transport failures; rate-limit and auth
    errors are returned immediately.
    """
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in variables.items():
        if isinstance(value, bool):
            args.extend(["-F", f"{key}={'true' if value else 'false'}"])
        elif isinstance(value, int):
            args.extend(["-F", f"{key}={value}"])
        else:
            args.extend(["-f", f"{key}={value}"])

    last_error: dict[str, Any] | None = None
    for attempt in range(1, attempts + 1):
        try:
            completed = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return None, _error("gh_missing", "gh is not installed")
        except subprocess.TimeoutExpired:
            last_error = _error("timeout", f"gh timed out after {timeout}s", retryable=True)
            if attempt == attempts:
                return None, last_error
            continue

        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        combined = f"{stderr}\n{stdout}".lower()

        if "rate limit" in combined or "api rate limit exceeded" in combined:
            return None, _error("rate_limit", stderr or stdout or "GitHub rate limit exceeded")
        if "authentication" in combined or "gh auth login" in combined or "http 401" in combined:
            return None, _error("auth", stderr or stdout or "gh is not authenticated")

        payload: Any = None
        if stdout:
            try:
                payload = json.loads(stdout)
            except json.JSONDecodeError:
                payload = None

        graphql_errors = payload.get("errors") if isinstance(payload, dict) else None
        if graphql_errors:
            message = "; ".join(
                str(item.get("message", item)) if isinstance(item, dict) else str(item)
                for item in graphql_errors
            )
            return None, _error("graphql_errors", message)

        if completed.returncode != 0:
            transient = any(token in combined for token in ("502", "504", "econnreset", "timeout"))
            last_error = _error(
                "http", stderr or stdout or f"gh exited {completed.returncode}", retryable=transient
            )
            if transient and attempt < attempts:
                continue
            return None, last_error

        if not isinstance(payload, dict) or "data" not in payload:
            return None, _error("bad_json", "gh returned no GraphQL data object")
        data = payload.get("data")
        if not isinstance(data, dict):
            return None, _error("bad_json", "gh returned a non-object GraphQL data field")
        return data, None

    return None, last_error or _error("unknown", "gh call failed")


def _fetch_connection_page(
    query: str,
    variables: dict[str, Any],
    *,
    timeout: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    data, error = _run_gh_graphql(query, variables, timeout=timeout)
    if error:
        return None, error
    pull = ((data or {}).get("repository") or {}).get("pullRequest") or {}
    return pull, None


def _paginate_connection(
    first_connection: dict[str, Any],
    *,
    page_query: str,
    variables: dict[str, Any],
    connection_keys: tuple[str, ...],
    cursor_var: str = "cursor",
    timeout: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """Collect a connection's nodes, following pageInfo.

    Returns ``(nodes, error, truncated)``. The first connection is already
    fetched by the main query; additional pages use ``page_query``.
    """
    label = ".".join(connection_keys)
    nodes: list[dict[str, Any]] = list(first_connection.get("nodes") or [])
    page_info = first_connection.get("pageInfo") or {}
    cursor = page_info.get("endCursor")
    seen_cursors: set[str] = set()
    pages = 0
    while page_info.get("hasNextPage"):
        if pages >= max_pages:
            return nodes, _error("truncated", f"more than {max_pages} pages of {label}"), True
        if not cursor or cursor in seen_cursors:
            return nodes, _error("cursor", f"repeated or missing cursor for {label}"), True
        seen_cursors.add(cursor)
        page_vars = dict(variables)
        page_vars[cursor_var] = cursor
        data, error = _run_gh_graphql(page_query, page_vars, timeout=timeout)
        if error:
            return nodes, error, True
        pull = ((data or {}).get("repository") or {}).get("pullRequest") or {}
        connection = pull
        for key in connection_keys:
            connection = (connection or {}).get(key) or {}
        nodes.extend(connection.get("nodes") or [])
        page_info = connection.get("pageInfo") or {}
        cursor = page_info.get("endCursor")
        pages += 1
    return nodes, None, False


def _paginate_thread_comments(
    thread: dict[str, Any],
    *,
    timeout: int,
    max_pages: int,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    connection = thread.get("comments") or {}
    nodes: list[dict[str, Any]] = list(connection.get("nodes") or [])
    page_info = connection.get("pageInfo") or {}
    cursor = page_info.get("endCursor")
    seen_cursors: set[str] = set()
    pages = 0
    thread_id = thread.get("id")
    while page_info.get("hasNextPage"):
        if pages >= max_pages:
            return nodes, _error("truncated", "more than %d pages of thread comments" % max_pages), True
        if not cursor or cursor in seen_cursors or not thread_id:
            return nodes, _error("cursor", "repeated or missing cursor for thread comments"), True
        seen_cursors.add(cursor)
        data, error = _run_gh_graphql(
            _THREAD_COMMENTS_QUERY,
            {"thread": thread_id, "cursor": cursor},
            timeout=timeout,
        )
        if error:
            return nodes, error, True
        node = (data or {}).get("node") or {}
        connection = node.get("comments") or {}
        nodes.extend(connection.get("nodes") or [])
        page_info = connection.get("pageInfo") or {}
        cursor = page_info.get("endCursor")
        pages += 1
    return nodes, None, False


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------


def _iso(value: str | None) -> str:
    return value or ""


def _clean_login(login: str | None) -> str:
    return (login or "").removesuffix("[bot]").lower().strip()


def classify_author(
    login: str | None,
    typename: str | None,
    body: str = "",
    *,
    is_copilot: bool = False,
) -> tuple[str | None, bool]:
    """Return ``(ai_reviewer, is_bot)`` for an author."""
    raw = login or ""
    normalized = _clean_login(raw)
    ai: str | None = None
    if normalized == _CODEX_LOGIN:
        ai = "codex"
    elif normalized == "github-actions" and (
        _CODEX_MARKER in (body or "") or (body or "").lstrip().startswith("## Codex Review")
    ):
        ai = "codex"
    elif normalized.startswith("coderabbitai"):
        ai = "coderabbit"
    elif is_copilot or normalized in _COPILOT_LOGINS:
        ai = "copilot"
    is_bot = (
        typename == "Bot"
        or bool(ai)
        or raw.endswith("[bot]")
        or normalized.endswith("-bot")
    )
    return ai, is_bot


def _body_hash(body: str | None) -> str:
    return hashlib.sha256((body or "").encode("utf-8")).hexdigest()[:16]


def _check_result(*, kind: str, status: str | None, conclusion: str | None, state: str | None) -> str:
    if kind == "check_run":
        if status and status.upper() != "COMPLETED":
            return "pending"
        value = (conclusion or "").upper()
        if value == "SUCCESS":
            return "pass"
        if value in _CHECK_FAIL:
            return "fail"
        if value in _CHECK_SKIP:
            return "skipped"
        return "pending" if not value else "unknown"
    value = (state or "").upper()
    if value == "SUCCESS":
        return "pass"
    if value in {"FAILURE", "ERROR"}:
        return "fail"
    if value in {"PENDING", "EXPECTED"}:
        return "pending"
    return "unknown"


def normalize_ci(rollup: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a ``statusCheckRollup`` into checks, counts and an overall state."""
    rollup = rollup or {}
    raw = ((rollup.get("contexts") or {}).get("nodes")) or []
    checks: list[dict[str, Any]] = []
    status_contexts: dict[str, dict[str, Any]] = {}
    check_run_names: set[str] = set()

    for node in raw:
        typename = node.get("__typename")
        if typename == "CheckRun":
            name = node.get("name") or ""
            result = _check_result(
                kind="check_run",
                status=node.get("status"),
                conclusion=node.get("conclusion"),
                state=None,
            )
            check = {
                "name": name,
                "kind": "check_run",
                "status": node.get("status"),
                "conclusion": node.get("conclusion"),
                "state": None,
                "result": result,
                "details_url": node.get("detailsUrl"),
                "description": None,
                "required": node.get("isRequired"),
                "workflow": ((node.get("checkSuite") or {}).get("app") or {}).get("name"),
                "started_at": node.get("startedAt"),
                "completed_at": node.get("completedAt"),
            }
            checks.append(check)
            check_run_names.add(name.casefold())
        elif typename == "StatusContext":
            context = node.get("context") or ""
            result = _check_result(
                kind="status_context",
                status=None,
                conclusion=None,
                state=node.get("state"),
            )
            status_contexts[context.casefold()] = {
                "name": context,
                "kind": "status_context",
                "status": None,
                "conclusion": None,
                "state": node.get("state"),
                "result": result,
                "details_url": node.get("targetUrl"),
                "description": node.get("description"),
                "required": node.get("isRequired"),
                "workflow": None,
                "started_at": None,
                "completed_at": node.get("updatedAt"),
            }

    warnings: list[str] = []
    duplicates: list[str] = []
    for key, context in status_contexts.items():
        if key in check_run_names:
            context["duplicate_of"] = context["name"]
            duplicates.append(context["name"])
            continue
        checks.append(context)
    if duplicates:
        warnings.append("status contexts duplicate check runs: " + ", ".join(sorted(duplicates)))

    counts = {"total": len(checks), "passing": 0, "failing": 0, "pending": 0, "skipped": 0}
    failing: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    for check in checks:
        result = check["result"]
        if result == "fail":
            counts["failing"] += 1
            failing.append({"name": check["name"], "details_url": check.get("details_url")})
        elif result == "pending":
            counts["pending"] += 1
            pending.append({"name": check["name"], "status": check.get("status") or check.get("state")})
        elif result == "pass":
            counts["passing"] += 1
        elif result == "skipped":
            counts["skipped"] += 1
    if counts["failing"]:
        overall = "fail"
    elif counts["pending"]:
        overall = "pending"
    elif counts["total"]:
        overall = "pass"
    else:
        overall = "none"

    return {
        "state": rollup.get("state"),
        "overall": overall,
        "counts": counts,
        "failing": failing,
        "pending": pending,
        "checks": checks,
        "warnings": warnings,
    }


def _author_fields(node: dict[str, Any], body: str = "", *, is_copilot: bool = False) -> dict[str, Any]:
    author = node.get("author") or {}
    ai, is_bot = classify_author(
        author.get("login"), author.get("__typename"), body, is_copilot=is_copilot
    )
    return {
        "author": author.get("login") or "",
        "author_type": author.get("__typename") or "",
        "ai": ai,
        "is_bot": is_bot,
    }


def _noise_reason(surface: str, body: str, ai: str | None) -> str | None:
    text = body or ""
    if surface in {"review", "comment"}:
        if ai == "codex":
            return "codex_summary"
        if ai == "coderabbit":
            lowered = text.lower()
            if (
                "actionable comments posted: 0" in lowered
                or "review skipped" in lowered
                or "auto-generated comment: summarize by coderabbit.ai" in lowered
                or "<!-- walkthrough_start -->" in lowered
            ):
                return "coderabbit_walkthrough"
        if ai == "copilot":
            return "copilot_summary"
        if surface == "review" and not text.strip():
            return "empty_review"
        if surface == "comment" and ai is None:
            lowered = text.lower().strip()
            if lowered in {"all checks have passed", "all checks passed"} or (
                len(text.strip()) < 40
                and any(token in lowered for token in ("checks passed", "checks failed", "workflow status"))
                and "```" not in text
            ):
                return "ci_status_echo"
    return None


def _codex_attention(body: str, ai: str | None) -> bool:
    return ai == "codex" and any(marker in (body or "") for marker in _CODEX_ATTENTION_MARKERS)


def _normalize_thread_comment(node: dict[str, Any]) -> dict[str, Any]:
    body = node.get("body") or ""
    fields = _author_fields(
        node, body, is_copilot=bool(node.get("isCopilotCodeReview"))
    )
    reply_to = (node.get("replyTo") or {}).get("fullDatabaseId")
    return {
        "id": node.get("id"),
        "database_id": node.get("fullDatabaseId"),
        "body": body,
        "path": node.get("path"),
        "line": node.get("line"),
        "original_line": node.get("originalLine"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "last_edited_at": node.get("lastEditedAt"),
        "outdated": bool(node.get("outdated")),
        "reply_to": reply_to,
        "commit_oid": ((node.get("commit") or {}).get("oid")),
        "url": node.get("url"),
        "body_hash": _body_hash(body),
        "actionable": bool(body.strip()) and (fields["ai"] is not None or not fields["is_bot"]),
        **fields,
    }


def _normalize_review(node: dict[str, Any]) -> dict[str, Any]:
    body = node.get("body") or ""
    fields = _author_fields(
        node, body, is_copilot=bool(node.get("isCopilotCodeReview"))
    )
    noise = _noise_reason("review", body, fields["ai"])
    state = (node.get("state") or "").upper()
    actionable = noise is None and bool(body.strip()) and (
        not fields["is_bot"] and state in {"CHANGES_REQUESTED", "COMMENTED"}
    )
    return {
        "surface": "review",
        "id": node.get("id"),
        "database_id": node.get("fullDatabaseId"),
        "state": state,
        "body": body,
        "url": node.get("url"),
        "submitted_at": node.get("submittedAt") or node.get("createdAt"),
        "commit_oid": ((node.get("commit") or {}).get("oid")),
        "body_hash": _body_hash(body),
        "actionable": actionable,
        "attention_required": _codex_attention(body, fields["ai"]),
        "noise_reason": noise,
        **fields,
    }


def _normalize_comment(node: dict[str, Any]) -> dict[str, Any]:
    body = node.get("body") or ""
    fields = _author_fields(node, body)
    noise = _noise_reason("comment", body, fields["ai"])
    return {
        "surface": "comment",
        "id": node.get("id"),
        "database_id": node.get("fullDatabaseId"),
        "body": body,
        "url": node.get("url"),
        "created_at": node.get("createdAt"),
        "updated_at": node.get("updatedAt"),
        "last_edited_at": node.get("lastEditedAt"),
        "is_minimized": bool(node.get("isMinimized")),
        "body_hash": _body_hash(body),
        "actionable": noise is None and bool(body.strip()) and not fields["is_bot"],
        "attention_required": _codex_attention(body, fields["ai"]),
        "noise_reason": noise,
        **fields,
    }


def _thread_actionable(comments: Iterable[dict[str, Any]]) -> bool:
    return any(comment.get("actionable") for comment in comments)


def _normalize_thread(thread: dict[str, Any]) -> dict[str, Any]:
    raw_comments = (thread.get("comments") or {}).get("nodes") or []
    comments = [_normalize_thread_comment(node) for node in raw_comments]
    first = comments[0] if comments else {}
    ai = first.get("ai")
    resolved = bool(thread.get("isResolved"))
    return {
        "surface": "thread",
        "id": thread.get("id"),
        "is_resolved": resolved,
        "is_outdated": bool(thread.get("isOutdated")),
        "is_collapsed": bool(thread.get("isCollapsed")),
        "path": thread.get("path"),
        "line": thread.get("line"),
        "original_line": thread.get("originalLine"),
        "diff_side": thread.get("diffSide"),
        "resolved_by": (thread.get("resolvedBy") or {}).get("login"),
        "viewer_can_resolve": bool(thread.get("viewerCanResolve")),
        "author": first.get("author", ""),
        "author_type": first.get("author_type", ""),
        "ai": ai,
        "is_bot": first.get("is_bot", False),
        "actionable": not resolved and _thread_actionable(comments),
        "noise_reason": None,
        "body_hash": first.get("body_hash"),
        "comments": comments,
    }


# ---------------------------------------------------------------------------
# Delta / cursor
# ---------------------------------------------------------------------------


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _parse_since(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    parsed = _parse_ts(text)
    if parsed is None:
        raise ValueError(f"since must be an ISO-8601 timestamp, got {value!r}")
    return parsed


def _iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _newest_ts(values: Iterable[str | None]) -> datetime | None:
    parsed = [_parse_ts(value) for value in values]
    parsed = [item for item in parsed if item is not None]
    return max(parsed) if parsed else None


def _mark_item(
    item: dict[str, Any],
    *,
    ts: datetime | None,
    seen: set[str],
    since_dt: datetime | None,
) -> tuple[bool, bool]:
    item_id = item.get("id")
    if not item_id:
        return True, False
    in_since = since_dt is None or (ts is not None and ts >= since_dt)
    if item_id not in seen:
        return in_since, False
    return False, in_since


def _apply_delta(
    threads: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
    *,
    seen_ids: set[str],
    since_dt: datetime | None,
    include_resolved: bool,
) -> dict[str, Any]:
    new_item_ids: list[str] = []
    new_thread_ids: list[str] = []
    new_review_ids: list[str] = []
    new_comment_ids: list[str] = []
    new_reply_count = 0
    actionable_count = 0

    visible_threads: list[dict[str, Any]] = []
    for thread in threads:
        for comment in thread.get("comments") or []:
            comment_ts = _newest_ts(
                [comment.get("updated_at"), comment.get("created_at"), comment.get("last_edited_at")]
            )
            is_new, is_updated = _mark_item(
                comment, ts=comment_ts, seen=seen_ids, since_dt=since_dt
            )
            comment["is_new"] = is_new
            comment["is_updated"] = is_updated
            if is_new:
                new_item_ids.append(comment["id"])
                if comment.get("reply_to") is not None:
                    new_reply_count += 1
        thread_ts = _newest_ts(
            [
                comment.get("updated_at") or comment.get("created_at") or comment.get("last_edited_at")
                for comment in thread.get("comments") or []
            ]
        )
        thread_is_new, thread_is_updated = _mark_item(
            thread, ts=thread_ts, seen=seen_ids, since_dt=since_dt
        )
        has_new_comments = any(
            comment.get("is_new") for comment in thread.get("comments") or []
        )
        thread["is_new"] = thread_is_new
        thread["is_updated"] = thread_is_updated
        thread["has_new_comments"] = has_new_comments
        if thread_is_new:
            new_item_ids.append(thread["id"])
            if include_resolved or not thread.get("is_resolved"):
                new_thread_ids.append(thread["id"])
        if thread.get("actionable"):
            actionable_count += 1
        if include_resolved or not thread.get("is_resolved"):
            if include_resolved or thread_is_new or thread_is_updated or has_new_comments:
                visible_threads.append(thread)

    visible_reviews: list[dict[str, Any]] = []
    for review in reviews:
        ts = _newest_ts(
            [review.get("submitted_at"), review.get("updated_at"), review.get("created_at")]
        )
        review_is_new, review_is_updated = _mark_item(
            review, ts=ts, seen=seen_ids, since_dt=since_dt
        )
        review["is_new"] = review_is_new
        review["is_updated"] = review_is_updated
        if review_is_new:
            new_item_ids.append(review["id"])
            new_review_ids.append(review["id"])
        if review.get("actionable"):
            actionable_count += 1
        if review_is_new or review_is_updated:
            visible_reviews.append(review)

    visible_comments: list[dict[str, Any]] = []
    for comment in comments:
        ts = _newest_ts(
            [comment.get("updated_at"), comment.get("created_at"), comment.get("last_edited_at")]
        )
        comment_is_new, comment_is_updated = _mark_item(
            comment, ts=ts, seen=seen_ids, since_dt=since_dt
        )
        comment["is_new"] = comment_is_new
        comment["is_updated"] = comment_is_updated
        if comment_is_new:
            new_item_ids.append(comment["id"])
            new_comment_ids.append(comment["id"])
        if comment.get("actionable"):
            actionable_count += 1
        if comment_is_new or comment_is_updated:
            visible_comments.append(comment)

    return {
        "threads": visible_threads,
        "reviews": visible_reviews,
        "comments": visible_comments,
        "delta": {
            "first_snapshot": not seen_ids and since_dt is None,
            "new_item_ids": [item for item in new_item_ids if item],
            "new_thread_ids": [item for item in new_thread_ids if item],
            "new_review_ids": [item for item in new_review_ids if item],
            "new_comment_ids": [item for item in new_comment_ids if item],
            "new_reply_count": new_reply_count,
            "actionable_count": actionable_count,
        },
    }


def _collect_cursor_ids(
    threads: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    comments: list[dict[str, Any]],
) -> list[str]:
    entries: list[tuple[datetime, str]] = []

    def add(item: dict[str, Any], timestamp: str | None) -> None:
        item_id = item.get("id")
        if not item_id:
            return
        parsed = _parse_ts(timestamp)
        if parsed is None:
            return
        entries.append((parsed, item_id))

    for thread in threads:
        add(thread, (thread.get("comments") or [{}])[0].get("created_at") if thread.get("comments") else None)
        for comment in thread.get("comments") or []:
            add(comment, comment.get("created_at"))
    for review in reviews:
        add(review, review.get("submitted_at"))
    for comment in comments:
        add(comment, comment.get("created_at"))
    entries.sort(key=lambda item: item[0], reverse=True)
    ordered: list[str] = []
    seen: set[str] = set()
    for _, item_id in entries:
        if item_id in seen:
            continue
        seen.add(item_id)
        ordered.append(item_id)
    return ordered[:_MAX_SEEN_IDS]


# ---------------------------------------------------------------------------
# Snapshot
# ---------------------------------------------------------------------------


def _resolve_one_repo(repo: str) -> tuple[str, str]:
    resolved = resolve_repos(repo)
    if len(resolved) != 1:
        raise ValueError('repo must name exactly one repo (e.g. "pypto"), not a list or "all"')
    name, slug = resolved[0]
    owner, _, repo_name = slug.partition("/")
    return owner, repo_name


def _fetch_snapshot(
    owner: str,
    name: str,
    number: int,
    *,
    timeout: int,
    max_pages: int,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str]]:
    variables = {"owner": owner, "name": name, "number": number}
    data, error = _run_gh_graphql(_PR_QUERY, variables, timeout=timeout)
    if error:
        return None, error, []
    pull = ((data or {}).get("repository") or {}).get("pullRequest")
    if not isinstance(pull, dict):
        return None, _error("not_found", f"pull request {owner}/{name}#{number} was not found"), []

    warnings: list[str] = []
    complete = True

    contexts, page_error, truncated = _paginate_connection(
        (pull.get("statusCheckRollup") or {}).get("contexts") or {},
        page_query=_CONTEXT_PAGE_QUERY,
        variables=variables,
        connection_keys=("statusCheckRollup", "contexts"),
        timeout=timeout,
        max_pages=max_pages,
    )
    if page_error:
        warnings.append(page_error["message"])
        complete = False
    if truncated:
        complete = False

    threads_raw, page_error, truncated = _paginate_connection(
        pull.get("reviewThreads") or {},
        page_query=_THREAD_PAGE_QUERY,
        variables=variables,
        connection_keys=("reviewThreads",),
        timeout=timeout,
        max_pages=max_pages,
    )
    if page_error:
        warnings.append(page_error["message"])
        complete = False
    if truncated:
        complete = False
    threads_raw = list(threads_raw)
    for thread in threads_raw:
        comments, comment_error, comment_truncated = _paginate_thread_comments(
            thread, timeout=timeout, max_pages=max_pages
        )
        thread["comments"] = {"nodes": comments}
        if comment_error:
            warnings.append(comment_error["message"])
            complete = False
        if comment_truncated:
            complete = False

    reviews_raw, page_error, truncated = _paginate_connection(
        pull.get("reviews") or {},
        page_query=_REVIEW_PAGE_QUERY,
        variables=variables,
        connection_keys=("reviews",),
        timeout=timeout,
        max_pages=max_pages,
    )
    if page_error:
        warnings.append(page_error["message"])
        complete = False
    if truncated:
        complete = False

    comments_raw, page_error, truncated = _paginate_connection(
        pull.get("comments") or {},
        page_query=_COMMENT_PAGE_QUERY,
        variables=variables,
        connection_keys=("comments",),
        timeout=timeout,
        max_pages=max_pages,
    )
    if page_error:
        warnings.append(page_error["message"])
        complete = False
    if truncated:
        complete = False

    pull["statusCheckRollup"] = {"state": (pull.get("statusCheckRollup") or {}).get("state"),
                                 "contexts": {"nodes": contexts}}
    pull["reviewThreads"] = {"nodes": threads_raw}
    pull["reviews"] = {"nodes": reviews_raw}
    pull["comments"] = {"nodes": comments_raw}
    return pull, None, warnings if complete else warnings


def pr_watch_impl(
    repo: str,
    number: int,
    since: str = "",
    seen_ids: list[str] | None = None,
    include_resolved: bool = False,
    *,
    timeout: int = _TIMEOUT_SECONDS,
    max_pages: int = _MAX_PAGES,
) -> dict[str, Any]:
    """Return one PR snapshot/delta. Read-only; never posts."""
    if not isinstance(number, int) or number < 1:
        raise ValueError("number must be a positive pull-request number")
    if timeout < 1:
        raise ValueError("timeout must be positive")
    if max_pages < 1:
        raise ValueError("max_pages must be positive")
    owner, name = _resolve_one_repo(repo)
    since_dt = _parse_since(since)
    seen = set(seen_ids or [])
    fetch_start = datetime.now(timezone.utc)

    pull, error, warnings = _fetch_snapshot(
        owner, name, number, timeout=timeout, max_pages=max_pages
    )
    if error:
        return {
            "repo": f"{owner}/{name}",
            "number": number,
            "complete": False,
            "error": error,
            "warnings": warnings,
        }

    assert pull is not None
    ci = normalize_ci(pull.get("statusCheckRollup"))
    warnings.extend(ci.pop("warnings", []))

    threads = [_normalize_thread(node) for node in (pull.get("reviewThreads") or {}).get("nodes") or []]
    reviews = [_normalize_review(node) for node in (pull.get("reviews") or {}).get("nodes") or []]
    comments = [_normalize_comment(node) for node in (pull.get("comments") or {}).get("nodes") or []]

    deltaed = _apply_delta(
        threads,
        reviews,
        comments,
        seen_ids=seen,
        since_dt=since_dt,
        include_resolved=include_resolved,
    )
    complete = bool(pull is not None)
    result: dict[str, Any] = {
        "repo": f"{owner}/{name}",
        "number": number,
        "url": pull.get("url"),
        "fetched_at": _iso_utc(fetch_start),
        "complete": complete,
        "truncated": False,
        "pr": {
            "state": pull.get("state"),
            "is_draft": bool(pull.get("isDraft")),
            "title": pull.get("title"),
            "author": (pull.get("author") or {}).get("login"),
            "author_type": (pull.get("author") or {}).get("__typename"),
            "head_ref": pull.get("headRefName"),
            "head_sha": pull.get("headRefOid"),
            "base_ref": pull.get("baseRefName"),
            "base_sha": pull.get("baseRefOid"),
            "mergeable": pull.get("mergeable"),
            "merge_state_status": pull.get("mergeStateStatus"),
            "review_decision": pull.get("reviewDecision"),
            "additions": pull.get("additions"),
            "deletions": pull.get("deletions"),
            "changed_files": pull.get("changedFiles"),
            "created_at": pull.get("createdAt"),
            "updated_at": pull.get("updatedAt"),
        },
        "ci": ci,
        "threads": deltaed["threads"],
        "reviews": deltaed["reviews"],
        "comments": deltaed["comments"],
        "delta": {
            **deltaed["delta"],
            "since": _iso_utc(since_dt) if since_dt else "",
        },
        "warnings": warnings,
    }
    cursor_ids = _collect_cursor_ids(threads, reviews, comments)
    if warnings:
        result["complete"] = False
    if result["complete"]:
        result["cursor"] = {
            "next_since": _iso_utc(fetch_start - timedelta(seconds=_OVERLAP_SECONDS)),
            "seen_ids": cursor_ids,
        }
    else:
        result["truncated"] = True
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_gh_json(args: list[str]) -> tuple[Any | None, str | None]:
    try:
        completed = subprocess.run(args, capture_output=True, text=True, timeout=_TIMEOUT_SECONDS, check=False)
    except FileNotFoundError:
        return None, "gh is not installed"
    except subprocess.TimeoutExpired:
        return None, "gh timed out"
    if completed.returncode != 0:
        return None, (completed.stderr or completed.stdout or "gh failed").strip()[:500]
    try:
        return json.loads(completed.stdout or "null"), None
    except json.JSONDecodeError:
        return None, "gh returned non-JSON output"


def resolve_pr_number(repo: str, branch: str) -> int:
    owner, name = _resolve_one_repo(repo)
    payload, error = _run_gh_json(
        ["gh", "pr", "view", branch, "--repo", f"{owner}/{name}", "--json", "number,state"]
    )
    if error:
        raise ValueError(error)
    number = (payload or {}).get("number")
    if not isinstance(number, int) or number < 1:
        raise ValueError(f"no pull request found for branch {branch!r}")
    return number


def _state_path_for(repo: str, number: int) -> str:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    owner, name = _resolve_one_repo(repo)
    return os.path.join(base, "hw-native-sys", "pr-watch", f"{name}-{number}.json")


def _read_state(path: str) -> dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_state(path: str, state: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".pr-watch-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass


def _summary(result: dict[str, Any], previous: dict[str, Any] | None = None) -> str:
    if result.get("error"):
        return f"ERROR {result['error']['kind']}: {result['error']['message']}"
    pr = result.get("pr") or {}
    ci = result.get("ci") or {}
    counts = ci.get("counts") or {}
    delta = result.get("delta") or {}
    lines = [
        f"{result['repo']}#{result['number']} {pr.get('state')} {pr.get('head_sha', '')[:10]} "
        f"merge={pr.get('merge_state_status')} review={pr.get('review_decision')}",
        f"CI {ci.get('overall')}: {counts.get('passing', 0)} pass / {counts.get('failing', 0)} fail / "
        f"{counts.get('pending', 0)} pending / {counts.get('skipped', 0)} skipped",
    ]
    if ci.get("failing"):
        lines.append("failing: " + ", ".join(item["name"] for item in ci["failing"]))
    new_items = len(delta.get("new_item_ids") or [])
    if new_items:
        lines.append(
            f"new: {new_items} item(s), {delta.get('new_thread_ids', [])} thread(s), "
            f"{delta.get('new_reply_count', 0)} reply(ies), "
            f"{delta.get('actionable_count', 0)} actionable"
        )
    elif previous:
        lines.append("no changes")
    if not result.get("complete"):
        lines.append("INCOMPLETE: " + "; ".join(result.get("warnings") or []))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hw-native-sys-pr-watch",
        description="One-shot PR snapshot: CI, review threads, reviews, comments, and a delta cursor.",
    )
    parser.add_argument("--repo", required=True, help='single allowlisted repo, e.g. "pypto"')
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--pr", type=int, help="pull-request number")
    target.add_argument("--branch", help="branch name to resolve to a pull request")
    parser.add_argument("--since", default="", help="ISO-8601 cursor from a previous snapshot")
    parser.add_argument("--seen", action="append", default=[], help="an ID already reported (repeatable)")
    parser.add_argument("--state-file", help="read/write the watch cursor here")
    parser.add_argument("--update-state", action="store_true", help="atomically write the cursor when complete")
    parser.add_argument("--include-resolved", action="store_true", help="include resolved threads")
    parser.add_argument("--timeout", type=int, default=_TIMEOUT_SECONDS)
    parser.add_argument("--max-pages", type=int, default=_MAX_PAGES)
    parser.add_argument("--format", choices=["json", "summary"], default="json")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        number = args.pr if args.pr is not None else resolve_pr_number(args.repo, args.branch)
        state = _read_state(args.state_file) if args.state_file else {}
        since = args.since or state.get("since", "")
        seen_ids = list(args.seen) if args.seen else list(state.get("seen_ids") or [])
        previous = bool(state)
        result = pr_watch_impl(
            args.repo,
            number,
            since=since,
            seen_ids=seen_ids,
            include_resolved=args.include_resolved,
            timeout=args.timeout,
            max_pages=args.max_pages,
        )
    except ValueError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    if args.format == "summary":
        print(_summary(result, previous=state if previous else None))
    else:
        print(json.dumps(result, indent=2, sort_keys=True))

    if result.get("error"):
        return 3
    if not result.get("complete"):
        return 4
    if args.state_file and args.update_state:
        cursor = result.get("cursor") or {}
        next_state = {
            "version": _STATE_VERSION,
            "repo": result["repo"],
            "number": result["number"],
            "since": cursor.get("next_since", ""),
            "seen_ids": cursor.get("seen_ids", []),
            "hashes": {
                **(state.get("hashes") or {}),
                **{
                    item.get("id"): item.get("body_hash")
                    for bucket in ("threads", "reviews", "comments")
                    for item in result.get(bucket, [])
                    if item.get("id")
                },
            },
            "head_sha": (result.get("pr") or {}).get("head_sha"),
            "ci_overall": (result.get("ci") or {}).get("overall"),
            "merge_state_status": (result.get("pr") or {}).get("merge_state_status"),
            "review_decision": (result.get("pr") or {}).get("review_decision"),
            "posted_ids": list(state.get("posted_ids") or []),
            "updated_at": result.get("fetched_at"),
        }
        _write_state(args.state_file, next_state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
