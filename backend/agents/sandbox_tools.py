"""
Ephemeral Docker sandbox for validating CI fix patches before MCP commit.

Uses one-shot `docker run` with a host-mounted workspace (not a long-lived
named container). Commands are allowlisted to avoid shell injection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

from langsmith import traceable

VALIDATOR_IMAGE = os.getenv("CI_FIX_VALIDATOR_IMAGE", "axolotl-validator")
WORKSPACE_ROOT = Path(
    os.getenv("CI_FIX_WORKSPACE_ROOT", "")
    or (Path(tempfile.gettempdir()) / "axolotl-sandbox")
)
# Resolve the sandbox directory (contains Dockerfile) relative to this file.
_SANDBOX_DIR = Path(__file__).resolve().parent.parent / "sandbox"
_VALIDATOR_HASH_LABEL = "com.axolotl.validator.source-sha256"

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


def _ensure_validator_image(client, image_name: str) -> bool:
    """
    Ensure the validator Docker image exists, building it automatically if missing.

    Returns True if the image is available (pre-existing or freshly built),
    False if the build failed or the Dockerfile is missing.
    """
    dockerfile_path = _SANDBOX_DIR / "Dockerfile"
    validator_path = _SANDBOX_DIR / "axolotl_validate.py"
    if not dockerfile_path.exists():
        logger.warning(
            "Cannot auto-build '%s': Dockerfile not found at %s",
            image_name,
            dockerfile_path,
        )
        return False

    source_hash = hashlib.sha256(
        dockerfile_path.read_bytes()
        + (validator_path.read_bytes() if validator_path.exists() else b"")
    ).hexdigest()
    try:
        image = client.images.get(image_name)
        labels = (image.attrs.get("Config") or {}).get("Labels") or {}
        if labels.get(_VALIDATOR_HASH_LABEL) == source_hash:
            return True
        logger.info("Validator image '%s' is stale; rebuilding it.", image_name)
    except Exception:
        pass  # Image not found, attempt auto-build below

    logger.info(
        "Validator image '%s' not found — auto-building from %s ...",
        image_name,
        _SANDBOX_DIR,
    )
    try:
        client.images.build(
            path=str(_SANDBOX_DIR),
            dockerfile="Dockerfile",
            tag=image_name,
            labels={_VALIDATOR_HASH_LABEL: source_hash},
            rm=True,
        )
        logger.info("Successfully built validator image '%s'.", image_name)
        return True
    except Exception as exc:
        logger.error("Auto-build of '%s' failed: %s", image_name, exc)
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
    argv = _allowlisted_argv(file_path, logs)
    return _run_argv(
        workspace,
        argv,
        image=image,
        timeout_seconds=timeout_seconds,
        needs_network=argv[:2] == ["pip", "install"],
    )


def _run_argv(
    workspace: Path,
    argv: list[str],
    *,
    image: Optional[str] = None,
    timeout_seconds: int = 120,
    needs_network: bool = False,
) -> CheckResult:
    """Run one allowlisted argv in one ephemeral validator container."""
    image_name = image or VALIDATOR_IMAGE
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
    from docker.errors import APIError, ContainerError

    client = docker.from_env()

    # Auto-build the validator image if it doesn't exist yet.
    if not _ensure_validator_image(client, image_name):
        return CheckResult(
            passed=False,
            output=(
                f"Validator image '{image_name}' not found and auto-build failed. "
                f"Build it manually with: docker build -t {image_name} "
                f"-f backend/sandbox/Dockerfile backend/sandbox"
            ),
            command=command_display,
        )

    host_path = str(workspace.resolve())

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
    *,
    original_contents: Optional[dict[str, str]] = None,
    strategy_type: str = "",
    error_signature: Optional[dict] = None,
) -> CheckResult:
    """
    Validate all original/patched file pairs in one ephemeral container.

    Syntax failures and in-scope newly introduced findings are hard failures.
    Pre-existing findings are ignored, while newly introduced out-of-scope lint
    findings are reported as advisory output.
    """
    if not file_patches:
        return CheckResult(passed=False, output="No file_patches provided", command="validate_patches")

    workspace = reset_workspace(pipeline_id)
    originals = {
        path.replace("\\", "/").lstrip("/"): content
        for path, content in (original_contents or {}).items()
    }
    manifest_files: list[dict[str, Optional[str]]] = []
    requirements_path: Optional[str] = None
    for patch in file_patches:
        path = (patch.get("file_path") if isinstance(patch, dict) else getattr(patch, "file_path", "")) or ""
        content = (patch.get("updated_content") if isinstance(patch, dict) else getattr(patch, "updated_content", "")) or ""
        normalized = path.replace("\\", "/").lstrip("/")
        patched_path = f"patched/{normalized}"
        original_path: Optional[str] = None
        try:
            write_temp_file(workspace, patched_path, content)
            if normalized in originals:
                original_path = f"original/{normalized}"
                write_temp_file(workspace, original_path, originals[normalized])
        except ValueError as exc:
            return CheckResult(passed=False, output=str(exc), command="write_temp_file")

        manifest_files.append(
            {
                "path": normalized,
                "patched": patched_path,
                "original": original_path,
            }
        )
        if normalized.lower().endswith("requirements.txt"):
            requirements_path = patched_path

    signature = dict(error_signature or {})
    error_class = str(signature.get("error_class") or "").lower()
    strategy = (strategy_type or "").lower()
    lint_codes = [
        str(code).upper()
        for code in (signature.get("lint_codes") or [])
        if code
    ]
    if strategy == "deps" or error_class == "deps":
        mode = "deps"
    elif strategy == "format" or error_class == "format":
        mode = "format"
    elif strategy == "lint" or error_class == "lint":
        mode = "lint"
    elif strategy == "import" or error_class == "import":
        mode = "import"
    else:
        mode = "code"

    manifest = {
        "mode": mode,
        "lint_codes": lint_codes if mode == "lint" else [],
        "requirements_path": requirements_path,
        "files": manifest_files,
    }
    manifest_path = "validation-manifest.json"
    write_temp_file(
        workspace,
        manifest_path,
        json.dumps(manifest, ensure_ascii=True),
    )
    argv = ["python", "-m", "axolotl_validate", "--manifest", manifest_path]
    return _run_argv(
        workspace,
        argv,
        needs_network=mode == "deps" and bool(requirements_path),
    )


def cleanup_workspace(pipeline_id: str) -> None:
    """Best-effort removal of a pipeline workspace."""
    safe_id = re.sub(r"[^A-Za-z0-9_.\-]", "_", pipeline_id)[:80] or "unknown"
    workspace = WORKSPACE_ROOT / safe_id
    if workspace.exists():
        shutil.rmtree(workspace, ignore_errors=True)
