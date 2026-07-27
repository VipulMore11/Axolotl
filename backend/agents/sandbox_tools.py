"""
Ephemeral Docker sandbox for validating CI fix patches before MCP commit.

Uses one-shot `docker run` with a host-mounted workspace (not a long-lived
named container). Commands are allowlisted to avoid shell injection.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from langsmith import traceable

VALIDATOR_IMAGE = os.getenv("CI_FIX_VALIDATOR_IMAGE", "axolotl-validator")
WORKSPACE_ROOT = Path(
    os.getenv("CI_FIX_WORKSPACE_ROOT", "")
    or (Path(tempfile.gettempdir()) / "axolotl-sandbox")
)

# Safe relative path: no absolute paths, no .. traversal
_SAFE_REL_PATH = re.compile(r"^(?!/)(?!.*\.\.(?:/|$))[A-Za-z0-9_./\-]+$")


@dataclass
class CheckResult:
    """Result of a sandbox validation run."""

    passed: bool
    output: str
    command: str


def _docker_available() -> bool:
    try:
        import docker  # noqa: F401

        client = docker.from_env()
        client.ping()
        return True
    except Exception:
        return False


def reset_workspace(pipeline_id: str) -> Path:
    """Create a clean workspace directory for this pipeline session."""
    safe_id = re.sub(r"[^A-Za-z0-9_.\-]", "_", pipeline_id)[:80] or "unknown"
    workspace = WORKSPACE_ROOT / safe_id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def write_temp_file(workspace: Path, file_path: str, content: str) -> Path:
    """
    Write a proposed file into the sandbox workspace.

    Args:
        workspace: Host workspace root for this pipeline
        file_path: Relative path inside the project (e.g. requirements.txt)
        content: Full file contents to write

    Returns:
        Absolute host path of the written file
    """
    if not file_path or not _SAFE_REL_PATH.match(file_path.replace("\\", "/")):
        raise ValueError(f"Unsafe or empty file path: {file_path!r}")

    normalized = file_path.replace("\\", "/").lstrip("/")
    target = (workspace / normalized).resolve()
    if not str(target).startswith(str(workspace.resolve())):
        raise ValueError(f"Path escapes workspace: {file_path!r}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _allowlisted_argv(file_path: str, logs: str) -> list[str]:
    """
    Pick a single allowlisted validation command (argv list, no shell).

    - requirements.txt / ModuleNotFound → pip install -r requirements.txt
    - otherwise → ruff check on the file, falling back to py_compile
    """
    normalized = (file_path or "").replace("\\", "/").lower()
    logs_lower = (logs or "").lower()

    if (
        normalized.endswith("requirements.txt")
        or "modulenotfounderror" in logs_lower
        or "no module named" in logs_lower
    ):
        req = "requirements.txt"
        if normalized.endswith("requirements.txt"):
            req = file_path.replace("\\", "/")
        return ["pip", "install", "-r", req]

    if normalized.endswith(".py"):
        # Prefer ruff when present in the validator image; py_compile as fallback
        # is chosen at runtime via a tiny wrapper script in Dockerfile entry.
        return ["python", "-m", "axolotl_validate", file_path.replace("\\", "/")]

    if normalized:
        return ["python", "-m", "axolotl_validate", file_path.replace("\\", "/")]

    return ["python", "-m", "compileall", "-q", "."]


def run_check(
    workspace: Path,
    file_path: str,
    logs: str = "",
    *,
    image: Optional[str] = None,
    timeout_seconds: int = 120,
) -> CheckResult:
    """
    Run an allowlisted check inside an ephemeral validator container.

    Mounts `workspace` at /workspace and executes without a shell.
    """
    image_name = image or VALIDATOR_IMAGE
    argv = _allowlisted_argv(file_path, logs)
    command_display = " ".join(argv)

    if not _docker_available():
        return CheckResult(
            passed=False,
            output=(
                "Docker is not available on this host. "
                "Set CI_FIX_VALIDATE=false to skip validation, or install Docker."
            ),
            command=command_display,
        )

    import docker
    from docker.errors import ContainerError, ImageNotFound, APIError

    client = docker.from_env()
    host_path = str(workspace.resolve())

    # pip install needs network; compile/lint checks stay isolated.
    needs_network = argv[:2] == ["pip", "install"]
    run_kwargs: dict = {
        "image": image_name,
        "command": argv,
        "volumes": {host_path: {"bind": "/workspace", "mode": "rw"}},
        "working_dir": "/workspace",
        "mem_limit": "512m",
        "nano_cpus": 1_000_000_000,
        "remove": False,
        "detach": True,
    }
    if not needs_network:
        run_kwargs["network_mode"] = "none"

    container = None
    try:
        container = client.containers.run(**run_kwargs)
        result = container.wait(timeout=timeout_seconds)
        logs_out = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
        status = result.get("StatusCode", 1) if isinstance(result, dict) else int(result)
        return CheckResult(
            passed=status == 0,
            output=logs_out.strip() or f"exit code {status}",
            command=command_display,
        )
    except ImageNotFound:
        return CheckResult(
            passed=False,
            output=(
                f"Validator image '{image_name}' not found. "
                f"Build it with: docker build -t {image_name} -f backend/sandbox/Dockerfile backend/sandbox"
            ),
            command=command_display,
        )
    except ContainerError as exc:
        output = (exc.stderr or b"").decode("utf-8", errors="replace") if exc.stderr else str(exc)
        return CheckResult(passed=False, output=output.strip() or str(exc), command=command_display)
    except APIError as exc:
        return CheckResult(passed=False, output=f"Docker API error: {exc}", command=command_display)
    except Exception as exc:
        return CheckResult(passed=False, output=f"Sandbox error: {exc}", command=command_display)
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


@traceable(name="docker_validate_patch", run_type="tool")
def validate_patch(
    pipeline_id: str,
    file_path: str,
    content: str,
    logs: str = "",
) -> CheckResult:
    """Reset workspace, write a single patch, and run the allowlisted check."""
    workspace = reset_workspace(pipeline_id)
    try:
        write_temp_file(workspace, file_path, content)
    except ValueError as exc:
        return CheckResult(passed=False, output=str(exc), command="write_temp_file")

    return run_check(workspace, file_path, logs)


@traceable(name="docker_validate_patches", run_type="tool")
def validate_patches(
    pipeline_id: str,
    file_patches: list[dict],
    logs: str = "",
) -> CheckResult:
    """
    Write all patches into one workspace and run checks.

    For deps/ModuleNotFound → pip install -r on requirements.txt if present.
    Otherwise run allowlisted check on each Python file; first failure wins.
    """
    if not file_patches:
        return CheckResult(passed=False, output="No file_patches provided", command="validate_patches")

    workspace = reset_workspace(pipeline_id)
    written: list[str] = []
    for patch in file_patches:
        path = (patch.get("file_path") if isinstance(patch, dict) else getattr(patch, "file_path", "")) or ""
        content = (patch.get("updated_content") if isinstance(patch, dict) else getattr(patch, "updated_content", "")) or ""
        try:
            write_temp_file(workspace, path, content)
            written.append(path)
        except ValueError as exc:
            return CheckResult(passed=False, output=str(exc), command="write_temp_file")

    # Prefer requirements.txt check when present or ModuleNotFound in logs
    req = next((p for p in written if p.replace("\\", "/").endswith("requirements.txt")), None)
    logs_lower = (logs or "").lower()
    if req or "modulenotfounderror" in logs_lower or "no module named" in logs_lower:
        target = req or "requirements.txt"
        if (workspace / target).exists() or req:
            return run_check(workspace, req or target, logs)

    outputs: list[str] = []
    for path in written:
        result = run_check(workspace, path, logs)
        outputs.append(f"$ {result.command}\n{result.output}")
        if not result.passed:
            return CheckResult(
                passed=False,
                output="\n\n".join(outputs),
                command=result.command,
            )

    return CheckResult(
        passed=True,
        output="\n\n".join(outputs) or "all patches validated",
        command="validate_patches",
    )


def cleanup_workspace(pipeline_id: str) -> None:
    """Best-effort removal of a pipeline workspace."""
    safe_id = re.sub(r"[^A-Za-z0-9_.\-]", "_", pipeline_id)[:80] or "unknown"
    workspace = WORKSPACE_ROOT / safe_id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
