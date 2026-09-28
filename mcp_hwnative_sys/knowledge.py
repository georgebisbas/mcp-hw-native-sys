from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from mcp_hwnative_sys.doc_sections import build_section_toc, extract_section
from mcp_hwnative_sys.paths import (
    abstractions_config_path,
    ascend_abstractions_config_path,
    entrypoints_config_path,
    knowledge_config_path,
    load_json_cached,
    load_repos_config,
    project_root,
    resolve_doc_path,
    resolve_workspace_path,
    workspace_root,
)

EPHEMERAL_PREFIXES = ("pypto-3.0-notes/pr_plans/", "pypto-3.0-notes/pull_requests/")
NOTES_FRESHNESS_PATH = "pypto-3.0-notes/NOTES_FRESHNESS.md"


def load_knowledge_config() -> dict[str, Any]:
    return load_json_cached(knowledge_config_path())


def load_entrypoints() -> dict[str, Any]:
    return load_json_cached(entrypoints_config_path())


# Auto-generated abstraction cards (from tools/build_pto_isa_index.py and
# tools/build_ptoas_index.py) are merged in first so they cover the long tail
# of pto-isa instructions and PTOAS ops that nobody has hand-curated yet; any
# hand-curated card with the same key always wins outright.
_GENERATED_ABSTRACTION_FILES = ("pto_isa_generated.json", "ptoas_generated.json")
_CATALOG_CARD_FILES = ("simpler_scheduler.json", "pypto_lib_workloads.json")

# Merged abstractions are cached against the mtimes of every source file so an
# edit to any of them is picked up without restarting the server.
_abstractions_cache: tuple[tuple[float, ...], dict[str, Any]] | None = None


def load_abstractions() -> dict[str, Any]:
    global _abstractions_cache
    base_path = abstractions_config_path()
    ascend_path = ascend_abstractions_config_path()
    generated_paths = [project_root() / "config" / name for name in _GENERATED_ABSTRACTION_FILES]
    catalog_paths = [project_root() / "config" / name for name in _CATALOG_CARD_FILES]
    all_paths = [base_path, ascend_path, *generated_paths, *catalog_paths]
    key = tuple(p.stat().st_mtime if p.exists() else 0.0 for p in all_paths)
    if _abstractions_cache is not None and _abstractions_cache[0] == key:
        return _abstractions_cache[1]

    merged: dict[str, Any] = {}
    for path in generated_paths:
        if path.exists():
            merged.update(load_json_cached(path))
    for path in catalog_paths:
        if not path.exists():
            continue
        payload = load_json_cached(path)
        cards = payload.get("cards") if isinstance(payload, dict) else None
        if isinstance(cards, dict):
            merged.update(cards)
    merged.update(load_json_cached(base_path))
    if ascend_path.exists():
        merged.update(load_json_cached(ascend_path))

    _abstractions_cache = (key, merged)
    return merged


_ABSTRACTION_ALIASES: dict[str, str] = {
    "aicore-cube": "AIC",
    "cube": "AIC",
    "aicore-vector": "AIV",
    "vector": "AIV",
    "hccl": "HCCLWindow",
    "hcclwindow": "HCCLWindow",
    "commremoteptr": "CommRemotePtr",
    "910b": "Ascend910B",
    "910c": "Ascend910B",
    "950": "Ascend950",
    "arch35": "Ascend950",
    "notifyop": "NotifyOp",
    "waitcmp": "WaitCmp",
}


def _fold_abstraction_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", name.lower())


def _card_layer_matches(card: dict[str, Any], layer: str) -> bool:
    card_layer = str(card.get("layer", "")).lower()
    wanted = layer.strip().lower().rstrip("/")
    if not wanted:
        return True
    return card_layer == wanted or card_layer.startswith(wanted + "/")


def _abstraction_candidates(name: str, layer: str = "") -> list[str]:
    """Exact key wins. Otherwise every case-folded match is returned."""
    abstractions = load_abstractions()
    if name in abstractions and _card_layer_matches(abstractions[name], layer):
        return [name]
    folded = _fold_abstraction_name(name)
    if not folded:
        return []
    matches = [
        key
        for key, card in abstractions.items()
        if _fold_abstraction_name(key) == folded and _card_layer_matches(card, layer)
    ]
    if matches:
        return matches
    alias = _ABSTRACTION_ALIASES.get(folded)
    if alias and alias in abstractions and _card_layer_matches(abstractions[alias], layer):
        return [alias]
    return []


def suggest_similar(query: str, candidates: list[str], limit: int = 5) -> list[str]:
    """Return near-miss candidates for a query, preserving original casing.

    Used for "did you mean" hints on 0-hit lookups. Two-stage: exact
    normalize-stripped token overlap first, then fuzzy string similarity.
    """
    from difflib import get_close_matches

    q = query.strip().lower()
    if not q:
        return []

    # Token-overlap matches (handles snake_case vs "natural language").
    tokens = [t for t in re.split(r"[^a-z0-9]+", q) if t]
    by_lower = {}
    for c in candidates:
        by_lower.setdefault(c.lower(), c)
    overlap: list[tuple[int, str]] = []
    if tokens:
        for lower, orig in by_lower.items():
            norm = re.sub(r"[^a-z0-9]+", " ", lower)
            hits = sum(1 for t in tokens if t in norm)
            if hits:
                overlap.append((hits, orig))
    overlap.sort(key=lambda pair: -pair[0])

    # Fuzzy matches for typos.
    fuzzy = get_close_matches(q, list(by_lower), n=limit, cutoff=0.6)
    fuzzy_orig = [by_lower[f] for f in fuzzy]

    merged: list[str] = []
    seen: set[str] = set()
    for _, orig in overlap:
        if orig in seen:
            continue
        seen.add(orig)
        merged.append(orig)
    for orig in fuzzy_orig:
        if orig in seen:
            continue
        seen.add(orig)
        merged.append(orig)
    return merged[:limit]


def _bootstrap_prompt_for_task(task_type: str) -> str:
    if task_type in ("ascend_arch", "ascend_runtime", "npu_tuning", "npu_verify_handoff"):
        return "start_ascend_work"
    if task_type.startswith("distributed") or task_type == "host_collectives_program":
        return "start_distributed_work"
    return "start_compiler_work"


def resolve_doc_tier(relative_path: str) -> str:
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("content/"):
        return "mcp-owned"
    for prefix in EPHEMERAL_PREFIXES:
        if normalized.startswith(prefix):
            return "ephemeral"
    if normalized.startswith("pypto-3.0-notes/"):
        return "enriched"
    if normalized.startswith("pypto_top_level_documents/"):
        return "design"
    return "canonical"


