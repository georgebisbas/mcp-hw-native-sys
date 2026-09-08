"""Tests for generated-artifact discovery (mcp_hwnative_sys.artifacts)."""

from __future__ import annotations

from pathlib import Path

import pytest

import mcp_hwnative_sys.artifacts as artifacts_mod


def _write(path: Path, content: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def fake_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ws = tmp_path / "ws"
    build_output = ws / "pypto-lib" / "build_output" / "qwen_decode_20260908"
    _write(build_output / "passes_dump" / "00_frontend.py", "ir = ...\n")
    _write(build_output / "passes_dump" / "12_after_simplify.py", "ir = ...\n")
    _write(build_output / "ptoas" / "qwen_decode.pto")
    _write(build_output / "kernels" / "aic" / "qwen_decode_aic.cpp")
    _write(build_output / "kernels" / "aiv" / "qwen_decode_aiv.cpp")
    _write(build_output / "orchestration" / "main_orch.cpp")
    _write(build_output / "orchestration" / "main_orch.so")
    _write(build_output / "kernel_config.py", "KERNELS = []\n")
    _write(build_output / "dfx_outputs" / "args_dump_0.json")
    # Noise that must not be classified.
    _write(build_output / "data" / "in" / "x.pt")
    _write(ws / "pypto-lib" / "src" / "helper.cpp")

    monkeypatch.setattr(
        artifacts_mod,
        "_repo_roots",
        lambda: [("pypto-lib", build_output.parent)],
    )
    monkeypatch.setattr(artifacts_mod, "workspace_root", lambda: ws)
    return ws


def test_finds_pass_dump_dir(fake_workspace: Path):
    result = artifacts_mod.find_generated_artifacts_impl(kind="passes_dump")
    assert result["count"] == 1
    assert result["results"][0]["path"].endswith("qwen_decode_20260908/passes_dump")


def test_filters_by_kind_and_repo(fake_workspace: Path):
    kernels = artifacts_mod.find_generated_artifacts_impl(kind="kernel_aic_cpp")
    assert [r["kind"] for r in kernels["results"]] == ["kernel_aic_cpp"]

    orch = artifacts_mod.find_generated_artifacts_impl(kind="orchestration_cpp")
    assert any(r["path"].endswith("main_orch.cpp") for r in orch["results"])


def test_program_hint_narrows_results(fake_workspace: Path):
    result = artifacts_mod.find_generated_artifacts_impl(program_hint="qwen_decode")
    assert result["count"] > 0
    assert all("qwen_decode" in r["path"] for r in result["results"])


def test_unfiltered_lists_all_classified(fake_workspace: Path):
    result = artifacts_mod.find_generated_artifacts_impl()
    kinds = {r["kind"] for r in result["results"]}
    assert {"passes_dump", "pto_mlir", "kernel_aic_cpp", "kernel_aiv_cpp", "dfx_outputs"} <= kinds
    # Raw source helper.cpp and data/*.pt are not generated-code artifacts.
    assert not any(r["path"].endswith("helper.cpp") for r in result["results"])


def test_unknown_kind_raises(fake_workspace: Path):
    with pytest.raises(ValueError, match="Unknown kind"):
        artifacts_mod.find_generated_artifacts_impl(kind="bogus")
