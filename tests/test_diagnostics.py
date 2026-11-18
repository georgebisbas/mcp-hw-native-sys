"""Tests for the portable installation diagnostics tool."""

from __future__ import annotations

from mcp_hwnative_sys.diagnostics import doctor_impl


def test_doctor_returns_non_secret_environment_report():
    result = doctor_impl()
    assert result["status"] in {"ok", "degraded"}
    assert "python" in result
    assert "mcp" in result
    assert "repositories" in result
    assert "commands" in result
    assert "github" in result
    assert len(result["sim_images"]) == 3
    assert "token" not in str(result["github"]).lower()