# Cache the parsed freshness table against the source file's mtime — it is
# read once per enriched path in knowledge_health_impl's loops.
_notes_freshness_cache: tuple[float, dict[str, str]] | None = None


def _parse_notes_freshness() -> dict[str, str]:
    global _notes_freshness_cache
    root = workspace_root()
    freshness_path = root / NOTES_FRESHNESS_PATH
    if not freshness_path.exists():
        _notes_freshness_cache = None
        return {}

    mtime = freshness_path.stat().st_mtime
    if _notes_freshness_cache is not None and _notes_freshness_cache[0] == mtime:
        return _notes_freshness_cache[1]

    text = freshness_path.read_text(encoding="utf-8")
    mapping: dict[str, str] = {}
    for match in re.finditer(r"\[([^\]]+\.md)\]\(([^)]+)\)[^\n]*\|\s*(\d{4}-\d{2}-\d{2})", text):
        link_path = match.group(2)
        verified = match.group(3)
        if link_path.startswith("../"):
            rel = link_path.removeprefix("../")
        else:
            rel = f"pypto-3.0-notes/{link_path}"
        mapping[rel] = verified
    _notes_freshness_cache = (mtime, mapping)
    return mapping


def _doc_front_matter(relative_path: str) -> str:
    tier = resolve_doc_tier(relative_path)
    lines = [f"tier: {tier}", f"path: {relative_path}"]
    if tier == "enriched":
        verified = _parse_notes_freshness().get(relative_path)
        if verified:
            lines.append(f"last_verified: {verified}")
    return "---\n" + "\n".join(lines) + "\n---\n\n"


def _truncate_slice(text: str, max_chars: int, relative_path: str) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars].rstrip()
    return f"{truncated}\n\n... (truncated — read full file at {relative_path})"


def read_doc_slice(
    relative_path: str,
    max_chars: int = 8000,
    section: str | None = None,
) -> str:
    resolved = resolve_doc_path(relative_path)
    if not resolved.exists():
        raise FileNotFoundError(f"Document not found: {relative_path}")

    content = resolved.read_text(encoding="utf-8", errors="replace")
    if section:
        extracted = extract_section(content, section)
        if extracted is None:
            toc = build_section_toc(content, max_entries=20)
            body = (
                f"Section '{section}' not found in {relative_path}.\n\n"
                f"{toc}\n\n"
                f"... (falling back to document head)\n\n"
                f"{_truncate_slice(content, max_chars, relative_path)}"
            )
        else:
            body = _truncate_slice(extracted, max_chars, relative_path)
    else:
        body = _truncate_slice(content, max_chars, relative_path)
    return _doc_front_matter(relative_path) + body


def read_multiple_docs(
    paths: list[str],
    max_chars: int = 8000,
    sections: list[str | None] | None = None,
) -> str:
    if not paths:
        raise ValueError("paths cannot be empty")

    # max_chars is a global budget across all docs. Track usage incrementally
    # so the loop stays O(n) rather than re-summing every part each iteration.
    parts: list[str] = []
    used = 0
    for index, path in enumerate(paths):
        remaining = max_chars - used
        if remaining <= 0:
            parts.append(f"\n... (additional docs omitted: {', '.join(paths[index:])})")
            break
        section = None
        if sections and index < len(sections):
            section = sections[index]
        slice_text = read_doc_slice(path, max_chars=remaining, section=section)
        parts.append(slice_text)
        used += len(slice_text)

    return "\n\n".join(parts)


def read_doc_payload(path: str, max_chars: int = 12000, section: str = "") -> dict[str, Any]:
    if max_chars < 500 or max_chars > 50000:
        raise ValueError("max_chars must be between 500 and 50000")

    tier = resolve_doc_tier(path)
    if tier == "ephemeral":
        raise ValueError(f"Refusing to serve ephemeral-tier doc via read_doc: {path}")

    exists = resolve_doc_path(path).exists()
    section_arg = section.strip() or None
    content = read_doc_slice(path, max_chars=max_chars, section=section_arg) if exists else ""
    return {
        "path": path,
        "tier": tier,
        "exists": exists,
        "section": section_arg,
        "content": content,
    }


_SKILL_STOPWORDS = {
    "for", "the", "and", "are", "via", "with", "from", "into", "across", "over",
    "you", "your", "new", "each", "every", "per", "any", "see", "use", "used",
    "when", "what", "that", "this", "these", "those", "can", "may", "all", "its",
}


def _route_skill_hints(task_type: str, description: str) -> list[dict[str, str]]:
    """Best-effort top-5 skill hints for a route, matched by token overlap.

    The skill inventory (config/skills.json + live SKILL.md frontmatter) is the
    agent-skill corpus; surfacing it in route_task means an agent discovers the
    right workflow (compare-codegen, generate-ir-trace, dfx-analyze, ...) in the
    first orientation call instead of needing a separate find_skill call.
    """
    try:
        from mcp_hwnative_sys.skills import build_skills_index

        index = build_skills_index()
    except Exception:  # noqa: BLE001 - hints must never break routing
        return []
    text = f"{task_type} {description}".lower().replace("_", " ")
    tokens = {
        t for t in re.split(r"[^a-z0-9]+", text)
        if len(t) >= 3 and t not in _SKILL_STOPWORDS
    }
    if not tokens:
        return []
    scored: list[tuple[int, str, dict[str, str]]] = []
    for repo, skills in index.get("repos", {}).items():
        for skill in skills:
            haystack = (skill["name"] + " " + skill["summary"]).lower()
            hits = sum(1 for token in tokens if token in haystack)
            if hits:
                scored.append(
                    (
                        hits,
                        skill["name"],
                        {
                            "repo": repo,
                            "name": skill["name"],
                            "summary": skill["summary"][:200],
                            "path": skill["path"],
                        },
                    )
                )
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [card for _, _, card in scored[:5]]


def _resolve_entrypoints(entrypoint_areas: list[str]) -> dict[str, list[str]]:
    entrypoints = load_entrypoints()
    output: dict[str, list[str]] = {}
    for area in entrypoint_areas:
        if ":" in area:
            repo, key = area.split(":", 1)
            paths = entrypoints.get(repo, {}).get(key, [])
            if paths:
                output[f"{repo}/{key}"] = paths
        else:
            repo_paths = entrypoints.get(area, {})
            if repo_paths:
                output[area] = [path for paths in repo_paths.values() for path in paths]
    return output


