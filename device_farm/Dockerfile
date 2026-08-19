# syntax=docker.io/docker/dockerfile:1

# ── Device Farm Backend ──────────────────────────────────────────────────────
# Multi-stage build: deps → builder → runner
# Python 3.13 slim + uv for fast, reproducible installs
# Final image ~250MB (no build tools, no cache)

FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ── Stage 1: Install dependencies ───────────────────────────────────────────

FROM base AS deps

# System deps for compiled wheels (cryptography, lxml, numpy, av/PyAV)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libxml2-dev \
    libxslt1-dev \
    libavformat-dev \
    libavcodec-dev \
    libavutil-dev \
    libswscale-dev \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python package management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy only dependency files first (layer cache)
COPY pyproject.toml ./

# Install dependencies into .venv (isolated, reproducible)
#
# NOTE: `uv pip install -r pyproject.toml` ignores [tool.uv] override-dependencies
# (and uv.lock) — those only apply to `uv sync`. So airtest's pin wins and pulls
# opencv-contrib-python, whose binaries link libGL. The slim runtime image has no
# libGL, so `import cv2` raised "libGL.so.1: cannot open shared object file" and
# every visual-anchor path was dead. We only use aircv.find_template, i.e. plain
# TM_CCOEFF_NORMED, so the headless build is a drop-in — and ~90MB smaller.
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -r pyproject.toml && \
    uv pip uninstall --python .venv/bin/python opencv-contrib-python opencv-python || true && \
    uv pip install --python .venv/bin/python "opencv-python-headless>=4.10.0"

# ── Stage 2: Copy source ────────────────────────────────────────────────────

FROM base AS runner

ARG SCRCPY_SERVER_VERSION=3.3.4

# Runtime deps only (no gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libavformat61 \
    libavcodec61 \
    adb \
    curl \
    ca-certificates \
    # OCR backend. Without these, OCREngine.available is False and every
    # extract_text_ocr step fails with ENGINE_UNAVAILABLE. `vie` is not
    # optional: OCRService defaults to lang ["vi", "en"].
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-vie \
    && rm -rf /var/lib/apt/lists/* && \
    mkdir -p /usr/share/scrcpy && \
    curl -fL "https://github.com/Genymobile/scrcpy/releases/download/v${SCRCPY_SERVER_VERSION}/scrcpy-server-v${SCRCPY_SERVER_VERSION}" \
      -o /usr/share/scrcpy/scrcpy-server

# Non-root user
RUN groupadd --system --gid 1001 farm && \
    useradd --system --uid 1001 --gid farm farm

WORKDIR /app

# Copy venv from deps stage
COPY --from=deps /app/.venv .venv

# Copy application source
COPY --chown=farm:farm . .

# Ensure .venv/bin is on PATH
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app"

# Create directories for runtime data (/app is root-owned; farm cannot mkdir here)
RUN mkdir -p /app/captures /app/data /app/logs && \
    chown -R farm:farm /app

USER farm

EXPOSE 8081
# gRPC relay — agent-boot (local) connects inbound here
EXPOSE 50051

HEALTHCHECK --interval=30s --timeout=10s --retries=3 --start-period=60s \
    CMD curl -fsS http://localhost:8081/api/live || exit 1

CMD ["python", "main.py"]
