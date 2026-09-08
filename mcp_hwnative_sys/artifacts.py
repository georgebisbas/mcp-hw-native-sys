"""Locate generated-code artifacts across the workspace.

Each repo keeps its compiled/codegen output under a small set of roots
(``build_output/``, ``outputs/``, and for pypto also ``build/``). This module
walks those roots and classifies what it finds — pass dumps, ``.pto`` MLIR,
kernel/orchestration C++, dfx outputs — so an agent debugging a lowering or
codegen bug can jump straight to the artifact for the stage it suspects.

Read-only with respect to the sibling repos: never writes, never shells out.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from mcp_hwnative_sys.paths import load_repos_config, workspace_root

# Classified artifact kinds (values accepted by the ``kind`` filter).
KINDS = (
    "passes_dump",      # dir: IR snapshot after each pass (NN_after_<Pass>.py)
    "ptoas_passes",     # dir: full-module IR after each ptoas pass
    "pto_mlir",         # file: raw .pto MLIR text
    "kernel_aic_cpp",   # file: cube kernel C++ wrapper (ptoas output)
    "kernel_aiv_cpp",   # file: vector kernel C++ wrapper (ptoas output)
    "orchestration_cpp",  # file: generated AICPU orchestration C++
    "runtime_so",       # file: compiled orchestration/runtime .so
    "kernel_bin",       # file: device kernel binary
    "kernel_config",    # file: kernel_config.py registry
    "dfx_outputs",      # dir: runtime DFX artifacts (swimlanes, args dumps)
    "report",           # dir: compile/memory/scheduling reports
    "args_dump",        # file: --dump-args runtime capture
)

_DIR_KINDS = {
    "passes_dump": "passes_dump",
    "ptoas_passes": "ptoas_passes",
    "dfx_outputs": "dfx_outputs",
    "report": "report",
}

# Subtree names never worth descending into when hunting codegen artifacts.
_SKIP_DIRS = {
    ".git", ".venv", "__pycache__", ".pytest_cache", "_skbuild", ".mypy_cache",
    "node_modules", "CMakeFiles", "_deps", "cmake-build-debug", "dist", "build",
}

# Candidate artifact roots per repo, relative to the repo root. Repos not
# listed get the generic pair; only roots that actually exist are scanned.
_ROOT_CANDIDATES: dict[str, tuple[str, ...]] = {
    "pypto": ("build_output", "build"),
    "pypto-lib": ("build_output",),
    "simpler": ("outputs",),
    "pypto-profiling": ("results",),
    "PTOAS": ("build_output", "build"),
    "pto-isa": ("build_output",),
}
_GENERIC_ROOTS = ("build_output", "outputs")


def _repo_roots() -> list[tuple[str, Path]]:
    """Return (repo_name, existing artifact root) pairs across the workspace."""
    config = load_repos_config()
    repos = config.get("repositories", {})
    ws = workspace_root()
    scanned: list[tuple[str, Path]] = []
    for name, rel in sorted(repos.items()):
        base = ws / rel
        if not base.is_dir():
            continue
        candidates = _ROOT_CANDIDATES.get(name, _GENERIC_ROOTS) or _GENERIC_ROOTS
        for root_name in candidates:
            candidate = base / root_name
            if candidate.is_dir():
                scanned.append((name, candidate))
    return scanned


def _classify_file(rel_parts: list[str]) -> str | None:
    basename = rel_parts[-1]
    parent = "/".join(rel_parts[:-1])
    if basename.endswith(".pto"):
        return "pto_mlir"
    if basename.endswith(".cpp"):
        if "kernels/aic" in parent:
            return "kernel_aic_cpp"
        if "kernels/aiv" in parent:
            return "kernel_aiv_cpp"
        if "orchestration" in parent:
            return "orchestration_cpp"
        return None
    if basename == "kernel_config.py":
        return "kernel_config"
    if basename.endswith(".so"):
        return "runtime_so"
    if basename.endswith(".bin"):
        return "kernel_bin"
    if basename.startswith("args_") and "dfx_outputs" in parent:
        return "args_dump"
    return None


def find_generated_artifacts_impl(
    repo: str = "",
    kind: str = "",
    program_hint: str = "",
    max_results: int = 300,
) -> dict[str, Any]:
    if kind and kind not in KINDS:
        raise ValueError(f"Unknown kind '{kind}'. Valid kinds: {', '.join(KINDS)}")

    roots = _repo_roots()
    if repo:
        roots = [(name, root) for name, root in roots if name == repo]
        if not roots:
            known = sorted({name for name, _ in _repo_roots()})
            raise ValueError(f"No artifact roots found for repo '{repo}'. Repos with roots: {', '.join(known) or 'none'}")

    hint = program_hint.strip().lower()
    results: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    roots_scanned: list[str] = []
    truncated = False
    max_nodes = 150_000

    for name, root in roots:
        roots_scanned.append(str(root))
        visited = 0
        for dirpath, dirnames, filenames in os.walk(root, topdown=True):
            visited += 1
            if visited > max_nodes or len(results) >= max_results:
                truncated = True
                break
            dirnames[:] = [
                d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")
            ]
            # Directory artifacts first (dirs named after a known kind).
            for dirname in list(dirnames):
                kind_name = _DIR_KINDS.get(dirname)
                if not kind_name:
                    continue
                if kind and kind_name != kind:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, dirname), workspace_root())
                if hint and hint not in rel.lower():
                    continue
                key = (name, kind_name, rel)
                if key not in seen:
                    seen.add(key)
                    results.append({"repo": name, "kind": kind_name, "path": rel})
                    if len(results) >= max_results:
                        break
            if len(results) >= max_results:
                break
            for filename in filenames:
                rel_parts = os.path.relpath(os.path.join(dirpath, filename), workspace_root()).split(os.sep)
                kind_name = _classify_file(rel_parts)
                if not kind_name:
                    continue
                rel = "/".join(rel_parts)
                key = (name, kind_name, rel)
                if key in seen:
                    continue
                seen.add(key)
                if kind and kind_name != kind:
                    continue
                if hint and hint not in rel.lower():
                    continue
                results.append({"repo": name, "kind": kind_name, "path": rel})
                if len(results) >= max_results:
                    truncated = True
                    break

    return {
        "count": len(results),
        "results": results,
        "roots_scanned": roots_scanned,
        "truncated": truncated,
        "note": (
            "Artifacts are read live from build_output/outputs/build roots. "
            "For branch diffs or pass-dump-to-HTML conversion see skills "
            "compare-codegen / generate-ir-trace."
        ),
    }
