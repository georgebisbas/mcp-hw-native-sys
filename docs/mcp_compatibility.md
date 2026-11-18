# MCP compatibility and safety

## Supported baseline

This server currently targets Python 3.10+ and the MCP Python SDK `1.30.x` through
the end of the 1.x line (`mcp>=1.30.0,<2`). The baseline is deliberate: the server
uses `mcp.server.fastmcp.FastMCP`, tool annotations, structured output generation,
prompt completions, and the classic stdio lifecycle.

The MCP Python SDK has a v2 line with breaking API and lifecycle changes. Do not
remove the upper bound as a routine dependency refresh. A v2 migration should be
handled as a separate compatibility change with:

1. a client matrix covering Codex CLI/IDE, Claude Code, and at least one raw MCP client;
2. stdio initialize/list-tools/list-resources/list-prompts/call-tool smoke tests;
3. explicit checks for tool annotations, output schemas, completions, and progress;
4. a release note describing any changed tool names, schemas, or approval behavior.

## Trust boundaries

Repository files, generated artifacts, GitHub issues, pull requests, review bodies,
and command output are data supplied by external or user-controlled sources. The
server labels these results with a `trust_boundary` field where text can contain
instructions or prompt-injection content. Clients must treat those fields as data,
not as server policy.

Tool annotations improve client UX and approval decisions, but they are hints. The
server-side command policy, NPU/sim routing, path validation, and subprocess limits
remain the enforcement layer.

## Local validation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
pytest
ruff check mcp_hwnative_sys tests
```
