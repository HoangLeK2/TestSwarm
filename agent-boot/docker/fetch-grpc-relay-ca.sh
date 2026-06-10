#!/usr/bin/env sh
# Fetch the TLS certificate chain served by the production gRPC relay endpoint.
# Run during `docker build` so customer images trust Let's Encrypt without manual PEM files.
set -eu

HOST="${1:-grpc-device-farm.tommadethis.app}"
PORT="${2:-443}"
OUT="${3:-/app/certs/grpc-relay-ca.pem}"

mkdir -p "$(dirname "$OUT")"

openssl s_client -showcerts -connect "${HOST}:${PORT}" -servername "$HOST" </dev/null 2>/dev/null \
  | sed -n '/BEGIN CERTIFICATE/,/END CERTIFICATE/p' > "$OUT"

if [ ! -s "$OUT" ]; then
  echo "error: failed to fetch gRPC relay TLS chain from ${HOST}:${PORT}" >&2
  exit 1
fi

echo "Fetched gRPC relay TLS chain for ${HOST}:${PORT} -> ${OUT}"
