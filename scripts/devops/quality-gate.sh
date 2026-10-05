#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCOPE="${1:-quick}"

log() {
  printf '\n==> %s\n' "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    printf 'Missing required command: %s\n' "$1" >&2
    exit 127
  fi
}

run_backend_quick() {
  require_cmd uv
  cd "$ROOT_DIR/backend"
  log "Backend compile check"
  uv run python -m compileall \
    api/routes/scenarios.py \
    services/campaign/account_resolver.py \
    services/org_scenario_io/serializer.py

  log "Workspace admin, phone allocation, and campaign binding regression"
  uv run --extra dev pytest -q \
    tests/test_workspace_admin_console.py \
    tests/test_epic04_campaign_account_binding.py \
    tests/test_epic04_campaign_device_binding.py \
    tests/test_campaign_dispatch_n2n.py
}

run_backend_campaign() {
  require_cmd uv
  cd "$ROOT_DIR/backend"
  log "Account, group, source, page, device, campaign workflow regression"
  uv run --extra dev pytest -q \
    tests/test_account_import.py \
    tests/test_device_account_routes_n2n.py \
    tests/test_account_groups_routes_n2n.py \
    tests/test_account_state_fsm.py \
    tests/test_account_verification.py \
    tests/test_account_target_runtime.py \
    tests/test_account_graph_step.py \
    tests/test_account_action_ledger.py \
    tests/test_account_events.py \
    tests/test_campaign_scenario_sources.py \
    tests/test_source_pool_step.py \
    tests/test_epic04_campaign_device_binding.py \
    tests/test_epic04_campaign_account_binding.py \
    tests/test_campaign_dispatch_n2n.py

  log "Epic04 campaign runtime regression"
  uv run --extra dev pytest -q \
    tests/test_epic04_campaign_device_binding.py \
    tests/test_epic04_execution_runtime.py \
    tests/test_epic04_scenario_dsl.py \
    tests/test_campaign_scenario_sources.py \
    tests/test_epic04_execution_event_stream.py \
    tests/test_epic04_preview_execution.py \
    tests/test_dlq_campaign_filter.py \
    tests/test_campaign_cancel.py \
    tests/test_epic04_execution_retry_policy.py \
    tests/test_epic04_campaign_entity.py \
    tests/test_epic04_temporal_step_retry.py \
    tests/test_campaign_heavy_benchmark_metrics.py \
    tests/test_campaign_dispatch_n2n.py \
    tests/test_epic04_scenario_io.py \
    tests/test_epic04_scenario_entity.py \
    tests/test_campaign_device_step_bottleneck_benchmark.py \
    tests/test_epic04_temporal_pause_resume.py \
    tests/test_content_campaign_ref.py \
    tests/test_epic04_workflow_durable_step_retry.py \
    tests/test_campaign_failure_classification.py \
    tests/test_campaign_aggregator_scheduler.py \
    tests/test_epic04_execution_steps.py \
    tests/test_epic04_campaign_account_binding.py \
    tests/test_epic04_dlq_lifecycle.py \
    tests/test_campaign_scenario_repeat_config.py \
    tests/test_epic04_campaign_lifecycle_fsm.py \
    tests/test_epic04_step_capture.py \
    tests/test_campaign_pipeline_harness.py \
    tests/test_epic04_scenario_validation.py
}

run_frontend() {
  require_cmd pnpm
  cd "$ROOT_DIR/front-end"
  log "Frontend typecheck"
  pnpm typecheck

  if [[ "${DF_SKIP_FRONTEND_BUILD:-0}" != "1" ]]; then
    log "Frontend production build"
    pnpm exec next build
  fi
}

run_compose_preflight() {
  require_cmd docker
  cd "$ROOT_DIR"
  if [[ ! -f .env ]]; then
    log "Skipping compose preflight because .env is not present"
    return 0
  fi
  log "Docker Compose config preflight"
  docker compose config --quiet
}

case "$SCOPE" in
  quick)
    run_backend_quick
    DF_SKIP_FRONTEND_BUILD="${DF_SKIP_FRONTEND_BUILD:-1}" run_frontend
    ;;
  backend)
    run_backend_quick
    ;;
  campaign)
    run_backend_campaign
    ;;
  frontend)
    run_frontend
    ;;
  compose)
    run_compose_preflight
    ;;
  full)
    run_backend_quick
    run_backend_campaign
    run_frontend
    run_compose_preflight
    ;;
  *)
    printf 'Usage: %s [quick|backend|campaign|frontend|compose|full]\n' "$0" >&2
    exit 2
    ;;
esac

log "DevOps quality gate passed: $SCOPE"
