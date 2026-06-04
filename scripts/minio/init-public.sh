#!/bin/sh
# One-shot MinIO bootstrap: create bucket(s) and allow anonymous read (dev / local only).
# Mirrors production R2 public bucket — browser can load <img src="http://localhost:9000/..."> directly.
set -eu

ENDPOINT="${MINIO_ENDPOINT:-http://minio:9000}"
ALIAS="${MINIO_ALIAS:-local}"
USER="${MINIO_ROOT_USER:-minioadmin}"
PASS="${MINIO_ROOT_PASSWORD:-minioadmin}"
BUCKET="${MINIO_BUCKET:-device-farm}"

echo "minio-init: waiting for ${ENDPOINT} ..."
until mc alias set "${ALIAS}" "${ENDPOINT}" "${USER}" "${PASS}" >/dev/null 2>&1; do
  sleep 2
done

echo "minio-init: ensuring bucket ${BUCKET} ..."
mc mb "${ALIAS}/${BUCKET}" --ignore-existing

echo "minio-init: public download on ${BUCKET} (all objects) ..."
mc anonymous set download "${ALIAS}/${BUCKET}"

# Legacy URLs without bucket prefix treated content-screenshots as bucket name.
echo "minio-init: public download on content-screenshots (legacy path) ..."
mc mb "${ALIAS}/content-screenshots" --ignore-existing
mc anonymous set download "${ALIAS}/content-screenshots"

echo "minio-init: done. Example URL:"
echo "  ${MINIO_PUBLIC_BASE_URL:-http://localhost:9000}/${BUCKET}/content-screenshots/<file>.jpg"
