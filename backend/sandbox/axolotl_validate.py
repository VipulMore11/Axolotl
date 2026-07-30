"""Allowlisted file validator used inside the axolotl-validator image."""

from __future__ import annotations

import json
import py_compile
import subprocess
import sys
from collections import Counter
from pathlib import Path


def _run(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, capture_output=True, text=True)


def _compile_python(paths: list[str]) -> list[str]:
    failures: list[str] = []
    for file_path in paths:
        try:
            py_compile.compile(file_path, doraise=True)
        except py_compile.PyCompileError as exc:
            failures.append(f"{file_path}: {exc}")
    return failures


def _ruff_findings(paths: list[str], lint_codes: list[str]) -> tuple[Counter, str]:
    if not paths:
        return Counter(), ""
    argv = ["ruff", "check", "--output-format=json"]
    if lint_codes:
        argv.extend(["--select", ",".join(lint_codes)])
    argv.extend(paths)
    result = _run(argv)
    try:
        payload = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return Counter(), (
            f"ruff could not produce JSON (exit {result.returncode}): "
            f"{result.stderr or result.stdout}"
        )
    findings = Counter(
        (str(item.get("code", "")), str(item.get("message", "")))
        for item in payload
        if item.get("code")
    )
    if result.returncode not in (0, 1):
        return Counter(), (
            f"ruff execution failed (exit {result.returncode}): "
            f"{result.stderr or result.stdout}"
        )
    return findings, ""


def _format_fails(path: str) -> tuple[bool, str]:
    result = _run(["ruff", "format", "--check", path])
    if result.returncode in (0, 1):
        return result.returncode != 0, ""
    return False, (
        f"ruff format failed for {path} (exit {result.returncode}): "
        f"{result.stderr or result.stdout}"
    )


def _format_findings(files: list[dict]) -> tuple[list[str], list[str]]:
    introduced: list[str] = []
    errors: list[str] = []
    for item in files:
        patched = str(item["patched"])
        original = item.get("original")
        patched_fails, error = _format_fails(patched)
        if error:
            errors.append(error)
            continue
        original_fails = False
        if original:
            original_fails, error = _format_fails(str(original))
            if error:
                errors.append(error)
                continue
        if patched_fails and not original_fails:
            introduced.append(str(item["path"]))
    return introduced, errors


def _render_findings(findings: Counter) -> list[str]:
    lines: list[str] = []
    for (code, message), count in sorted(findings.items()):
        suffix = f" (x{count})" if count > 1 else ""
        lines.append(f"- {code}: {message}{suffix}")
    return lines


def validate_manifest(manifest_path: str) -> int:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    files = list(manifest.get("files") or [])
    mode = str(manifest.get("mode") or "code")
    lint_codes = [
        str(code)
        for code in manifest.get("lint_codes") or []
        if str(code) != "E999"
    ]
    patched_python = [
        str(item["patched"])
        for item in files
        if str(item.get("path", "")).lower().endswith((".py", ".pyi"))
    ]
    original_python = [
        str(item["original"])
        for item in files
        if item.get("original")
        and str(item.get("path", "")).lower().endswith((".py", ".pyi"))
    ]

    compile_failures = _compile_python(patched_python)
    if compile_failures:
        print("Hard validation failure: patched Python does not compile.")
        print("\n".join(f"- {failure}" for failure in compile_failures))
        return 1

    requirements_path = manifest.get("requirements_path")
    if mode == "deps" and requirements_path:
        result = _run(["pip", "install", "-r", str(requirements_path)])
        sys.stdout.write(result.stdout or "")
        sys.stderr.write(result.stderr or "")
        if result.returncode != 0:
            return result.returncode

    if mode == "format":
        introduced_format, format_errors = _format_findings(files)
        if format_errors:
            print("\n".join(format_errors), file=sys.stderr)
            return 1
        if introduced_format:
            print("Hard validation failure: patch introduced formatting failures.")
            print("\n".join(f"- {path}" for path in introduced_format))
            return 1

    # Lint failures are compared by (code, message), not by line number, so
    # harmless line shifts do not make pre-existing debt look newly introduced.
    original_findings, original_error = _ruff_findings(original_python, lint_codes)
    patched_findings, patched_error = _ruff_findings(patched_python, lint_codes)
    if original_error or patched_error:
        print(original_error or patched_error, file=sys.stderr)
        return 1

    introduced = patched_findings - original_findings
    if introduced and mode == "lint":
        print("Hard validation failure: patch introduced lint findings.")
        print("\n".join(_render_findings(introduced)))
        return 1
    if introduced:
        print("Advisory only: patch introduced lint findings outside the CI failure scope.")
        print("\n".join(_render_findings(introduced)))
    elif patched_findings:
        print(
            f"Ignored {sum(patched_findings.values())} pre-existing lint finding(s); "
            "the patch introduced none."
        )

    print(f"Validation passed for {len(files)} patched file(s).")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print(
            "usage: python -m axolotl_validate <relative-file> | "
            "--manifest <validation.json>",
            file=sys.stderr,
        )
        return 2

    if args[0] == "--manifest":
        if len(args) != 2:
            print("--manifest requires exactly one path", file=sys.stderr)
            return 2
        return validate_manifest(args[1])

    file_path = args[0]
    target = Path(file_path)
    if not target.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        return 1

    if target.suffix == ".py":
        # Prefer ruff when installed; fall back to bytecode compile.
        ruff = subprocess.run(
            ["ruff", "check", file_path],
            capture_output=True,
            text=True,
        )
        if ruff.returncode == 0:
            print(ruff.stdout or f"ruff check passed: {file_path}")
            return 0
        if "No such file" not in (ruff.stderr or "") and ruff.returncode != 127:
            sys.stdout.write(ruff.stdout or "")
            sys.stderr.write(ruff.stderr or "")
            return ruff.returncode

        try:
            py_compile.compile(file_path, doraise=True)
            print(f"py_compile passed: {file_path}")
            return 0
        except py_compile.PyCompileError as exc:
            print(str(exc), file=sys.stderr)
            return 1

    # Non-Python: ensure the file is readable UTF-8 text
    try:
        target.read_text(encoding="utf-8")
        print(f"file readable: {file_path}")
        return 0
    except Exception as exc:
        print(f"Failed to read {file_path}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
