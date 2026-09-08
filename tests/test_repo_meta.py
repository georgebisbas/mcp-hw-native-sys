"""Golden test: every registered repo's canonical_docs / agent_rules must exist.

repos.json repository_meta feeds list_repositories, which agents use to pick
canonical docs and agent rules. A path that no longer exists on disk (doc moved,
CLAUDE.md relocated) silently sends the agent to a 404 — this test catches it.
"""

from __future__ import annotations

from mcp_hwnative_sys.paths import load_repos_config, workspace_root


def test_registered_repo_meta_paths_exist():
    cfg = load_repos_config()
    meta = cfg.get("repository_meta", {})
    assert meta, "repository_meta is empty in config/repos.json"
    ws = workspace_root()
    missing: list[str] = []
    for name, entry in sorted(meta.items()):
        for key in ("canonical_docs", "agent_rules"):
            for rel in entry.get(key, []) or []:
                if not (ws / rel).exists():
                    missing.append(f"[{key}] {name}: {rel}")
    assert not missing, "repository_meta paths missing on disk:\n" + "\n".join(missing)


def test_repositories_and_meta_are_in_sync():
    cfg = load_repos_config()
    meta = set(cfg.get("repository_meta", {}))
    repos = set(cfg.get("repositories", {}))
    assert repos <= meta, f"repositories missing repository_meta: {sorted(repos - meta)}"
