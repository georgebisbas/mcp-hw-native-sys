from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def default_workspace_root() -> Path:
    return project_root().parents[1]


def repos_config_path() -> Path:
    return project_root() / "config" / "repos.json"


def knowledge_config_path() -> Path:
    return project_root() / "config" / "knowledge.json"


def entrypoints_config_path() -> Path:
    return project_root() / "config" / "entrypoints.json"


def abstractions_config_path() -> Path:
    return project_root() / "config" / "abstractions.json"


def ascend_abstractions_config_path() -> Path:
    return project_root() / "config" / "ascend_abstractions.json"


def contract_artifacts_config_path() -> Path:
    return project_root() / "config" / "contract_artifacts.json"


def is_within(path: Path, root: Path) -> bool:
    """Return True if ``path`` is ``root`` itself or nested under it.

    Boundary-aware containment check. Unlike ``str.startswith`` on the string
    forms, this does not treat a sibling directory as contained: given
    ``root=/ws/pypto``, the path ``/ws/pypto-lib/x`` is correctly rejected.
    Both operands should already be resolved (absolute, symlink-free).
    """
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_doc_path(relative_path: str) -> Path:
    """Resolve a document path — MCP-owned content/ lives under project_root."""
    normalized = relative_path.replace("\\", "/")
    if normalized.startswith("content/"):
        resolved = (project_root() / normalized).resolve()
        root = project_root().resolve()
        if not is_within(resolved, root):
            raise ValueError(f"Path escapes MCP project root: {relative_path}")
        return resolved
    return resolve_workspace_path(relative_path)


_json_cache: dict[str, tuple[float, Any]] = {}


def load_json_cached(path: Path) -> Any:
    """Load JSON with mtime-based cache invalidation.

    Parses a file at most once per mtime: unchanged files are served from
    cache, but edits to ``config/*.json`` are picked up on the next call
    without restarting the server. The returned object is shared across
    callers, so treat it as read-only.
    """
    key = str(path)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        _json_cache.pop(key, None)
        raise
    cached = _json_cache.get(key)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    _json_cache[key] = (mtime, data)
    return data


def load_repos_config() -> dict[str, Any]:
    return load_json_cached(repos_config_path())


def workspace_root(raw_config: dict[str, Any] | None = None) -> Path:
    env_root = os.getenv("HW_NATIVE_SYS_ROOT", "").strip()
    if env_root:
        return Path(env_root).expanduser().resolve()

    config = raw_config if raw_config is not None else load_repos_config()
    configured_root = str(config.get("workspace_root", "")).strip()
    if configured_root:
        candidate = Path(configured_root).expanduser()
        if not candidate.is_absolute():
            candidate = (project_root() / candidate).resolve()
        return candidate.resolve()

    return default_workspace_root().resolve()


def safe_relpath(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def run_command(
    args: list[str],
    cwd: Path | None = None,
    timeout_seconds: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a command, capturing output.

    A timeout is reported as a completed process with exit code 124 (the
    conventional timeout code) and the partial output preserved, so callers
    surface it via their normal ``exit_code`` / ``stderr`` envelopes instead
    of the caller raising ``TimeoutExpired``. A missing executable raises a
    clean ``RuntimeError`` naming the binary.
    """
    try:
        return subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        # Under text=True these are str, but typeshed types them loosely.
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        note = f"Command timed out after {timeout_seconds}s: {' '.join(args)}"
        result: subprocess.CompletedProcess[str] = subprocess.CompletedProcess(
            args=args,
            returncode=124,
            stdout=stdout,
            stderr=(stderr + ("\n" if stderr else "") + note),
        )
        return result
    except FileNotFoundError as exc:
        raise RuntimeError(f"Executable not found in PATH: {args[0]!r} ({exc})") from exc


def git_command(
    repo_path: Path,
    args: list[str],
    timeout_seconds: int = 20,
) -> subprocess.CompletedProcess[str]:
    return run_command(["git", "-C", str(repo_path), *args], timeout_seconds=timeout_seconds)


def resolve_workspace_path(relative_path: str) -> Path:
    root = workspace_root()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (root / relative_path).resolve()

    if not is_within(resolved, root):
        raise ValueError(f"Path escapes workspace root: {relative_path}")
    return resolved
