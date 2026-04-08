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
RUN uv venv .venv && \
    uv pip install --python .venv/bin/python -r pyproject.toml

# ── Stage 2: Copy source ────────────────────────────────────────────────────

FROM base AS runner

# Runtime deps only (no gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    libxslt1.1 \
    libavformat61 \
    libavcodec61 \
    curl \
    && rm -rf /var/lib/apt/lists/*

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

# Create directories for runtime data
RUN mkdir -p /app/captures /app/data && \
    chown -R farm:farm /app/captures /app/data

USER farm

EXPOSE 8081
# gRPC relay — agent-boot (local) connects inbound here
EXPOSE 50051

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8081/api/health || exit 1

CMD ["python", "main.py"]