def route_task_impl(task_type: str, detail: str = "") -> dict[str, Any]:
    config = load_knowledge_config()
    routes = config.get("routes", {})
    route = routes.get(task_type)
    if route is None:
        available = ", ".join(sorted(routes))
        raise ValueError(f"Unknown task_type '{task_type}'. Available: {available}")

    canonical_docs = [
        {
            "path": path,
            "tier": resolve_doc_tier(path),
            "exists": resolve_workspace_path(path).exists(),
        }
        for path in route.get("read_first_canonical", [])
    ]
    enriched_docs = [
        {
            "path": path,
            "tier": "enriched",
            "exists": resolve_workspace_path(path).exists(),
            "last_verified": _parse_notes_freshness().get(path),
        }
        for path in route.get("read_first_enriched", [])
    ]
    rules = [
        {
            "path": path,
            "tier": resolve_doc_tier(path),
            "exists": resolve_workspace_path(path).exists(),
        }
        for path in route.get("rules", [])
    ]

    return {
        "task_type": task_type,
        "description": route.get("description", ""),
        "detail": detail.strip() or None,
        "read_first_canonical": canonical_docs,
        "read_first_enriched": enriched_docs,
        "rules": rules,
        "skills": _route_skill_hints(task_type, route.get("description", "")),
        "entrypoints": _resolve_entrypoints(route.get("entrypoint_areas", [])),
        "verify_tasks": route.get("verify_tasks", []),
        "agent_verify_tasks": route.get("agent_verify_tasks", route.get("verify_tasks", [])),
        "developer_verify_tasks": route.get("developer_verify_tasks", []),
        "resources": [f"hw-native-sys://{uri}" for uri in route.get("resources", [])],
        "suggested_tools": route.get("suggested_tools", []),
        "bootstrap_prompt": _bootstrap_prompt_for_task(task_type),
    }


def list_knowledge_topics_impl() -> dict[str, Any]:
    config = load_knowledge_config()
    routes = config.get("routes", {})
    resources = config.get("resources", {})
    notes_topics = config.get("notes_topics", {})

    return {
        "task_types": [
            {
                "task_type": key,
                "description": value.get("description", ""),
                "resources": value.get("resources", []),
            }
            for key, value in sorted(routes.items())
        ],
        "resources": [
            {
                "uri": f"hw-native-sys://{key}",
                "tier": value.get("tier", "canonical"),
            }
            for key, value in sorted(resources.items())
        ],
        "notes_topics": [
            {"topic": key, "uri": f"hw-native-sys://notes/{key}"}
            for key in sorted(notes_topics)
        ],
        "prompts": ["start_compiler_work", "start_distributed_work", "start_ascend_work", "start_npu_verify", "debug_codegen_work", "finish_work"],
    }


def explain_abstraction_impl(name: str, layer: str = "") -> dict[str, Any]:
    abstractions = load_abstractions()
    keys = _abstraction_candidates(name, layer)
    if not keys:
        suggestions = suggest_similar(name, list(abstractions), limit=5)
        hint = f" Did you mean: {', '.join(suggestions)}." if suggestions else ""
        available = ", ".join(sorted(abstractions)[:25])
        raise ValueError(f"Unknown abstraction '{name}'.{hint} Examples: {available}")
    if len(keys) > 1:
        return {
            "ambiguous": True,
            "query": name,
            "candidates": [
                {
                    "name": key,
                    "layer": abstractions[key].get("layer"),
                    "one_liner": abstractions[key].get("one_liner") or abstractions[key].get("kind", ""),
                }
                for key in keys
            ],
        }

    key = keys[0]
    card = abstractions[key]
    return {
        "name": key,
        "source": card.get("source", "curated"),
        "layer": card.get("layer"),
        "kind": card.get("kind"),
        "tags": card.get("tags", []),
        "arch_families": card.get("arch_families", []),
        "repos": card.get("repos", []),
        "paths": card.get("paths", []),
        "docs_canonical": [
            {"path": p, "exists": _path_exists(p)}
            for p in card.get("docs_canonical", [])
        ],
        "docs_enriched": [
            {
                "path": p,
                "exists": resolve_workspace_path(p).exists(),
                "last_verified": _parse_notes_freshness().get(p),
            }
            for p in card.get("docs_enriched", [])
        ],
        "rules": card.get("rules", []),
        "related": card.get("related", []),
        "downstream": card.get("downstream", []),
        "verify_tasks": card.get("verify_tasks", []),
        "agent_verify_tasks": card.get("agent_verify_tasks", card.get("verify_tasks", [])),
        "developer_verify_tasks": card.get("developer_verify_tasks", []),
        "agent_policy": card.get("agent_policy", []),
    }


def _abstraction_relevance(name: str, card: dict[str, Any], needle: str) -> int:
    name_lower = name.lower()
    if name_lower == needle:
        return 4
    if needle in name_lower:
        return 3
    tags = " ".join(card.get("tags", [])).lower()
    if needle in tags:
        return 2
    layer = str(card.get("layer", "")).lower()
    kind = str(card.get("kind", "")).lower()
    if needle in layer or needle in kind:
        return 1
    return 0


def search_abstractions_impl(
    query: str,
    max_results: int = 20,
    fields: str = "summary",
    layer: str = "",
) -> dict[str, Any]:
    if not query.strip():
        raise ValueError("query cannot be empty")
    if max_results < 1 or max_results > 100:
        raise ValueError("max_results must be between 1 and 100")

    needle = query.strip().lower()
    tokens = [token for token in re.split(r"[^a-z0-9]+", needle) if token]
    abstractions = load_abstractions()
    scored: list[tuple[int, int, str, dict[str, Any]]] = []

    for name, card in abstractions.items():
        if not _card_layer_matches(card, layer):
            continue
        haystack = " ".join(
            [
                name,
                str(card.get("layer", "")),
                str(card.get("kind", "")),
                str(card.get("one_liner", "")),
                " ".join(card.get("tags", [])),
                " ".join(card.get("arch_families", [])),
                " ".join(card.get("repos", [])),
                " ".join(card.get("related", [])),
                " ".join(card.get("downstream", [])),
            ]
        ).lower()
        # Normalize separators so snake_case names ("host_collectives_program")
        # match natural-language multi-word queries ("host collectives").
        normalized = re.sub(r"[^a-z0-9]+", " ", haystack)
        if tokens and all(token in normalized for token in tokens):
            coverage = sum(1 for token in tokens if token in normalized)
            scored.append((coverage, _abstraction_relevance(name, card, needle), name, card))

    scored.sort(key=lambda t: (-t[0], -t[1]))
    matches: list[dict[str, Any]] = []
    for _, _, name, card in scored[:max_results]:
        if fields == "full":
            matches.append(
                {
                    "name": name,
                    "layer": card.get("layer"),
                    "kind": card.get("kind"),
                    "tags": card.get("tags", []),
                    "arch_families": card.get("arch_families", []),
                    "repos": card.get("repos", []),
                }
            )
        else:
            matches.append(
                {
                    "name": name,
                    "layer": card.get("layer"),
                    "one_liner": card.get("one_liner") or card.get("kind", ""),
                }
            )

    by_layer: dict[str, list[dict[str, Any]]] = {}
    for match in matches:
        by_layer.setdefault(str(match.get("layer") or ""), []).append(match)
    result: dict[str, Any] = {
        "query": query,
        "layer": layer or None,
        "match_count": len(matches),
        "matches": matches,
        "by_layer": by_layer,
    }
    if not matches:
        result["suggestions"] = suggest_similar(query, list(abstractions), limit=5)
    return result


