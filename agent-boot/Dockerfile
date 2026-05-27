FROM python:3.13-slim

WORKDIR /app

# System deps:
# - android adb: talk to devices (Linux hosts only; on macOS, ADB is typically on host)
# - ca-certificates/curl: basic TLS + health/debug
RUN apt-get update \
  && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    android-sdk-platform-tools \
  && rm -rf /var/lib/apt/lists/*

# uv is used by this repo to resolve/install deps (uv.lock present).
RUN python -m pip install --no-cache-dir --upgrade pip uv

COPY ./pyproject.toml ./uv.lock ./README.md* ./main.py ./
COPY ./relay ./relay
COPY ./bootstrap.py ./bootstrap.py

# Install dependencies exactly as locked.
RUN uv sync --frozen --no-dev

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Default to relay-only; bootstrap typically needs USB access + device APKs.
ENTRYPOINT ["/app/.venv/bin/python", "main.py"]
CMD ["--relay-only"]

