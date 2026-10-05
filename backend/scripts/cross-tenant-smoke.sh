#!/usr/bin/env bash
# DF-T-01-004 — local cross-tenant smoke (same set as CI).
set -euo pipefail
cd "$(dirname "$0")/.."
export TENANCY_STRICT_MODE="${TENANCY_STRICT_MODE:-true}"
python -m pytest -q \
  tests/test_tenancy_cross_tenant_smoke.py \
  tests/test_tenancy_org_disabled.py \
  tests/test_tenancy_devices_smoke.py \
  tests/test_personal_org.py
