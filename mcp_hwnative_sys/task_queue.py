"""Read-only guide to the NPU task-submit queue.

The agent explains the queue. It does not submit jobs or edit the spool.
"""

from __future__ import annotations

from typing import Any

from mcp_hwnative_sys.doc_sections import extract_section
from mcp_hwnative_sys.paths import workspace_root

_DOCS = (
    "pypto-docker/TASK_QUEUE.md",
    "pypto-docker/TASK_QUEUE_hng-atlas02_admin-note.md",
    "pypto-docker/scripts/attach-taskqueue.sh",
    "pypto-3.0-notes/tools/npu-task-submit-runbook.md",
    "pypto-3.0-notes/tools/task-submit.md",
    "pypto-tooling/task-submit/task-submit.md",
)

_EXCERPT = 700


def explain_task_queue_impl() -> dict[str, Any]:
    root = workspace_root()
    docs = []
    for rel in _DOCS:
        path = root / rel
        docs.append({"path": rel, "exists": path.is_file()})

    pitfalls = ""
    queue_doc = root / "pypto-docker/TASK_QUEUE.md"
    if queue_doc.is_file():
        text = queue_doc.read_text(encoding="utf-8", errors="replace")
        section = extract_section(text, "Pitfalls") or ""
        pitfalls = section[:_EXCERPT]

    return {
        "agent_runs_npu": False,
        "hosts": [
            {"host": "192.168.150.11", "queue": "required", "note": "hng-atlas01; spool /var/lib/taskqueue"},
            {"host": "192.168.150.12", "queue": "required", "note": "confirm with task-submit --list"},
            {"host": "192.168.150.13", "queue": "absent", "note": "direct unqueued runs only"},
        ],
        "sim_images": "unqueued",
        "join": [
            "Bind-mount /var/lib/taskqueue at the same path inside the container.",
            "Run pypto-docker/scripts/attach-taskqueue.sh <container>.",
            "Confirm with task-submit --list.",
        ],
        "submit": (
            "task-submit --device auto --device-num N --max-time 3600 --timeout 0 "
            "--run 'COMMAND --device=$TASK_DEVICE'"
        ),
        "rules": [
            "Do not nest task-submit inside a submitted job.",
            "Reference $TASK_DEVICE inside --run so the client does not append --device.",
            "Put LD_PRELOAD only inside --run. Exporting it in the client shell kills HCCL jobs (exit 137).",
            "--max-time is the kill deadline (hard cap 3600s). --timeout only bounds how long the client waits.",
            "Do not start the broker.",
            "Do not run task-submit --clean on the shared volume.",
            "Do not rewrite /var/lib/taskqueue. The admin note is read-only context.",
            "Do not pick a card from npu-smi on a queue host. Use --device auto.",
        ],
        "docs": docs,
        "pitfalls_excerpt": pitfalls,
    }
