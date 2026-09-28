"""Docs, skills, and rules for one framework layer.

A framework layer is a repository (pypto, PTOAS, pto-isa, simpler, pypto-lib).
Card layers such as ``pypto/passes`` are a different axis and are not listed here.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_hwnative_sys.paths import load_repos_config, workspace_root
from mcp_hwnative_sys.skills import list_skills_impl

# Public name -> directory under the workspace root.
FRAMEWORK_LAYERS: dict[str, str] = {
    "pypto": "pypto",
    "ptoas": "PTOAS",
    "pto-isa": "pto-isa",
    "simpler": "simpler",
    "pypto-lib": "pypto-lib",
}

_SNIPPET_CHARS = 400
_TOPIC_CAP = 15
_PLUGIN_REPOS = ("pypto-user", "pypto-developer")
_EXTRA_DOCS: dict[str, list[str]] = {
    "simpler": ["simpler/docs/scheduler.md"],
}


def _fold_layer_token(layer: str) -> re.Pattern[str]:
    """Match a framework layer as a word, without treating pypto-lib as pypto."""
    if layer == "pypto":
        return re.compile(r"\bpypto\b(?!-lib)", re.IGNORECASE)
    if layer == "pypto-lib":
        return re.compile(r"pypto[-_ ]lib", re.IGNORECASE)
    if layer == "pto-isa":
        return re.compile(r"pto[-_ ]?isa", re.IGNORECASE)
    if layer == "ptoas":
        return re.compile(r"\bptoas\b", re.IGNORECASE)
    return re.compile(rf"\b{re.escape(layer)}\b", re.IGNORECASE)


def _title_and_lead(text: str) -> tuple[str, str]:
    title = ""
    paragraph: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if paragraph:
                break
            continue
        if line.startswith("#") and not title:
            title = line.lstrip("#").strip()
            continue
        if line.startswith("#") and paragraph:
            break
        paragraph.append(line)
    lead = " ".join(paragraph)[:_SNIPPET_CHARS]
    return title, lead


def _doc_counts(docs_root: Path) -> list[dict[str, Any]]:
    if not docs_root.is_dir():
        return []
    counts: list[dict[str, Any]] = []
    root_files = [p for p in docs_root.iterdir() if p.is_file()]
    if root_files:
        counts.append({"directory": "docs", "file_count": len(root_files)})
    for child in sorted(p for p in docs_root.iterdir() if p.is_dir() and p.name != ".git"):
        file_count = sum(1 for p in child.rglob("*") if p.is_file())
        counts.append({"directory": f"docs/{child.name}", "file_count": file_count})
    return counts


def _summarize_file(path: Path, workspace: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    title, lead = _title_and_lead(text)
    return {
        "path": str(path.relative_to(workspace)),
        "title": title or path.stem,
        "summary": lead,
    }


def _canonical_docs(layer: str, repo_dir: str, workspace: Path) -> list[dict[str, str]]:
    meta = load_repos_config().get("repository_meta", {}).get(repo_dir, {})
    rels = list(meta.get("canonical_docs", [])) + _EXTRA_DOCS.get(layer, [])
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for rel in rels:
        if rel in seen:
            continue
        seen.add(rel)
        path = workspace / rel
        if path.is_file():
            found.append(_summarize_file(path, workspace))
    return found


def _topic_docs(repo_root: Path, workspace: Path, topic: str) -> list[dict[str, str]]:
    if not topic.strip():
        return []
    needle = topic.strip().lower()
    docs = repo_root / "docs"
    if not docs.is_dir():
        return []
    matches: list[dict[str, str]] = []
    for path in sorted(docs.rglob("*.md")):
        rel = str(path.relative_to(workspace)).lower()
        if needle not in rel and needle not in path.stem.lower():
            continue
        matches.append(_summarize_file(path, workspace))
        if len(matches) >= _TOPIC_CAP:
            break
    return matches


def _rules(repo_root: Path, workspace: Path) -> list[dict[str, str]]:
    candidates: list[Path] = []
    for rel in ("CLAUDE.md", "AGENTS.md", ".claude/CLAUDE.md", "docs/agent.md"):
        path = repo_root / rel
        if path.is_file():
            candidates.append(path)
    rules_dir = repo_root / ".claude" / "rules"
    if rules_dir.is_dir():
        candidates.extend(sorted(rules_dir.glob("*.md")))
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return [_summarize_file(path, workspace) for path in unique]


def _own_skills(repo_dir: str) -> list[dict[str, str]]:
    try:
        listed = list_skills_impl(repo_dir)
    except ValueError:
        return []
    return [
        {"name": s["name"], "summary": s.get("summary", ""), "path": s.get("path", "")}
        for s in listed.get("skills", [])
    ]


def _plugin_skills(layer: str) -> list[dict[str, str]]:
    pattern = _fold_layer_token(layer)
    found: list[dict[str, str]] = []
    for plugin in _PLUGIN_REPOS:
        try:
            listed = list_skills_impl(plugin)
        except ValueError:
            continue
        for skill in listed.get("skills", []):
            blob = f"{skill.get('name', '')} {skill.get('summary', '')}"
            if pattern.search(blob):
                found.append(
                    {
                        "name": skill["name"],
                        "summary": skill.get("summary", ""),
                        "path": skill.get("path", ""),
                        "repo": plugin,
                    }
                )
    return found


def layer_guide_impl(layer: str, topic: str = "") -> dict[str, Any]:
    key = layer.strip().lower()
    if key == "all":
        return {
            "layer": "all",
            "layers": [layer_guide_impl(name, topic) for name in FRAMEWORK_LAYERS],
        }
    if key not in FRAMEWORK_LAYERS:
        available = ", ".join([*FRAMEWORK_LAYERS, "all"])
        raise ValueError(f"Unknown framework layer '{layer}'. Available: {available}")

    repo_dir = FRAMEWORK_LAYERS[key]
    workspace = workspace_root()
    repo_root = workspace / repo_dir
    if not repo_root.is_dir():
        raise ValueError(f"Repository directory not found: {repo_dir}")

    return {
        "layer": key,
        "repo": repo_dir,
        "read_with": "read_doc",
        "docs": {
            "directories": _doc_counts(repo_root / "docs"),
            "canonical": _canonical_docs(key, repo_dir, workspace),
            "topic_matches": _topic_docs(repo_root, workspace, topic),
        },
        "skills": _own_skills(repo_dir),
        "shared_skills": _plugin_skills(key),
        "rules": _rules(repo_root, workspace),
    }
