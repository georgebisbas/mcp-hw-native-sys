#!/usr/bin/env python3
"""Generate the simpler scheduler catalog.

Scans directories named ``scheduler`` that contain ``scheduler.cpp`` or
``scheduler.h``, plus ``*completion_scheduler.h`` files. Levels L0–L6 and the
three engines are a short curated table; the docs are only checked for those
names, not scraped for queue prose.

Writes config/simpler_scheduler.json. Does not touch abstractions.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"

sys.path.insert(0, str(PROJECT_ROOT))

from mcp_hwnative_sys.paths import workspace_root  # noqa: E402

_DOCS = [
    "simpler/docs/hierarchical-level-runtime.md",
    "simpler/docs/scheduler.md",
]

_LEVELS = [
    {"id": "L0", "name": "core", "scope": "individual compute core (AIC/AIV), hardware-managed"},
    {"id": "L1", "name": "die", "scope": "chip die / L2 cache, hardware-managed; no Worker sits here"},
    {"id": "L2", "name": "chip", "scope": "one NPU chip; on-device boundary"},
    {"id": "L3", "name": "node", "scope": "single host machine"},
    {"id": "L4", "name": "pod", "scope": "pod of hosts"},
    {"id": "L5", "name": "supernode", "scope": "super-node"},
    {"id": "L6", "name": "cluster", "scope": "full cluster"},
]

_ENGINES = [
    {
        "name": "orchestrator",
        "one_liner": "Submits slots and infers dependencies; the only READY router is Orchestrator::enqueue_ready.",
        "paths": ["simpler/src/common/orchestrator/", "simpler/docs/orchestrator.md"],
    },
    {
        "name": "scheduler",
        "one_liner": "Single-threaded DAG executor: dispatches READY slots, handles completions, releases downstream dependencies.",
        "paths": ["simpler/src/common/hierarchical/scheduler.cpp", "simpler/docs/scheduler.md"],
    },
    {
        "name": "worker",
        "one_liner": "Endpoint execution for a hierarchical Worker, including the worker-thread pool.",
        "paths": ["simpler/src/common/worker/", "simpler/docs/worker-manager.md"],
    },
]


def _slug(rel: str) -> str:
    parts: list[str] = []
    for part in Path(rel).parts:
        if part in {"simpler", "src", "runtime", "scheduler", "scheduler.cpp", "scheduler.h"}:
            continue
        part = part.removesuffix(".h").removesuffix(".cpp")
        parts.append(part)
    slug = "_".join(parts) or "scheduler"
    return f"simpler.scheduler.{slug}"


_SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "site-packages"}


def _skipped(path: Path) -> bool:
    return any(part in _SKIP_PARTS for part in path.parts)


def scan_implementations(root: Path) -> list[dict]:
    simpler = root / "simpler"
    if not simpler.is_dir():
        return []
    found: list[dict] = []
    seen: set[str] = set()

    sources = [path for path in simpler.rglob("scheduler.cpp") if not _skipped(path)]
    sources += [
        path
        for path in simpler.rglob("scheduler.h")
        if not _skipped(path) and not (path.parent / "scheduler.cpp").is_file()
    ]
    for source in sorted(sources):
        rel = str(source.relative_to(root))
        if rel in seen:
            continue
        seen.add(rel)
        found.append(
            {
                "key": _slug(rel),
                "kind": "implementation",
                "path": rel,
                "one_liner": f"Scheduler implementation {rel}",
            }
        )

    for header in sorted(simpler.rglob("*completion_scheduler.h")):
        if _skipped(header):
            continue
        rel = str(header.relative_to(root))
        if rel in seen:
            continue
        seen.add(rel)
        found.append(
            {
                "key": _slug(rel),
                "kind": "completion",
                "path": rel,
                "one_liner": f"Completion scheduler {header.name}",
            }
        )
    return found


def _cards(implementations: list[dict]) -> dict[str, dict]:
    cards: dict[str, dict] = {}
    for level in _LEVELS:
        key = f"simpler.scheduler.{level['id']}"
        cards[key] = {
            "layer": "simpler/scheduler",
            "kind": "level",
            "repos": ["simpler"],
            "paths": ["simpler/docs/hierarchical-level-runtime.md"],
            "docs_canonical": ["simpler/docs/hierarchical-level-runtime.md"],
            "one_liner": f"{level['id']} {level['name']}: {level['scope']}",
            "source": "generated",
        }
    for engine in _ENGINES:
        key = f"simpler.scheduler.{engine['name']}"
        cards[key] = {
            "layer": "simpler/scheduler",
            "kind": "engine",
            "repos": ["simpler"],
            "paths": engine["paths"],
            "docs_canonical": _DOCS,
            "one_liner": engine["one_liner"],
            "source": "generated",
        }
    for impl in implementations:
        cards[impl["key"]] = {
            "layer": "simpler/scheduler",
            "kind": impl["kind"],
            "repos": ["simpler"],
            "paths": [impl["path"]],
            "docs_canonical": _DOCS,
            "one_liner": impl["one_liner"],
            "source": "generated",
        }
    return cards


def build_scheduler_index(root: Path) -> dict:
    implementations = scan_implementations(root)
    return {
        "levels": _LEVELS,
        "engines": _ENGINES,
        "implementations": implementations,
        "docs_canonical": _DOCS,
        "cards": _cards(implementations),
    }


def main() -> None:
    payload = build_scheduler_index(workspace_root())
    out = CONFIG_DIR / "simpler_scheduler.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['implementations'])} implementations)")


if __name__ == "__main__":
    main()