def find_entrypoints_impl(repo: str, area: str = "") -> dict[str, Any]:
    entrypoints = load_entrypoints()
    repo_map = entrypoints.get(repo)
    if repo_map is None:
        available = ", ".join(sorted(entrypoints))
        raise ValueError(f"Unknown repo '{repo}'. Available: {available}")

    if area:
        paths = repo_map.get(area)
        if paths is None:
            available_areas = ", ".join(sorted(repo_map))
            raise ValueError(f"Unknown area '{area}' for repo '{repo}'. Available: {available_areas}")
        return {"repo": repo, "area": area, "paths": paths}

    return {"repo": repo, "areas": repo_map}


def trace_in_stack_impl(symbol_or_path: str) -> dict[str, Any]:
    from mcp_hwnative_sys.contract_trace import trace_in_stack_impl as _impl

    return _impl(symbol_or_path)


def _path_exists(relative_path: str) -> bool:
    if relative_path.replace("\\", "/").startswith("content/"):
        return resolve_doc_path(relative_path).exists()
    return resolve_workspace_path(relative_path).exists()


def knowledge_health_impl() -> dict[str, Any]:
    config = load_knowledge_config()
    root = workspace_root()
    missing: list[str] = []
    stale_enriched: list[dict[str, str]] = []
    ascend_issues: list[str] = []
    freshness = _parse_notes_freshness()
    today = date.today()

    def check_path(path: str) -> None:
        if path and not _path_exists(path):
            missing.append(path)

    for route in config.get("routes", {}).values():
        for path in route.get("read_first_canonical", []):
            check_path(path)
        for path in route.get("read_first_enriched", []):
            check_path(path)
            verified = freshness.get(path)
            if verified:
                verified_date = datetime.strptime(verified, "%Y-%m-%d").date()
                age_days = (today - verified_date).days
                if age_days > 30:
                    stale_enriched.append({"path": path, "last_verified": verified, "age_days": str(age_days)})

    ascend_arch_path = "pypto-3.0-notes/performance_tuning/ascend-architectures.md"
    if not _path_exists(ascend_arch_path):
        ascend_issues.append(f"Missing ascend arch reference: {ascend_arch_path}")
    else:
        verified = freshness.get(ascend_arch_path)
        if verified:
            age_days = (today - datetime.strptime(verified, "%Y-%m-%d").date()).days
            if age_days > 30:
                ascend_issues.append(f"Stale ascend-architectures.md ({age_days}d since last_verified)")

    for name in ("which_platform.md", "alignment_rules.md", "hccl_container_checklist.md"):
        content_path = f"content/ascend/{name}"
        if not resolve_doc_path(content_path).exists():
            ascend_issues.append(f"Missing MCP content: {content_path}")

    for resource in config.get("resources", {}).values():
        paths = resource.get("paths", [])
        single = resource.get("path")
        if single:
            paths = [*paths, single]
        for path in paths:
            check_path(path)

    for path in config.get("notes_topics", {}).values():
        check_path(path)

    abstractions = load_abstractions()
    for card in abstractions.values():
        for path in card.get("paths", []):
            check_path(path)
        for path in card.get("docs_canonical", []):
            check_path(path)

    index_build_marker = project_root() / "config" / ".index_build_time"
    last_index_build = None
    if index_build_marker.exists():
        last_index_build = index_build_marker.read_text(encoding="utf-8").strip()

    ascend_route_count = sum(1 for k in config.get("routes", {}) if k.startswith(("ascend_", "npu_")))

    # Surface a passes-index scrape failure (e.g. pass_manager.py refactored so
    # the extraction regex no longer matches) instead of silently reporting 0.
    from mcp_hwnative_sys.passes_index import load_passes_index

    passes_index = load_passes_index()
    passes_index_warning = passes_index.get("warning")

    # How much of pto-isa/PTOAS's real surface area the generated indices
    # actually cover -- self-reported so index staleness/drift shows up here
    # instead of requiring a manual audit to discover.
    coverage: dict[str, int] = {}
    for repo_key, filename in (
        ("pto_isa_indexed", "pto_isa_generated.json"),
        ("ptoas_indexed", "ptoas_generated.json"),
    ):
        gen_path = project_root() / "config" / filename
        coverage[repo_key] = len(load_json_cached(gen_path)) if gen_path.exists() else 0

    catalog_issues: list[str] = []
    scheduler_implementation_count = 0
    workload_count = 0
    scheduler_path = project_root() / "config" / "simpler_scheduler.json"
    workload_path = project_root() / "config" / "pypto_lib_workloads.json"
    if not scheduler_path.exists():
        catalog_issues.append("Missing config/simpler_scheduler.json")
    else:
        scheduler_payload = load_json_cached(scheduler_path)
        scheduler_implementation_count = len(scheduler_payload.get("implementations", []))
        if scheduler_implementation_count == 0:
            catalog_issues.append("simpler scheduler implementation count is 0")
    if not workload_path.exists():
        catalog_issues.append("Missing config/pypto_lib_workloads.json")
    else:
        workload_payload = load_json_cached(workload_path)
        workload_count = len(workload_payload.get("workloads", []))
        if workload_count == 0:
            catalog_issues.append("pypto-lib workload count is 0")

    # Skill corpus: how many SKILL.md files the configured dirs currently
    # resolve, and which configured dirs/files are missing on disk.
    skills_issues: list[str] = []
    skills_total = 0
    try:
        from mcp_hwnative_sys.skills import build_skills_index, load_skills_config

        skills_cfg = load_skills_config()
        root = workspace_root()
        for repo_key, entry in (skills_cfg.get("repos", {}) or {}).items():
            for rel in entry.get("files", []):
                if not (root / rel).exists():
                    skills_issues.append(f"Missing skill file [{repo_key}]: {rel}")
            directory = entry.get("dir")
            if directory and not (root / directory).is_dir():
                skills_issues.append(f"Missing skill dir [{repo_key}]: {directory}")
        skills_index = build_skills_index()
        skills_total = skills_index.get("total_skills", 0)
    except Exception as exc:  # noqa: BLE001 - health must never raise
        skills_issues.append(f"Skill scan failed: {exc}")

    return {
        "config_version": config.get("version", "unknown"),
        "workspace_root": str(root),
        "abstraction_count": len(abstractions),
        "ascend_route_count": ascend_route_count,
        "missing_paths_count": len(missing),
        "missing_paths": list(dict.fromkeys(missing))[:50],
        "stale_enriched_count": len(stale_enriched),
        "stale_enriched": stale_enriched[:20],
        "ascend_issues_count": len(ascend_issues),
        "ascend_issues": ascend_issues[:20],
        "skills_total": skills_total,
        "skills_issues_count": len(skills_issues),
        "skills_issues": skills_issues[:20],
        "pypto_pass_count": len(passes_index.get("passes", [])),
        "pypto_passes_index_warning": passes_index_warning,
        "coverage": coverage,
        "scheduler_implementation_count": scheduler_implementation_count,
        "workload_count": workload_count,
        "catalog_issues": catalog_issues,
        "last_index_build": last_index_build,
    }


