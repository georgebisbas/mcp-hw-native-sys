"""Tests for the ``testing`` block returned by bootstrap_session."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mcp_hwnative_sys.bootstrap import bootstrap_session_impl

_ROUTES = json.loads(
    (Path(__file__).resolve().parents[1] / "config" / "knowledge.json").read_text()
)["routes"]


def _testing(task_type: str) -> dict:
    return bootstrap_session_impl(task_type, include_health=False)["testing"]


def test_pass_change_uses_pypto_sim_image():
    testing = _testing("pass_change")
    task = testing["agent_verify_tasks"][0]
    assert task["task"] == "pypto:unit_tests_fast"
    assert task["image"] == "pypto3-hw-native-sys:sim"
    assert task["command"].startswith("pytest")
    assert testing["developer_verify_tasks"] == []


def test_distributed_collectives_separates_developer_gate():
    testing = _testing("distributed_collectives")
    assert [t["task"] for t in testing["agent_verify_tasks"]] == [
        "pypto-docker:host_collectives_ut_sim"
    ]
    dev = testing["developer_verify_tasks"][0]
    assert dev["developer_only"] is True
    assert dev["image"] == "pypto3-hw-native-sys:cann9"


def test_distributed_runtime_uses_simpler_sim_image():
    task = _testing("distributed_runtime")["agent_verify_tasks"][0]
    assert task["task"] == "simpler:test_sim"
    assert task["image"] == "simpler-hw-native-sys:sim"


def test_pypto_lib_uses_its_sim_image():
    images = _testing("pypto_lib")["images"]
    assert images["pypto-lib"]["sim_image"] == "pypto-lib-hw-native-sys:sim"


def test_docs_and_rules_always_present():
    testing = _testing("stack_overview")
    assert "tools/test_standards" in testing["docs"]
    assert testing["rules"]
    assert testing["agent_verify_tasks"] == []


def test_session_hint_points_at_testing_block():
    result = bootstrap_session_impl("ir_change", include_health=False)
    assert "testing" in result["session_hint"]


@pytest.mark.parametrize("task_type", sorted(_ROUTES))
def test_every_verify_task_resolves(task_type):
    """No route may point at a verify task that is missing from repos.json."""
    testing = _testing(task_type)
    for task in testing["agent_verify_tasks"] + testing["developer_verify_tasks"]:
        assert task.get("found", True), f"{task_type}: unknown task {task['task']}"
