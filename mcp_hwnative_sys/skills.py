"""Agent-skill inventory across the hw-native-sys workspace.

Each sibling repo ships a `.agents/skills` / `.claude/skills` corpus whose
SKILL.md frontmatter (``name`` / ``description``) is the canonical summary.
``config/skills.json`` only maps repo -> skill directory; the actual inventory
is read live from each SKILL.md so it never drifts from the repo. A skill a
repo removes simply disappears from the listing.

Read-only with respect to the sibling repos: source material only.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from mcp_hwnative_sys.paths import load_json_cached, project_root, workspace_root

SKILLS_CONFIG_PATH = "config/skills.json"

# Heavy subtree names never worth descending into when scanning for skills.
_SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules"}


def skills_config_path() -> Path:
    return project_root() / SKILLS_CONFIG_PATH


def load_skills_config() -> dict[str, Any]:
    return load_json_cached(skills_config_path())


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Extract ``name`` and ``description`` from a SKILL.md frontmatter block.

    Handles ``name: foo`` and both ``description: single line`` and folded
    ``description: >-\n  line1\n  line2`` forms. Returns {} when there is no
    frontmatter block.
    """
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    lines = text[3:end].splitlines()
    out: dict[str, str] = {}
    active: str | None = None
    for raw in lines:
        if not raw.strip():
            continue
        match = re.match(r"^([A-Za-z_]+):\s*(.*)$", raw)
        if match and not raw.startswith((" ", "\t")):
            key, value = match.group(1), match.group(2).strip()
            active = key if key in ("name", "description") else None
            if active and value and value not in (">-", ">", "|", "|-"):
                out[active] = value
            elif active:
                out.setdefault(active, "")
            continue
        # Continuation line of a folded description (indented) or an orphaned
        # value line — append to whichever of name/description is active.
        if active and active in out:
            out[active] = (out[active] + " " + raw.strip()).strip()
    return out


def _fallback_summary(body: str) -> str:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if line.startswith("#") and not line.startswith("##"):
            # First heading, then the first non-heading paragraph after it.
            for following in lines[i + 1 :]:
                if following and not following.startswith("#"):
                    return following[:200]
            break
    return ""


def _skill_files(repo: str, entry: dict[str, Any], root: Path) -> list[tuple[str, Path]]:
    if not entry:
        return []
    found: list[tuple[str, Path]] = []
    for rel in entry.get("files", []):
        path = root / rel
        if path.exists():
            found.append((repo, path))
    directory = entry.get("dir")
    if directory:
        base = root / directory
        if base.is_dir():
            for path in sorted(base.rglob("SKILL.md")):
                if any(part in _SKIP_DIRS for part in path.parts):
                    continue
                found.append((repo, path))
    return found


def _load_skill(repo: str, path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    front = _parse_frontmatter(text)
    name = front.get("name") or path.parent.name
    summary = front.get("description") or _fallback_summary(text)
    return {
        "repo": repo,
        "name": name,
        "summary": summary,
        "path": str(path.relative_to(project_root().parents[1])),
    }


def build_skills_index() -> dict[str, Any]:
    cfg = load_skills_config()
    root = workspace_root()
    repos: dict[str, list[dict[str, str]]] = {}
    total = 0
    for repo in sorted(cfg.get("repos", {})):
        entry = cfg["repos"][repo]
        files = _skill_files(repo, entry, root)
        if not files:
            continue
        skills = [_load_skill(repo, path) for _, path in files]
        repos[repo] = sorted(skills, key=lambda s: s["name"])
        total += len(skills)
    return {"config_version": cfg.get("version", "unknown"), "total_skills": total, "repos": repos}


def list_skills_impl(repo: str = "") -> dict[str, Any]:
    index = build_skills_index()
    repos = index["repos"]
    if repo:
        if repo not in repos:
            raise ValueError(
                f"Unknown repo '{repo}' (no skills configured). Available: {', '.join(sorted(repos)) or 'none'}"
            )
        return {
            "repo": repo,
            "skills": repos[repo],
            "total": len(repos[repo]),
        }
    # Keep per-repo listings compact: name + summary, not the full card.
    compact = {
        name: [{"name": s["name"], "summary": s["summary"]} for s in skills]
        for name, skills in repos.items()
    }
    return {"total_skills": index["total_skills"], "repos": compact}


def find_skill_impl(query: str, repo: str = "") -> dict[str, Any]:
    index = build_skills_index()
    repos = index["repos"]
    if repo and repo not in repos:
        raise ValueError(
            f"Unknown repo '{repo}' (no skills configured). Available: {', '.join(sorted(repos)) or 'none'}"
        )
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t]
    matches: list[dict[str, str]] = []
    for repo_name, skills in repos.items():
        if repo and repo_name != repo:
            continue
        for skill in skills:
            haystack = (skill["name"] + " " + skill["summary"]).lower()
            if not tokens:
                continue
            if all(t in haystack for t in tokens):
                matches.append(skill)
    return {"query": query, "repo": repo or "all", "count": len(matches), "matches": matches[:25]}
