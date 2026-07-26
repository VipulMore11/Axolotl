FROM python:3.12-slim

WORKDIR /opt/axolotl-validator

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir ruff==0.12.0

# Allowlisted validator helper (python -m axolotl_validate <file>)
COPY axolotl_validate.py /usr/local/lib/python3.12/site-packages/axolotl_validate.py

WORKDIR /workspace

# Default: no-op; callers override command with allowlisted argv
CMD ["python", "-c", "print('axolotl-validator ready')"]
