#!/bin/bash
# gen_proto.sh — Compile relay.proto for both device_farm and agent-boot.
# Run from the deviceFarmer/ root directory:
#   bash scripts/gen_proto.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
PROTO_DIR="$ROOT_DIR/proto"

echo "Proto source: $PROTO_DIR/relay.proto"

# ── device_farm ───────────────────────────────────────────────────────────────
DF_OUT="$ROOT_DIR/device_farm/runtime/transports/grpc_gen"
mkdir -p "$DF_OUT"
touch "$DF_OUT/__init__.py"

cd "$ROOT_DIR/device_farm"
python -m grpc_tools.protoc \
  --python_out="$DF_OUT" \
  --grpc_python_out="$DF_OUT" \
  --proto_path="$PROTO_DIR" \
  "$PROTO_DIR/relay.proto"

# Fix relative imports in generated files (grpc_tools generates broken imports)
sed -i '' 's/^import relay_pb2/from . import relay_pb2/' "$DF_OUT/relay_pb2_grpc.py" 2>/dev/null || \
sed -i 's/^import relay_pb2/from . import relay_pb2/' "$DF_OUT/relay_pb2_grpc.py"

echo "  device_farm: $DF_OUT"

# ── agent-boot ────────────────────────────────────────────────────────────────
AB_OUT="$ROOT_DIR/agent-boot/relay/grpc_gen"
mkdir -p "$AB_OUT"
touch "$AB_OUT/__init__.py"

cd "$ROOT_DIR/agent-boot"
python -m grpc_tools.protoc \
  --python_out="$AB_OUT" \
  --grpc_python_out="$AB_OUT" \
  --proto_path="$PROTO_DIR" \
  "$PROTO_DIR/relay.proto"

sed -i '' 's/^import relay_pb2/from . import relay_pb2/' "$AB_OUT/relay_pb2_grpc.py" 2>/dev/null || \
sed -i 's/^import relay_pb2/from . import relay_pb2/' "$AB_OUT/relay_pb2_grpc.py"

echo "  agent-boot:  $AB_OUT"
echo "Proto generation done."