def render_resource(uri_suffix: str) -> str:
    config = load_knowledge_config()
    resources = config.get("resources", {})
    notes_topics = config.get("notes_topics", {})

    if uri_suffix == "agent/routing":
        topics = list_knowledge_topics_impl()
        lines = ["# Task routing index", ""]
        lines.append("## Compiler / stack")
        for item in topics["task_types"]:
            if item["task_type"].startswith(("ascend_", "npu_")):
                continue
            lines.append(f"- **{item['task_type']}**: {item['description']}")
        lines.append("")
        lines.append("## Ascend architecture / NPU")
        for item in topics["task_types"]:
            if item["task_type"].startswith(("ascend_", "npu_")):
                lines.append(f"- **{item['task_type']}**: {item['description']}")
        lines.append("")
        lines.append("Bootstrap: `start_ascend_work` (focus: arch | tuning | hccl | verify)")
        return _doc_front_matter("config/knowledge.json") + "\n".join(lines)

    if uri_suffix.startswith("notes/"):
        topic = uri_suffix.removeprefix("notes/")
        path = notes_topics.get(topic)
        if path is None:
            available = ", ".join(sorted(notes_topics))
            raise ValueError(f"Unknown notes topic '{topic}'. Available: {available}")
        return read_doc_slice(path, max_chars=8000)

    resource = resources.get(uri_suffix)
    if resource is None:
        available = ", ".join(sorted(resources.keys()))
        raise ValueError(f"Unknown resource '{uri_suffix}'. Available: {available}")

    paths = resource.get("paths")
    section_hint = resource.get("section_hint")
    if paths:
        sections = [section_hint if index == 0 else None for index in range(len(paths))]
        return read_multiple_docs(paths, max_chars=resource.get("max_chars", 8000), sections=sections)

    path = resource.get("path")
    if not path:
        raise ValueError(f"Resource '{uri_suffix}' has no path configured")
    return read_doc_slice(
        path,
        max_chars=resource.get("max_chars", 8000),
        section=section_hint,
    )


def get_repository_meta() -> dict[str, Any]:
    return load_repos_config().get("repository_meta", {})


def _register_resource(mcp: FastMCP, uri_suffix: str) -> None:
    def _handler() -> str:
        return render_resource(uri_suffix)

    _handler.__name__ = f"resource_{uri_suffix.replace('/', '_')}"
    mcp.resource(f"hw-native-sys://{uri_suffix}")(_handler)


