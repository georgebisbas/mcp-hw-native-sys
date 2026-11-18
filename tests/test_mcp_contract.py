"""Contract tests for MCP metadata and client-facing safety behavior."""

from __future__ import annotations

import asyncio

from mcp.types import CompletionArgument, PromptReference

from mcp_hwnative_sys import server


def _tool(name: str):
    return next(item for item in asyncio.run(server.mcp.list_tools()) if item.name == name)


def test_server_instructions_mark_untrusted_content_and_workflow():
    instructions = server.mcp._mcp_server.instructions
    assert instructions is not None
    assert "untrusted data" in instructions
    assert "developer_only" in instructions


def test_tools_have_output_schemas_and_risk_annotations():
    for tool in asyncio.run(server.mcp.list_tools()):
        assert tool.outputSchema is not None, tool.name
        assert tool.annotations is not None, tool.name

    assert _tool("read_file").annotations.readOnlyHint is True
    assert _tool("run_task").annotations.destructiveHint is True
    assert _tool("pr_watch").annotations.openWorldHint is True


def test_write_capable_commands_require_explicit_authorization():
    try:
        server.run_command(repo="pypto", command="touch generated.txt")
    except ValueError as exc:
        assert "allow_writes" in str(exc)
    else:  # pragma: no cover - safety regression guard
        raise AssertionError("write-capable command was accepted without allow_writes")


def test_command_risk_classification_is_explicit():
    assert server._command_risk("git status -sb") == server.DEFAULT_RISK
    assert server._command_risk("pytest tests/ut -q") == server.RISK_WRITES


def test_shell_control_syntax_is_rejected_from_task_arguments():
    try:
        server._validate_extra_args("--name foo; touch generated.txt")
    except ValueError as exc:
        assert "shell control" in str(exc)
    else:  # pragma: no cover - safety regression guard
        raise AssertionError("shell control syntax was accepted")


def test_common_credentials_are_redacted_from_output():
    output = server._safe_output("Authorization: Bearer abc.def\nTOKEN=secret-value")
    assert "abc.def" not in output
    assert "secret-value" not in output
    assert "REDACTED" in output


def test_prompt_completion_returns_known_workflow_values():
    result = asyncio.run(
        server._complete_prompt_or_resource(
            PromptReference(type="ref/prompt", name="start_ascend_work"),
            CompletionArgument(name="focus", value="hc"),
            None,
        )
    )
    assert result.values == ["hccl"]
