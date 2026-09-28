#!/usr/bin/env python3
"""Generate the pypto-lib workload catalog from docs/models/index.md and models/.

Writes config/pypto_lib_workloads.json. Does not touch abstractions.json.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"

sys.path.insert(0, str(PROJECT_ROOT))

from mcp_hwnative_sys.paths import workspace_root  # noqa: E402

_ROW_RE = re.compile(
    r"^\|\s*\[([^\]]+)\]\(([^)]+)\)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|",
    re.MULTILINE,
)
_FILE_CAP = 200


def _phase(name: str) -> str:
    lower = name.lower()
    if lower.startswith("prefill"):
        return "prefill"
    if lower.startswith("decode"):
        return "decode"
    return "other"


def _kernel_files(model_dir: Path) -> list[dict[str, str]]:
    files: list[dict[str, str]] = []
    if not model_dir.is_dir():
        return files
    for path in sorted(model_dir.glob("*.py")):
        if path.name.endswith("_draft.py"):
            continue
        files.append({"name": path.name, "phase": _phase(path.name)})
        if len(files) >= _FILE_CAP:
            break
    return files


def parse_index_table(text: str) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    for match in _ROW_RE.finditer(text):
        name = match.group(1).strip()
        doc = match.group(2).strip()
        rows[name] = {
            "summary": match.group(3).strip(),
            "serving": match.group(4).strip(),
            "doc": f"pypto-lib/docs/models/{doc}",
            "documented": True,
        }
    return rows


def build_workloads(root: Path) -> dict:
    index_path = root / "pypto-lib/docs/models/index.md"
    documented = parse_index_table(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    models_root = root / "pypto-lib/models"
    names = set(documented)
    if models_root.is_dir():
        names.update(path.name for path in models_root.iterdir() if path.is_dir())

    workloads: list[dict] = []
    cards: dict[str, dict] = {}
    for name in sorted(names):
        meta = documented.get(name, {"summary": "", "serving": "", "doc": "", "documented": False})
        kernels = _kernel_files(models_root / name)
        entry = {
            "name": name,
            "layer": "pypto-lib/workload",
            "directory": f"pypto-lib/models/{name}",
            "summary": meta.get("summary", ""),
            "serving": meta.get("serving", ""),
            "doc": meta.get("doc", ""),
            "documented": bool(meta.get("documented")),
            "kernels": kernels,
        }
        workloads.append(entry)
        cards[f"pypto-lib.workload.{name}"] = {
            "layer": "pypto-lib/workload",
            "kind": "workload",
            "repos": ["pypto-lib"],
            "paths": [entry["directory"]],
            "docs_canonical": [entry["doc"]] if entry["doc"] else [],
            "one_liner": entry["summary"] or name,
            "source": "generated",
        }
    return {"workloads": workloads, "cards": cards}


def main() -> None:
    payload = build_workloads(workspace_root())
    out = CONFIG_DIR / "pypto_lib_workloads.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(payload['workloads'])} workloads)")


if __name__ == "__main__":
    main()
