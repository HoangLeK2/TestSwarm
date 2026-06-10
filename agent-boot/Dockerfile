FROM python:3.13-slim

# System deps:
# - adb client (talks to host adb server via TCP)
# - curl/ca-certificates for uv installer
RUN apt-get update && apt-get install -y --no-install-recommends \
    adb \
    android-sdk-platform-tools \
    ca-certificates \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install uv (matches customer install path behavior, but inside container).
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# Install Python deps (cached layer).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# App source
COPY . .

RUN chmod +x docker/entrypoint.sh

ENV ADB_HOST=host.docker.internal \
    ADB_PORT=5037 \
    ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 \
    ANDROID_ADB_SERVER_HOST=host.docker.internal \
    ANDROID_ADB_SERVER_PORT=5037 \
    ADB_WAIT_SECONDS=120

ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["uv", "run", "main.py", "--relay-only"]
