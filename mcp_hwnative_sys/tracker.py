"""Read-only GitHub issue and PR search for the stack repos."""

from __future__ import annotations

import json
import subprocess
from typing import Any

_ALLOWLIST: dict[str, str] = {
    "pypto": "hw-native-sys/pypto",
    "ptoas": "hw-native-sys/PTOAS",
    "PTOAS": "hw-native-sys/PTOAS",
    "pto-isa": "hw-native-sys/pto-isa",
    "simpler": "hw-native-sys/simpler",
    "pypto-lib": "hw-native-sys/pypto-lib",
}

_DEFAULT_REPOS = ("PTOAS", "pto-isa")
_ALL_REPOS = ("pypto", "PTOAS", "pto-isa", "simpler", "pypto-lib")
_SNIPPET = 400
_TIMEOUT_SECONDS = 20


def resolve_repos(repo: str) -> list[tuple[str, str]]:
    text = (repo or "").strip()
    if not text:
        names = list(_DEFAULT_REPOS)
    elif text.lower() == "all":
        names = list(_ALL_REPOS)
    else:
        names = [part.strip() for part in text.split(",") if part.strip()]

    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in names:
        slug = _ALLOWLIST.get(name)
        if slug is None:
            known = ", ".join(["all", *sorted(set(_ALLOWLIST))])
            raise ValueError(f"Unknown repo '{name}'. Allowed: {known}")
        if slug in seen:
            continue
        seen.add(slug)
        resolved.append((slug.split("/", 1)[1], slug))
    return resolved


def _queries(kind: str, state: str) -> list[tuple[str, str]]:
    """Return (gh subcommand, state flag) pairs. state flag may be 'merged'."""
    kind = kind.strip().lower()
    state = state.strip().lower()
    if kind not in {"issues", "prs", "both"}:
        raise ValueError("kind must be issues, prs, or both")
    if state not in {"open", "closed", "merged", "all"}:
        raise ValueError("state must be open, closed, merged, or all")

    kinds = ["issues", "prs"] if kind == "both" else [kind]
    pairs: list[tuple[str, str]] = []
    for item_kind in kinds:
        if state == "merged":
            if item_kind == "prs":
                pairs.append(("prs", "merged"))
            continue
        if state == "all":
            pairs.append((item_kind, "open"))
            pairs.append((item_kind, "closed"))
            if item_kind == "prs":
                pairs.append(("prs", "merged"))
            continue
        if state == "closed" and item_kind == "prs":
            pairs.append(("prs", "closed"))
            continue
        pairs.append((item_kind, state))
    return pairs


def _snippet(body: str) -> str:
    text = " ".join((body or "").split())
    return text[:_SNIPPET]


def _normalize_hit(item: dict[str, Any], repo_name: str, kind: str, state: str) -> dict[str, Any]:
    labels = item.get("labels") or []
    if labels and isinstance(labels[0], dict):
        labels = [label.get("name", "") for label in labels]
    reported_state = item.get("state") or state
    if state == "merged":
        reported_state = "merged"
    return {
        "repo": repo_name,
        "kind": "pr" if kind == "prs" else "issue",
        "number": item.get("number"),
        "state": reported_state,
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "updated": item.get("updatedAt") or item.get("updated_at") or "",
        "labels": labels,
        "snippet": _snippet(str(item.get("body") or "")),
    }


def _run_gh(args: list[str]) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError:
        return None, "gh is not installed"
    except subprocess.TimeoutExpired:
        return None, f"gh timed out after {_TIMEOUT_SECONDS}s"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "gh failed").strip()
        return None, detail[:500]
    try:
        payload = json.loads(completed.stdout or "[]")
    except json.JSONDecodeError:
        return None, "gh returned non-JSON output"
    if not isinstance(payload, list):
        return None, "gh JSON was not a list"
    return payload, None


def search_tracker_impl(
    query: str,
    repo: str = "PTOAS,pto-isa",
    kind: str = "both",
    state: str = "open",
    max_results: int = 20,
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query cannot be empty")
    if max_results < 1 or max_results > 50:
        raise ValueError("max_results must be between 1 and 50")

    repos = resolve_repos(repo)
    pairs = _queries(kind, state)
    if not pairs:
        return {
            "query": query,
            "repos": [slug for _, slug in repos],
            "kind": kind,
            "state": state,
            "match_count": 0,
            "hits": [],
            "note": "merged applies to pull requests only",
        }

    hits: list[dict[str, Any]] = []
    errors: list[str] = []
    for item_kind, item_state in pairs:
        if len(hits) >= max_results:
            break
        command = [
            "gh",
            "search",
            item_kind,
            "--limit",
            str(max_results),
            "--json",
            "number,title,state,url,updatedAt,body",
        ]
        for _, slug in repos:
            command.extend(["--repo", slug])
        if item_state == "merged":
            command.append("--merged")
        else:
            command.extend(["--state", item_state])
        command.append(query)
        payload, error = _run_gh(command)
        if error:
            errors.append(error)
            continue
        assert payload is not None
        for item in payload:
            if item_state == "closed" and item_kind == "prs":
                # gh --state closed can include merged PRs; keep them out of closed.
                if str(item.get("state", "")).upper() == "MERGED":
                    continue
            repo_name = item.get("repository") or ""
            if isinstance(repo_name, dict):
                repo_name = repo_name.get("nameWithOwner") or repo_name.get("name") or ""
            if not repo_name:
                repo_name = repos[0][1]
            hits.append(_normalize_hit(item, str(repo_name), item_kind, item_state))
            if len(hits) >= max_results:
                break

    result: dict[str, Any] = {
        "query": query,
        "repos": [slug for _, slug in repos],
        "kind": kind,
        "state": state,
        "match_count": len(hits),
        "hits": hits[:max_results],
    }
    if errors and not hits:
        result["error"] = errors[0]
    elif errors:
        result["warnings"] = errors
    return result
