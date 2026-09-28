"""pypto-lib workload catalog."""

from __future__ import annotations

import sys
from pathlib import Path

from mcp_hwnative_sys.paths import workspace_root

TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from build_pypto_lib_workloads import build_workloads  # noqa: E402


def test_catalog_includes_models_from_the_index():
    catalog = build_workloads(workspace_root())
    names = {item["name"] for item in catalog["workloads"]}
    assert {
        "qwen3_14b",
        "deepseek_v4_flash_mtp",
        "deepseek_v4_flash_dspark",
        "deepseek_v4_pro",
        "deepseek_v4_1_flash",
        "glm5_3_flash",
    } <= names
    flash = next(item for item in catalog["workloads"] if item["name"] == "deepseek_v4_1_flash")
    assert flash["documented"] is True
    assert flash["serving"]
    phases = {kernel["phase"] for kernel in flash["kernels"]}
    assert "prefill" in phases