def register_knowledge(mcp: FastMCP) -> None:
    """Register knowledge-layer resources, tools, and prompts on the MCP server."""

    config = load_knowledge_config()

    for uri_suffix in config.get("resources", {}):
        _register_resource(mcp, uri_suffix)

    def agent_routing_resource() -> str:
        return render_resource("agent/routing")

    mcp.resource("hw-native-sys://agent/routing")(agent_routing_resource)

    # Some notes topics are also listed under `resources` with richer metadata
    # (per-topic max_chars). Skip re-registering them here to avoid duplicate
    # "Resource already exists" warnings; the resource handler serves them.
    resource_uris = set(config.get("resources", {}))
    for topic in config.get("notes_topics", {}):
        if f"notes/{topic}" in resource_uris:
            continue

        def _make_notes_handler(note_topic: str):
            def _handler() -> str:
                return render_resource(f"notes/{note_topic}")

            _handler.__name__ = f"notes_{note_topic}"
            return _handler

        mcp.resource(f"hw-native-sys://notes/{topic}")(_make_notes_handler(topic))

    @mcp.tool()
    def list_task_types() -> list[dict[str, str]]:
        """Return all valid task_type values with one-line descriptions for use with bootstrap_session and route_task."""
        config = load_knowledge_config()
        routes = config.get("routes", {})
        return [
            {"task_type": key, "description": value.get("description", "")}
            for key, value in sorted(routes.items())
        ]

    @mcp.tool()
    def route_task(
        task_type: Annotated[str, Field(description='Task type key — use list_task_types() to enumerate valid values, e.g. "distributed_codegen", "ascend_arch"')],
        detail: Annotated[str, Field(description="Optional free-text context (e.g. symbol or feature name) passed through to the routing output")] = "",
    ) -> dict[str, Any]:
        """Return read-first docs, rules, entrypoints, and verify tasks for a compiler workflow."""
        return route_task_impl(task_type, detail)

    @mcp.tool()
    def list_knowledge_topics() -> dict[str, Any]:
        """List available task routes, MCP resources, notes topics, and bootstrap prompts."""
        return list_knowledge_topics_impl()

    @mcp.tool()
    def read_doc(
        path: Annotated[str, Field(description='Document path. Paths starting with "content/" are MCP-owned (project-relative). All others are workspace-relative (e.g. "pypto-3.0-notes/arch.md"). Use list_knowledge_topics() to discover registered paths.')],
        max_chars: Annotated[int, Field(description="Maximum characters to return (500–50000)", ge=500, le=50000)] = 12000,
        section: Annotated[str, Field(description='Extract a specific markdown section by exact heading text (case-sensitive). Leave empty to read from the top. Use read_doc with a bad section name to see the TOC.')] = "",
    ) -> dict[str, Any]:
        """Read a workspace document with tier labeling. Optional section extracts a markdown heading."""
        return read_doc_payload(path, max_chars, section)

    @mcp.tool()
    def explain_abstraction(
        name: Annotated[str, Field(description='Abstraction name or alias, e.g. "AIC", "tmov", "TMOV". Use search_abstractions() to discover names.')],
        layer: Annotated[str, Field(description='Optional card layer or framework prefix, e.g. "ptoas", "pto-isa/instruction", "simpler/scheduler". Required when the same folded name exists in more than one layer.')] = "",
    ) -> dict[str, Any]:
        """Explain a stack abstraction. If the name matches several layers, returns candidates instead of picking one."""
        return explain_abstraction_impl(name, layer)

    @mcp.tool()
    def search_abstractions(
        query: Annotated[str, Field(description="Keyword to search across abstraction names, layers, kinds, tags, and related fields")],
        max_results: Annotated[int, Field(description="Maximum results to return (1–100)", ge=1, le=100)] = 20,
        fields: Annotated[str, Field(description='"summary" returns name+layer+one_liner; "full" adds tags, arch_families, repos')] = "summary",
        layer: Annotated[str, Field(description='Optional card layer or framework prefix, e.g. "ptoas", "simpler", "pypto/passes". Results stay grouped by layer.')] = "",
    ) -> dict[str, Any]:
        """Search the abstraction index by keyword. Results are ranked by relevance and grouped by layer."""
        return search_abstractions_impl(query, max_results, fields, layer)

    @mcp.tool()
    def layer_guide(
        layer: Annotated[str, Field(description='Framework layer: "pypto", "ptoas", "pto-isa", "simpler", "pypto-lib", or "all".')],
        topic: Annotated[str, Field(description='Optional path substring to summarize up to 15 docs, e.g. "scheduler" or "models".')] = "",
    ) -> dict[str, Any]:
        """Docs, skills, and rules for one framework layer, read live from that repo."""
        from mcp_hwnative_sys.layer_guide import layer_guide_impl

        return layer_guide_impl(layer, topic)

    @mcp.tool()
    def explain_scheduler(
        name: Annotated[str, Field(description='Scheduler level, engine, or implementation, e.g. "L3", "orchestrator", "hierarchical", "a2a3_host_build_graph".')],
    ) -> dict[str, Any]:
        """Explain a simpler scheduler level (L0–L6), engine, or concrete implementation tree."""
        from mcp_hwnative_sys.scheduler import explain_scheduler_impl

        return explain_scheduler_impl(name)

    @mcp.tool()
    def list_workloads(
        name: Annotated[str, Field(description='Optional model directory name, e.g. "deepseek_v4_1_flash". Empty lists every pypto-lib workload.')] = "",
    ) -> dict[str, Any]:
        """List pypto-lib model workloads, or one model's kernels split into prefill and decode."""
        from mcp_hwnative_sys.workloads import list_workloads_impl

        return list_workloads_impl(name)

    @mcp.tool()
    def explain_task_queue() -> dict[str, Any]:
        """Read-only task-submit queue guide: which hosts require it, how to join, and the failure rules. Does not submit a job."""
        from mcp_hwnative_sys.task_queue import explain_task_queue_impl

        return explain_task_queue_impl()

    @mcp.tool()
    def search_tracker(
        query: Annotated[str, Field(description='GitHub search query, e.g. "TMOV layout" or "is:issue label:bug".')],
        repo: Annotated[str, Field(description='Comma-separated repos. Default "PTOAS,pto-isa". Also pypto, simpler, pypto-lib, alias ptoas, or all.')] = "PTOAS,pto-isa",
        kind: Annotated[str, Field(description='"issues", "prs", or "both".')] = "both",
        state: Annotated[str, Field(description='"open", "closed", "merged", or "all". merged is pull requests only.')] = "open",
        max_results: Annotated[int, Field(description="Maximum hits (1–50)", ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """Search open, closed, and merged GitHub issues and PRs. Read-only."""
        from mcp_hwnative_sys.tracker import search_tracker_impl

        return search_tracker_impl(query, repo, kind, state, max_results)

    @mcp.tool()
    def explain_pass(
        name: Annotated[str, Field(description="Pass name from the Default pipeline, e.g. LowerCompositeOps. Case-insensitive fallback is applied.")],
    ) -> dict[str, Any]:
        """Explain a pass in the Default pipeline: order, phase, neighbors, verify tasks."""
        from mcp_hwnative_sys.passes_index import explain_pass_impl

        return explain_pass_impl(name)

    @mcp.tool()
    def program_status() -> dict[str, Any]:
        """Structured PR/plan status from status_prs.md (open PRs, blockers, plan cross-index)."""
        from mcp_hwnative_sys.program_status import program_status_impl

        return program_status_impl()

    @mcp.tool()
    def collective_status(
        op: Annotated[str, Field(description='Optional collective op filter, e.g. "AllReduce" or "All-to-All" (substring match).')] = "",
        axis: Annotated[str, Field(description='Optional feature axis filter, e.g. "Dynamic NR" or "Simplex native kernel" (substring match).')] = "",
    ) -> dict[str, Any]:
        """Collective-comm feature parity status (merged/planned/gap) from the parity matrix in
        pypto-3.0-notes/distributed/current_status.md. Read-only -- never writes to the source doc."""
        from mcp_hwnative_sys.collective_status import collective_status_impl

        return collective_status_impl(op, axis)

    @mcp.tool()
    def verify_ladder(
        changed_paths: Annotated[list[str], Field(description='List of changed file paths (workspace-relative or repo-prefixed), e.g. ["pypto/src/codegen/pto/foo.cc", "simpler/src/common/comm/bar.cc"]. Used to derive minimal verify task set.')],
    ) -> dict[str, Any]:
        """Suggest minimal verify tasks for a set of changed file paths.

        Returns ``static_checks`` (e.g. ``["clang-tidy"]``) when a changed path
        is a C/C++ file in a C++ repo — run those before the pytest tasks
        (see ``tools/clang_tidy_workflow``).
        """
        from mcp_hwnative_sys.verify_ladder import verify_ladder_impl

        return verify_ladder_impl(changed_paths)

    @mcp.tool()
    def find_generated_artifacts(
        repo: Annotated[str, Field(description='Optional repository name (e.g. "pypto", "pypto-lib") to scope the search. Empty searches every repo\'s artifact roots.')] = "",
        kind: Annotated[str, Field(description="Optional artifact kind filter, e.g. passes_dump, pto_mlir, kernel_aic_cpp, orchestration_cpp, dfx_outputs")] = "",
        program_hint: Annotated[str, Field(description='Optional substring of the output path (e.g. a kernel or program name) to filter on.')] = "",
        max_results: Annotated[int, Field(description="Maximum results to return (1–1000)", ge=1, le=1000)] = 300,
    ) -> dict[str, Any]:
        """Locate generated-code artifacts across the workspace: pass dumps, .pto MLIR, kernel/orchestration C++, dfx outputs.

        Scans each repo's build_output/outputs/build roots (read-only) and
        classifies what it finds. Combine with the debug/codegen-inspection
        resource to know which stage each artifact belongs to."""
        from mcp_hwnative_sys.artifacts import find_generated_artifacts_impl

        return find_generated_artifacts_impl(repo=repo, kind=kind, program_hint=program_hint, max_results=max_results)

    @mcp.tool()
    def list_skills(
        repo: Annotated[str, Field(description='Optional repository/plugin name to scope the listing (e.g. "pypto", "simpler", "pypto-user"). Empty lists every repo\'s skills.')] = "",
    ) -> dict[str, Any]:
        """List the agent-skill corpus per repo (pypto, pypto-lib, simpler, PTOAS, pto-isa, pypto-* plugins, pypto-tooling)."""
        from mcp_hwnative_sys.skills import list_skills_impl

        return list_skills_impl(repo)

    @mcp.tool()
    def find_skill(
        query: Annotated[str, Field(description='Keyword(s) to match across skill names and descriptions, e.g. "compare codegen", "ir trace", "profile"')],
        repo: Annotated[str, Field(description='Optional repo to scope the search (e.g. "simpler"). Empty searches all repos.')] = "",
    ) -> dict[str, Any]:
        """Find the agent skill that matches a task across all repos' skill corpus."""
        from mcp_hwnative_sys.skills import find_skill_impl

        return find_skill_impl(query, repo)

    @mcp.tool()
    def summarize_profile(
        run_dir: Annotated[str, Field(description="Path to a profiling campaign directory containing results.json. Accepts workspace-relative or absolute paths.")],
    ) -> dict[str, Any]:
        """Summarize a pypto-profiling campaign directory (results.json, anomalies)."""
        from mcp_hwnative_sys.profiling_summarize import summarize_profile_impl

        return summarize_profile_impl(run_dir)

    @mcp.tool()
    def trace_contract(
        symbol_or_path: Annotated[str, Field(description='Symbol name or path to trace through the stack (e.g. "LowerHostTensorCollectives", "pypto/src/codegen/distributed/foo.cc"). Matched against abstraction cards, path-prefix rules, and contract artifacts.')],
    ) -> dict[str, Any]:
        """Full cross-layer trace: stack location + contract triangle + cross-layer verify tasks + active-PR links.

        This is the enriched trace. Use trace_in_stack for a lightweight
        stack-location-only lookup."""
        from mcp_hwnative_sys.contract_trace import trace_contract_impl

        return trace_contract_impl(symbol_or_path)

    @mcp.tool()
    def find_entrypoints(
        repo: Annotated[str, Field(description='Repository name from list_repositories(), e.g. "pypto", "simpler"')],
        area: Annotated[str, Field(description='Optional sub-area key within the repo, e.g. "codegen_orch". Leave empty to list all areas for the repo.')] = "",
    ) -> dict[str, Any]:
        """Find code entrypoints for a repo and optional area (e.g. pypto, codegen_orch)."""
        return find_entrypoints_impl(repo, area)

    @mcp.tool()
    def trace_in_stack(
        symbol_or_path: Annotated[str, Field(description='Symbol name or file path to locate in the pypto→PTOAS→pto-isa→simpler stack. Path prefix matching is used for file paths; abstraction card matching for concept names.')],
    ) -> dict[str, Any]:
        """Lightweight stack location: matched abstraction card or path-prefix pipeline stage only.

        No contract artifacts or PR links. Use trace_contract for the enriched
        cross-layer trace."""
        return trace_in_stack_impl(symbol_or_path)

    @mcp.tool()
    def knowledge_health() -> dict[str, Any]:
        """Check knowledge config health: missing paths, stale enriched docs, Ascend corpus, index build time."""
        return knowledge_health_impl()

    @mcp.tool()
    def ascend_env_check() -> dict[str, Any]:
        """Read-only Ascend/CANN environment check: devices, HCCL preload, Docker hints."""
        from mcp_hwnative_sys.ascend_env import ascend_env_check_impl

        return ascend_env_check_impl()

    @mcp.tool()
    def generate_verify_handoff(
        repo: Annotated[str, Field(description='Repository name to verify, e.g. "pypto"')],
        branch: Annotated[str, Field(description="Branch name to check out on the NPU host")],
        sha: Annotated[str, Field(description='Git SHA to record in the handoff. Leave empty to use a placeholder (fill after checkout with git rev-parse HEAD).')] = "",
        task_type: Annotated[str, Field(description='Route key for developer_verify_tasks. Default "npu_verify_handoff" covers the standard NPU gate.')] = "npu_verify_handoff",
        device_ids: Annotated[str, Field(description='Comma-separated NPU device IDs to pass to pytest (e.g. "0,1")')] = "0,1",
        platform: Annotated[str, Field(description='Target Ascend platform family for test flags, e.g. "a2a3" (Ascend910B) or "a3" (Ascend910C)')] = "a2a3",
        fork_remote: Annotated[str, Field(description="Git remote name on the NPU host that has the branch to verify")] = "fork-gbisbas",
    ) -> dict[str, Any]:
        """Generate markdown handoff for developer NPU verification in a container."""
        from mcp_hwnative_sys.handoff import generate_verify_handoff_impl

        return generate_verify_handoff_impl(
            repo=repo,
            branch=branch,
            sha=sha,
            task_type=task_type,
            device_ids=device_ids,
            platform=platform,
            fork_remote=fork_remote,
        )

    @mcp.prompt(title="Start full-stack compiler work")
    def start_compiler_work(area: str = "stack_overview") -> str:
        return f"""You are working on the hw-native-sys compiler stack (Ascend NPUs): pypto → PTOAS → pto-isa → simpler, with pypto-lib as the model/harness layer.

## Workflow — run these tools in order

0. layer_guide for the framework layer you are touching (pypto, ptoas, pto-isa, simpler, or pypto-lib) so you see that layer's docs, skills, and rules before reading further.

1. Orient (one call):
   bootstrap_session(task_type="{area}", detail="<symbol or feature you are touching>")
   It returns read_plan (docs in priority order), abstraction_seeds, program_hints,
   and health_summary. Follow read_plan; for large notes use read_doc(path, section=...)
   instead of reading whole files.

2. Pin concepts before writing code:
   - search_abstractions("<keyword>") to discover canonical names
   - explain_abstraction("<name>") for an IR node / pass / ISA instruction / hardware concept
   - explain_pass("<PassName>") for pipeline order, phase, neighbors, and verify tasks
   - trace_contract("<symbol or path>") for cross-layer contract and active PR blockers

3. Implement. Keep changes scoped to the requested area; do not touch unrelated layers.

4. Verify before claiming done:
   - verify_ladder(changed_paths=[...]) → minimal verify set
   - Run only agent_verify_tasks (sim-Docker UT). NEVER run developer_verify_tasks
     (NPU/hardware-gated) — those are for the human developer.

## Gates
- Agent gate: sim Docker UT (run_task auto-redirects when no NPU is reachable).
- Developer gate: NPU ST via generate_verify_handoff — do not run it yourself.
- Push to fork-gbisbas only; never `gh pr create`.

## Stop when
- read_plan points at docs you already read this session (do not re-read them).
- verify_ladder returns developer_only tasks → stop and hand off, do not run."""

    @mcp.prompt(title="Start distributed / large-scale work")
    def start_distributed_work(focus: str = "collectives") -> str:
        focus_route = {
            "collectives": "distributed_collectives",
            "host_collectives": "host_collectives_program",
            "codegen": "distributed_codegen",
            "runtime": "distributed_runtime",
            "inference": "large_model_inference",
        }.get(focus, "distributed")

        return f"""You are working on distributed / large-scale training or inference on Ascend NPUs.

## Workflow — run these tools in order

1. bootstrap_session(task_type="{focus_route}", detail="<op or symbol>")
2. program_status → open PRs + blockers; collective_status(op=..., axis=...) for parity gaps
3. trace_contract("<symbol>") for cross-layer verify (e.g. LowerHostTensorCollectives, pld.tensor.*)
4. Implement.
5. verify_ladder(changed_paths=[...]) → run agent_verify_tasks only.

## Context to read first
- Host collectives: hw-native-sys://notes/host_collectives; sim known failures / limits: hw-native-sys://agent/distributed_work_policy
- Collectives parity: hw-native-sys://notes/stack_availability

## Gates
- Agent gate: sim Docker UT. Developer gate: NPU ST. Push to fork-gbisbas only.

## Stop when
- A required task is developer_only → stop and generate_verify_handoff, do not run it."""

    @mcp.prompt(title="Start Ascend architecture / NPU work")
    def start_ascend_work(focus: str = "arch") -> str:
        focus_route = {
            "arch": "ascend_arch",
            "tuning": "npu_tuning",
            "hccl": "ascend_runtime",
            "runtime": "ascend_runtime",
            "verify": "npu_verify_handoff",
        }.get(focus, "ascend_arch")

        return f"""You are working on Huawei Ascend NPU architecture, tuning, or distributed runtime.

## Workflow — run these tools in order

1. bootstrap_session(task_type="{focus_route}")
2. search_abstractions("<concept>") then explain_abstraction("<name>")
   (AIC, AIV, HCCLWindow, Ascend910B, etc.)
3. ascend_env_check on NPU hosts — read-only diagnosis (devices, CANN_HOME, LD_PRELOAD)
4. generate_verify_handoff(repo, branch, platform, device_ids) for the developer to run NPU verify

## Gates
- Canonical docs are authoritative; enriched notes are secondary.
- Agent never runs NPU tests — always hand off via generate_verify_handoff.

## Stop when
- A task requires real NPUs → hand off; do not run it yourself."""

    @mcp.prompt(title="Start NPU container verification (developer gate)")
    def start_npu_verify() -> str:
        return """You are verifying pypto/simpler changes on real Ascend NPUs (developer gate).

Workflow:
1. Call explain_task_queue — queue hosts, join, and the task-submit rules. Do not run the job.
2. Call ascend_env_check — confirm devices, CANN_HOME
3. Read hw-native-sys://ascend/hccl_container_checklist
4. Call generate_verify_handoff with repo, branch, platform, device_ids
5. The developer checks out the branch and runs the handoff's task-submit commands.
   Put LD_PRELOAD inside --run, never in the client shell. .13 and sim images stay unqueued.
6. Record git rev-parse HEAD; do not open upstream PR unless explicitly asked"""

    @mcp.prompt(title="Finish work — verify and hand off")
    def finish_work() -> str:
        return """You are finishing a coding task and must confirm verification before handoff.

## Closing loop

1. Collect changed paths (git status / git diff).
2. verify_ladder(changed_paths=[...]) → minimal verify set.
3. Run agent_verify_tasks only; skip any developer_only task.
4. If a C++ file changed, run clang-tidy on the changed files first (see static_checks
   and the tools/clang_tidy_workflow resource).
5. If any task needs NPU hardware, call generate_verify_handoff(repo, branch, sha, ...)
   and hand off — do not run it.

## Record for handoff
- Branch name and `git rev-parse HEAD`.
- Do not open a PR (gh pr create) unless explicitly asked.

## Stop when
- All agent_verify_tasks pass and the NPU-gated remainder is captured in a handoff."""

    @mcp.prompt(title="Debug by inspecting generated code")
    def debug_codegen_work(focus: str = "passes") -> str:
        focus_hint = {
            "passes": "find_generated_artifacts(kind='passes_dump')",
            "pto": "find_generated_artifacts(kind='pto_mlir')",
            "kernel": "find_generated_artifacts(kind='kernel_aic_cpp' or 'kernel_aiv_cpp')",
            "orch": "find_generated_artifacts(kind='orchestration_cpp')",
            "runtime": "find_generated_artifacts(kind='dfx_outputs')",
        }.get(focus, "find_generated_artifacts()")
        return f"""You are debugging a compile / lowering / codegen bug by inspecting generated code at each pipeline stage.

## Workflow — run these tools in order

1. Orient on the stages and the switches that produce each artifact:
   layer_guide for the owning framework layer (ptoas, pto-isa, pypto, or simpler)
   route_task(task_type="debug_codegen", detail="<symbol or symptom>")
   explain_abstraction("<name>", layer="<card layer>") when the same name exists in more than one layer
   search_tracker("<symptom or op>", repo="<owning repo>", state="merged") then state="open"
   then read hw-native-sys://debug/codegen-inspection (per-stage: artifact -> flag/API -> output path -> inspection tool).

2. Locate the real artifacts on disk (read-only):
   {focus_hint}
   When several runs exist, pick the entry with the newest `modified` timestamp.
   If no artifacts exist yet, produce them: pass dumps need dump_passes=True /
   PassDumpLevel.EXPLICIT; ptoas dumps need dump_ptoas_passes=True; to isolate
   pypto IR->MLIR from ptoas regressions, recompile with skip_ptoas=True.

3. Inspect the stage you suspect:
   - read_doc / read_file on the dumped snapshot (pass dumps are Python-IR text,
     .pto files are MLIR text).
   - explain_pass / explain_abstraction to pin which pass/backend owns the stage.
   - For a self-contained HTML lowering trace: find_skill("ir trace") -> generate-ir-trace.
   - To diff generated code between branches: find_skill("compare codegen") -> compare-codegen.

4. Identify the root cause, fix the DSL/pass/codegen change in the owning repo,
   then verify: verify_ladder(changed_paths=[...]) and run agent_verify_tasks only.

## Gates
- Never run developer_only / NPU tasks — hand off via generate_verify_handoff.
- Push to fork-gbisbas only; never `gh pr create`.

## Stop when
- You have a causal chain from DSL source down to the failing artifact (see the
  explaining-problems discipline), not just an error message."""
