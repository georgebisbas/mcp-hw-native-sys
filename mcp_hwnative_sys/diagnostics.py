"""Operational diagnostics for local MCP deployments."""

from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys
from typing import Any

from mcp_hwnative_sys.ascend_env import npu_env_summary
from mcp_hwnative_sys.paths import load_repos_config, workspace_root


def _command_check(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    return {"name": name, "available": path is not None, "path": path}


def _gh_auth_check() -> dict[str, Any]:
    """Check GitHub CLI authentication without returning account details."""
    path = shutil.which("gh")
    if path is None:
        return {"available": False, "authenticated": False, "reason": "gh not found"}
    try:
        proc = subprocess.run(
            [path, "auth", "status"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "authenticated": False, "reason": type(exc).__name__}
    return {
        "available": True,
        "authenticated": proc.returncode == 0,
        "reason": None if proc.returncode == 0 else "gh auth status failed",
    }


def _sim_image_checks() -> list[dict[str, Any]]:
    images = (
        "pypto3-hw-native-sys:sim",
        "simpler-hw-native-sys:sim",
        "pypto-lib-hw-native-sys:sim",
    )
    docker = shutil.which("docker")
    if docker is None:
        return [{"image": image, "available": False, "reason": "docker not found"} for image in images]
    result = []
    for image in images:
        try:
            proc = subprocess.run(
                [docker, "image", "inspect", image],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            result.append({"image": image, "available": proc.returncode == 0})
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.append({"image": image, "available": False, "reason": type(exc).__name__})
    return result


def _mcp_version() -> str | None:
    try:
        return importlib.metadata.version("mcp")
    except importlib.metadata.PackageNotFoundError:
        return None


def doctor_impl() -> dict[str, Any]:
    """Return a non-secret, actionable health report for this MCP deployment."""
    config = load_repos_config()
    root = workspace_root(config)
    repositories = config.get("repositories", {})
    repo_checks = []
    for name, relative_path in sorted(repositories.items()):
        path = (root / str(relative_path)).resolve()
        repo_checks.append(
            {
                "repo": name,
                "path": str(relative_path),
                "exists": path.is_dir(),
                "is_git_repo": (path / ".git").exists(),
            }
        )

    return {
        "status": "ok" if all(item["exists"] for item in repo_checks) else "degraded",
        "python": {"version": sys.version.split()[0], "executable": sys.executable},
        "mcp": {"version": _mcp_version()},
        "workspace_root": str(root),
        "repositories": repo_checks,
        "commands": [_command_check(name) for name in ("rg", "gh", "docker", "npu-smi")],
        "github": _gh_auth_check(),
        "sim_images": _sim_image_checks(),
        "npu": npu_env_summary(),
        "notes": [
            "Repository paths are returned relative to the configured workspace where possible.",
            "GitHub authentication status is reported without account names or tokens.",
            "Missing repositories are expected for partial checkouts; install the sibling stack repos for full coverage.",
        ],
    }
