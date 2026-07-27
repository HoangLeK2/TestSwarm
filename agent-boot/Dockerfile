# syntax=docker/dockerfile:1

# ── Builder: deps, cert fetch, venv (not shipped) ────────────────────────────
FROM python:3.13-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    openssl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN chmod +x docker/entrypoint.sh docker/fetch-grpc-relay-ca.sh docker/prepare-assets.sh \
  && ./docker/prepare-assets.sh \
  && find /app/.venv -type d \( -name __pycache__ -o -name tests -o -name test \) -prune -exec rm -rf {} + 2>/dev/null || true

ARG RELAY_GRPC_TLS_HOST=grpc-device-farm.tommadethis.app
ARG RELAY_GRPC_TLS_PORT=443
RUN ./docker/fetch-grpc-relay-ca.sh "$RELAY_GRPC_TLS_HOST" "$RELAY_GRPC_TLS_PORT" /app/certs/grpc-relay-ca.pem

# ── Runtime: adb + venv only (no uv/curl/openssl build tools) ────────────────
FROM python:3.13-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    ca-certificates \
  && update-ca-certificates \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/certs /app/certs
COPY --from=builder /app/docker /app/docker
COPY --from=builder /app/main.py /app/main.py
COPY --from=builder /app/relay /app/relay
COPY --from=builder /app/assets /app/assets

ENV PATH="/app/.venv/bin:${PATH}" \
    ADB_HOST=host.docker.internal \
    ADB_PORT=5037 \
    ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 \
    ANDROID_ADB_SERVER_HOST=host.docker.internal \
    ANDROID_ADB_SERVER_PORT=5037 \
    ADB_WAIT_SECONDS=120 \
    RELAY_MODE=grpc \
    RELAY_SERVER=grpc-device-farm.tommadethis.app:443 \
    RELAY_GRPC_TLS=true \
    RELAY_GRPC_ROOT_CERT_FILE=/app/certs/grpc-relay-ca.pem \
    AGENT_BOOT_AUTO_BOOTSTRAP=1

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["/app/.venv/bin/python", "main.py"]
