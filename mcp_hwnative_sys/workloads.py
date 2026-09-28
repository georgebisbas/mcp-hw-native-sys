"""pypto-lib workload catalog."""

from __future__ import annotations

import json
from typing import Any

from mcp_hwnative_sys.paths import project_root, workspace_root

_FILE_CAP = 40


def workloads_index_path():
    return project_root() / "config" / "pypto_lib_workloads.json"


def load_workloads_index() -> dict[str, Any]:
    path = workloads_index_path()
    if not path.exists():
        return {
            "warning": f"Missing {path.name}. Run tools/build_pypto_lib_workloads.py.",
            "workloads": [],
            "cards": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


def workload_cards() -> dict[str, Any]:
    cards = load_workloads_index().get("cards", {})
    return cards if isinstance(cards, dict) else {}


def _phase(name: str) -> str:
    lower = name.lower()
    if lower.startswith("prefill"):
        return "prefill"
    if lower.startswith("decode"):
        return "decode"
    return "other"


def list_workloads_impl(name: str = "") -> dict[str, Any]:
    index = load_workloads_index()
    workloads: list[dict[str, Any]] = list(index.get("workloads", []))
    if index.get("warning") and not workloads:
        raise ValueError(index["warning"])

    needle = name.strip()
    if not needle:
        compact = [
            {
                "name": item["name"],
                "summary": item.get("summary", ""),
                "serving": item.get("serving", ""),
                "documented": item.get("documented", False),
                "doc": item.get("doc", ""),
            }
            for item in workloads
        ]
        return {"count": len(compact), "workloads": compact}

    matches = [item for item in workloads if needle.lower() in item["name"].lower()]
    if not matches:
        available = ", ".join(item["name"] for item in workloads[:12])
        raise ValueError(f"Unknown workload '{name}'. Examples: {available}")

    detailed: list[dict[str, Any]] = []
    root = workspace_root()
    for item in matches:
        kernels = list(item.get("kernels") or [])
        if not kernels:
            model_dir = root / item.get("directory", "")
            if model_dir.is_dir():
                for path in sorted(model_dir.glob("*.py")):
                    if path.name.endswith("_draft.py"):
                        continue
                    kernels.append({"name": path.name, "phase": _phase(path.name)})
                    if len(kernels) >= _FILE_CAP:
                        break
        detailed.append({**item, "kernels": kernels[:_FILE_CAP]})
    return {"count": len(detailed), "workloads": detailed}
