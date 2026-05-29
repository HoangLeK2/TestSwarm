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

# Default: use host adb server (Docker Desktop macOS).
ENV ADB_SERVER_SOCKET="tcp:host.docker.internal:5037"

CMD ["bash", "-lc", "adb -H host.docker.internal -P 5037 devices"]
