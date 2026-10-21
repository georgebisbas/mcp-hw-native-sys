from __future__ import annotations

from typing import Any

from mcp_hwnative_sys.paths import load_repos_config


# Longer prefixes first for greedy matching.
_VERIFY_RULES: list[tuple[str, str, list[str]]] = [
    ("pypto/src/codegen/orchestration/", "pypto", ["pypto:codegen_tests", "pypto:unit_tests_fast"]),
    ("pypto/src/codegen/distributed/", "pypto", ["pypto:system_tests_sim", "pypto:codegen_tests"]),
    ("pypto/src/codegen/pto/", "pypto", ["pypto:codegen_tests"]),
    ("pypto/src/codegen/", "pypto", ["pypto:codegen_tests", "pypto:unit_tests_fast"]),
    ("pypto/src/ir/transforms/", "pypto", ["pypto:unit_tests_fast"]),
    ("pypto/src/ir/op/distributed/", "pypto", ["pypto:system_tests_sim"]),
    ("pypto/python/pypto/ir/", "pypto", ["pypto:unit_tests_fast"]),
    ("host_orch", "pypto", ["pypto-docker:host_collectives_ut_sim"]),
    ("LowerHostTensorCollectives", "pypto", ["pypto-docker:host_collectives_ut_sim"]),
    ("simpler/src/common/comm/", "simpler", ["simpler:test_sim"]),
    ("simpler/examples/l3/", "simpler", ["simpler:test_sim"]),
    ("simpler/src/", "simpler", ["simpler:test_ut_python"]),
    ("PTOAS/docs/", "PTOAS", []),
    ("PTOAS/ptodsl/", "PTOAS", ["PTOAS:ptodsl_ctest", "PTOAS:lit_tests"]),
    ("PTOAS/", "PTOAS", ["PTOAS:ir_smoke", "PTOAS:lit_tests"]),
    ("pto-isa/docs/", "pto-isa", []),
    ("pto-isa/tests/", "pto-isa", ["pto-isa:validate_testcase_names", "pto-isa:cpu_st_tests"]),
    ("pto-isa/", "pto-isa", ["pto-isa:validate_op_coverage", "pto-isa:cpu_st_tests"]),
    ("pypto-lib/", "pypto-lib", ["pypto-lib:tests_golden"]),
    ("pypto-profiling/", "pypto-profiling", []),
]

# C++ repos and file extensions: a changed C/C++ file in one of these repos
# requires a clang-tidy static check before commit (see tools/clang_tidy_workflow).
_CPP_REPO_PREFIXES: tuple[tuple[str, str], ...] = (
    ("pto-isa/", "pto-isa"),
    ("PTOAS/", "PTOAS"),
    ("pypto-lib/", "pypto-lib"),
    ("pypto/", "pypto"),
    ("simpler/", "simpler"),
)
_CPP_EXTENSIONS = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl")


def _needs_clang_tidy(path: str) -> bool:
    """True when ``path`` is a C/C++ file in a C++ repo (clang-tidy applies)."""
    return path.endswith(_CPP_EXTENSIONS) and any(
        path.startswith(prefix) for prefix, _ in _CPP_REPO_PREFIXES
    )


_DOC_EXTENSIONS = (".md", ".rst", ".txt")
_DOC_DIRS = ("docs/", "doc/")


# pypto-lib is excluded: model/kernel changes there are verified by the golden
# harness and must leave tests/ unchanged (see pypto-lib .claude/CLAUDE.md).
_TEST_EXPECTED_REPOS = frozenset({"pypto", "simpler", "PTOAS", "pto-isa"})


def _is_test_path(path: str) -> bool:
    """True for files under a ``tests/``/``test/`` dir or named like a test."""
    parts = path.split("/")
    name = parts[-1]
    return (
        "tests" in parts[:-1]
        or "test" in parts[:-1]
        or name.startswith("test_")
        or name.rsplit(".", 1)[0].endswith("_test")
    )


def _is_doc_path(path: str) -> bool:
    return path.endswith(_DOC_EXTENSIONS) or any(
        d in path for d in ("/" + x for x in _DOC_DIRS)
    ) or path.startswith(_DOC_DIRS)


def _test_presence(paths: list[str]) -> dict[str, Any]:
    """Flag per-repo production changes that ship without any test change."""
    by_repo: dict[str, dict[str, list[str]]] = {}
    for path in paths:
        repo = path.split("/", 1)[0]
        if repo not in _TEST_EXPECTED_REPOS:
            continue
        bucket = by_repo.setdefault(repo, {"production": [], "tests": []})
        if _is_test_path(path):
            bucket["tests"].append(path)
        elif not _is_doc_path(path):
            bucket["production"].append(path)

    warnings = [
        f"{repo}: {len(b['production'])} production file(s) changed with no test change. "
        "New features and bug fixes need tests (regression test for fixes); "
        "see tools/test_standards."
        for repo, b in by_repo.items()
        if b["production"] and not b["tests"]
    ]
    return {
        "production_files": [f for b in by_repo.values() for f in b["production"]],
        "test_files": [f for b in by_repo.values() for f in b["tests"]],
        "warnings": warnings,
    }


def verify_ladder_impl(changed_paths: list[str]) -> dict[str, Any]:
    if not changed_paths:
        raise ValueError("changed_paths cannot be empty")

    normalized = [p.replace("\\", "/").strip() for p in changed_paths if p.strip()]
    matched_rules: list[dict[str, Any]] = []
    task_keys: list[str] = []

    for path in normalized:
        for prefix, repo, tasks in _VERIFY_RULES:
            if prefix in path or path.startswith(prefix):
                matched_rules.append({"path": path, "prefix": prefix, "repo": repo, "tasks": tasks})
                task_keys.extend(tasks)
                break

    # Deduplicate while preserving order
    seen: set[str] = set()
    ordered_tasks: list[str] = []
    for key in task_keys:
        if key in seen:
            continue
        seen.add(key)
        ordered_tasks.append(key)

    raw_config = load_repos_config()
    task_config = raw_config.get("tasks", {})

    ladder: list[dict[str, Any]] = []
    for task_key in ordered_tasks:
        if ":" not in task_key:
            continue
        repo, task_name = task_key.split(":", 1)
        spec = task_config.get(repo, {}).get(task_name) or task_config.get("default", {}).get(task_name)
        if spec is None:
            ladder.append({"task": task_key, "found": False})
            continue
        if isinstance(spec, str):
            entry = {"task": task_key, "found": True, "category": "misc", "risk": "unknown"}
        else:
            entry = {
                "task": task_key,
                "found": True,
                "category": spec.get("category", "misc"),
                "risk": spec.get("risk", "unknown"),
                "duration_hint": spec.get("duration_hint"),
                "developer_only": spec.get("developer_only", False),
                "long_running": spec.get("long_running", False),
            }
        ladder.append(entry)

    needs_clang_tidy = any(_needs_clang_tidy(p) for p in normalized)
    note = (
        "Run agent_verify_tasks only; skip developer_only tasks unless explicitly asked. "
        "C++ changes require clang-tidy on the changed files first (see tools/clang_tidy_workflow)."
        if needs_clang_tidy
        else "Run agent_verify_tasks only; skip developer_only tasks unless explicitly asked."
    )

    return {
        "changed_paths": normalized,
        "matched_rules": matched_rules,
        "suggested_tasks": ordered_tasks,
        "ladder": ladder,
        "static_checks": ["clang-tidy"] if needs_clang_tidy else [],
        "test_presence": _test_presence(normalized),
        "note": note,
    }
