"""Golden tests for the MCP prompts and the bootstrap/route entrypoints.

These assert the exact tool-call sequences that agents rely on, so a
regression in the routing text (a renamed tool, a dropped gate, a removed
"stop when" clause) fails loudly instead of silently misguiding an agent.
"""

from __future__ import annotations

import asyncio

from mcp_hwnative_sys import knowledge
from mcp_hwnative_sys.server import mcp


def _prompt_text(name: str, arguments: dict | None = None) -> str:
    result = asyncio.run(mcp.get_prompt(name, arguments or {}))
    return "\n".join(m.content.text for m in result.messages)


def test_all_prompts_are_registered():
    names = asyncio.run(mcp.list_prompts())
    registered = {p.name for p in names}
    assert {
        "start_compiler_work",
        "start_distributed_work",
        "start_ascend_work",
        "start_npu_verify",
        "debug_codegen_work",
        "finish_work",
    } <= registered


def test_debug_codegen_prompt_sequences_the_inspection_flow():
    text = _prompt_text("debug_codegen_work", {"focus": "passes"})
    assert 'route_task(task_type="debug_codegen"' in text
    assert "debug/codegen-inspection" in text
    assert "find_generated_artifacts" in text
    assert "find_skill" in text
    assert "verify_ladder" in text
    assert "generate_verify_handoff" in text


def test_compiler_prompt_mentions_discovery_tools():
    text = _prompt_text("start_compiler_work", {"area": "pass_change"})
    assert "search_abstractions" in text
    assert "explain_abstraction" in text
    assert "explain_pass" in text
    assert "trace_contract" in text
    assert "bootstrap_session" in text


def test_compiler_prompt_interpolates_area():
    text = _prompt_text("start_compiler_work", {"area": "ir_change"})
    assert 'task_type="ir_change"' in text


def test_distributed_prompt_routes_host_collectives_focus():
    text = _prompt_text("start_distributed_work", {"focus": "host_collectives"})
    assert 'task_type="host_collectives_program"' in text


def test_ascend_prompt_mentions_hardware_concepts():
    text = _prompt_text("start_ascend_work", {"focus": "hccl"})
    assert "ascend_env_check" in text
    assert "generate_verify_handoff" in text


def test_prompts_have_agent_developer_gate():
    for name, args in (
        ("start_compiler_work", {"area": "pass_change"}),
        ("start_distributed_work", {"focus": "collectives"}),
        ("start_ascend_work", {"focus": "arch"}),
    ):
        text = _prompt_text(name, args)
        assert "developer" in text.lower()
        assert "Stop when" in text


def test_finish_work_prompt_closes_the_loop():
    text = _prompt_text("finish_work")
    assert "verify_ladder" in text
    assert "generate_verify_handoff" in text
    assert "clang-tidy" in text


def test_route_task_returns_expected_shape():
    route = knowledge.route_task_impl("distributed_codegen", detail="")
    assert route["task_type"] == "distributed_codegen"
    assert "read_first_canonical" in route
    assert "agent_verify_tasks" in route
    assert "developer_verify_tasks" in route
    assert route["bootstrap_prompt"] == "start_distributed_work"


def test_bootstrap_session_without_health():
    from mcp_hwnative_sys.bootstrap import bootstrap_session_impl

    out = bootstrap_session_impl("distributed_codegen", detail="allreduce", include_health=False)
    assert out["task_type"] == "distributed_codegen"
    assert "read_plan" in out
    assert "abstraction_seeds" in out
    assert out["health_summary"] is None


if __name__ == "__main__":
    import pytest

    pytest.main([__file__, "-v"])
