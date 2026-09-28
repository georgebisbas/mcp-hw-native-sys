"""Task-submit guide and NPU handoff wrapping."""

from __future__ import annotations

from mcp_hwnative_sys.handoff import generate_verify_handoff_impl, wrap_task_submit
from mcp_hwnative_sys.task_queue import explain_task_queue_impl


def test_explain_task_queue_names_queued_and_unqueued_hosts():
    guide = explain_task_queue_impl()
    by_host = {item["host"]: item["queue"] for item in guide["hosts"]}
    assert by_host["192.168.150.11"] == "required"
    assert by_host["192.168.150.12"] == "required"
    assert by_host["192.168.150.13"] == "absent"
    assert guide["sim_images"] == "unqueued"
    assert guide["agent_runs_npu"] is False


def test_wrap_uses_task_device_inside_run():
    command = wrap_task_submit("pytest tests/st/distributed/test_l3.py -v --device=0,1", "0,1")
    assert command.startswith("task-submit --device auto")
    assert "--device-num 2" in command
    assert "$TASK_DEVICE" in command
    assert "export LD_PRELOAD" not in command
    assert "LD_PRELOAD=" in command


def test_handoff_does_not_export_preload_in_the_client_shell():
    result = generate_verify_handoff_impl("pypto", "feat/example", device_ids="0,1")
    markdown = result["markdown"]
    assert "task-submit --device auto" in markdown
    assert "$TASK_DEVICE" in markdown
    assert "export LD_PRELOAD" not in markdown
