"""Allowlisted file validator used inside the axolotl-validator image."""

from __future__ import annotations

import py_compile
import subprocess
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: python -m axolotl_validate <relative-file>", file=sys.stderr)
        return 2

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
