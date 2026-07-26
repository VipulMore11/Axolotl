# Axolotl CI Fix Validator
#
# Build (from repo root):
#   docker build -t axolotl-validator -f backend/sandbox/Dockerfile backend/sandbox
#
# The LangGraph CI fix agent mounts a per-pipeline workspace at /workspace and
# runs allowlisted checks (pip install -r, ruff/py_compile) with network disabled.
