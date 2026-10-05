#!/bin/bash
# gen_proto.sh — Compile relay.proto for both backend and agent-boot.
# Run from the deviceFarmer/ root directory:
#   bash scripts/gen_proto.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$ROOT_DIR/backend/proto"

echo "Proto source: $PROTO_DIR/relay.proto"

# Prefer project venvs (grpc_tools) via uv; override with PYTHON=python3 if needed.
UV_RUN=(uv run python)
if ! command -v uv &>/dev/null; then
  UV_RUN=("${PYTHON:-python3}")
  if ! command -v "${UV_RUN[0]}" &>/dev/null; then
    echo "error: install uv, or set PYTHON to a python with grpcio-tools" >&2
    exit 1
  fi
fi

# ── backend ───────────────────────────────────────────────────────────────────
DF_OUT="$ROOT_DIR/backend/runtime/transports/grpc_gen"
mkdir -p "$DF_OUT"
touch "$DF_OUT/__init__.py"

cd "$ROOT_DIR/backend"
"${UV_RUN[@]}" -m grpc_tools.protoc \
  --python_out="$DF_OUT" \
  --grpc_python_out="$DF_OUT" \
  --proto_path=proto \
  relay.proto

# Fix relative imports in generated files (grpc_tools generates broken imports)
sed -i '' 's/^import relay_pb2/from . import relay_pb2/' "$DF_OUT/relay_pb2_grpc.py" 2>/dev/null || \
sed -i 's/^import relay_pb2/from . import relay_pb2/' "$DF_OUT/relay_pb2_grpc.py"

echo "  backend: $DF_OUT"

# ── agent-boot ────────────────────────────────────────────────────────────────
AB_OUT="$ROOT_DIR/agent-boot/relay/grpc_gen"
mkdir -p "$AB_OUT"
touch "$AB_OUT/__init__.py"

cd "$ROOT_DIR/agent-boot"
"${UV_RUN[@]}" -m grpc_tools.protoc \
  --python_out="$AB_OUT" \
  --grpc_python_out="$AB_OUT" \
  --proto_path="$PROTO_DIR" \
  "$PROTO_DIR/relay.proto"

sed -i '' 's/^import relay_pb2/from . import relay_pb2/' "$AB_OUT/relay_pb2_grpc.py" 2>/dev/null || \
sed -i 's/^import relay_pb2/from . import relay_pb2/' "$AB_OUT/relay_pb2_grpc.py"

echo "  agent-boot:  $AB_OUT"

# ── media-adapter (Go) ────────────────────────────────────────────────────────
# Separate toolchain: grpc_tools.protoc has no Go plugin, so this needs protoc
# plus protoc-gen-go/protoc-gen-go-grpc on PATH. It used to be a manual step and
# the Go stubs silently drifted from the proto; skipped with a loud warning
# rather than failing, so the Python half still regenerates without the toolchain.
GO_OUT="$ROOT_DIR/agent-boot/media-adapter/internal/grpcapi/relaypb"
# `go install` drops the plugins in GOPATH/bin, which is on nobody's PATH by
# default, and protoc only finds them by name on PATH. Without this the branch
# silently skips on a machine that has everything installed.
if command -v go &>/dev/null; then
  PATH="$(go env GOBIN):$(go env GOPATH)/bin:$PATH"
fi
if command -v protoc &>/dev/null && command -v protoc-gen-go &>/dev/null \
  && command -v protoc-gen-go-grpc &>/dev/null; then
  # go_package is an absolute module path, so --go_opt=module strips it back to
  # a bare relay.pb.go in $GO_OUT instead of recreating the tree underneath.
  protoc \
    --proto_path="$PROTO_DIR" \
    --go_out="$GO_OUT" \
    --go_opt=module=devicefarm/media-adapter/internal/grpcapi/relaypb \
    --go-grpc_out="$GO_OUT" \
    --go-grpc_opt=module=devicefarm/media-adapter/internal/grpcapi/relaypb \
    "$PROTO_DIR/relay.proto"
  echo "  media-adapter (Go): $GO_OUT"
else
  echo "  media-adapter (Go): SKIPPED — Go stubs are now stale. Install:" >&2
  echo "    brew install protobuf" >&2
  echo "    go install google.golang.org/protobuf/cmd/protoc-gen-go@v1.36.11" >&2
  echo "    go install google.golang.org/grpc/cmd/protoc-gen-go-grpc@latest" >&2
fi

echo "Proto generation done."
