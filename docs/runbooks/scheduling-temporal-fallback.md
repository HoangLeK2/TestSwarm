# Scheduling Temporal Fallback Runbook

## Purpose

Use this runbook when `/api/schedules/system/status` reports `fallback_active=true` or the dashboard banner says `Fallback mode active`.

## Checks

1. Confirm Temporal health from the Temporal service and worker logs.
2. Query `GET /api/schedules/system/status` and record `temporal_available`, `queue_depth`, `tick_lag_seconds`, and `missed_ticks`.
3. Check recent schedule runs with `GET /api/schedules/{schedule_id}/runs?status=failed` for `error_code` and `trigger_source`.
4. Verify new runs created during the incident have `trigger_source="fallback"`.
5. If fallback remains active for more than 10 minutes, escalate to platform owner and pause high-SLA schedules with `POST /api/schedules/bulk/pause`.

## Recovery

1. Restore Temporal server and workers.
2. Confirm `/api/schedules/system/status` returns `temporal_available=true` and `fallback_active=false`.
3. Resume paused schedules with `POST /api/schedules/bulk/resume`.
4. Review schedule run history for missed or failed ticks and manually run safe catch-up jobs with `POST /api/schedules/{id}/run-now`.

## Evidence To Capture

- Status API response.
- Temporal worker logs around outage start and recovery.
- List of schedules paused/resumed.
- Failed schedule run IDs, linked execution IDs, and error codes.
