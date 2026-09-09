"""Prometheus metrics definitions for Device Farm."""
from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

# ── Device metrics ──
devices_online = Gauge(
    "device_farm_devices_online",
    "Number of online devices",
)
devices_by_state = Gauge(
    "device_farm_devices_by_state",
    "Devices grouped by state",
    ["state"],
)

# ── Relay metrics ──
relay_agents_connected = Gauge(
    "device_farm_relay_agents_connected",
    "Number of connected relay agents",
)
relay_devices_total = Gauge(
    "device_farm_relay_devices_total",
    "Total devices registered via relay",
)
relay_fsm_queue_depth = Gauge(
    "device_farm_relay_fsm_queue_depth",
    "Pending relay→device-FSM events waiting in the pump",
)
relay_fsm_events_total = Counter(
    "device_farm_relay_fsm_events_total",
    "Relay FSM events written by the pump",
    ["kind"],  # online | offline
)
relay_fsm_dropped_total = Counter(
    "device_farm_relay_fsm_dropped_total",
    "Relay FSM events dropped because the pump queue was full",
)
relay_fsm_batch_seconds = Histogram(
    "device_farm_relay_fsm_batch_seconds",
    "Relay FSM pump batch duration in seconds",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

# ── Edge content ingestion ──
edge_ingest_rows_total = Counter(
    "device_farm_edge_ingest_rows_total",
    "Rows submitted by relay agents for farm-side persistence",
    ["kind", "status"],
)
edge_ingest_duration_seconds = Histogram(
    "device_farm_edge_ingest_duration_seconds",
    "Farm-side edge ingest transaction duration in seconds",
    ["kind"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)
edge_ingest_batch_bytes = Histogram(
    "device_farm_edge_ingest_batch_bytes",
    "Serialized edge ingest batch size in bytes",
    buckets=[1024, 4096, 16384, 65536, 262144, 524288, 1048576, 4194304, 16777216],
)
edge_ingest_rejected_total = Counter(
    "device_farm_edge_ingest_rejected_total",
    "Edge ingest batches rejected before persistence",
    ["reason"],
)

# ── Task / Dispatch metrics ──
task_queue_depth = Gauge(
    "device_farm_task_queue_depth",
    "Number of pending tasks in queue",
)
tasks_dispatched_total = Counter(
    "device_farm_tasks_dispatched_total",
    "Total tasks dispatched",
    ["status"],  # success | failure | timeout
)
task_duration_seconds = Histogram(
    "device_farm_task_duration_seconds",
    "Task execution duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

# ── WebSocket / Streaming ──
ws_clients_connected = Gauge(
    "device_farm_ws_clients_connected",
    "Active WebSocket dashboard clients",
)
frame_drops_total = Counter(
    "device_farm_frame_drops_total",
    "Frames dropped due to full send queue",
    ["serial"],
)

# ── Account FSM (DF-T-07-005) ──
account_state_gauge = Gauge(
    "account_state_total",
    "Current account count by platform and FSM state",
    ["platform", "state"],
)
state_transition_total = Counter(
    "state_transition_total",
    "Account FSM transitions",
    ["from_state", "to_state", "reason_code"],
)

# ── Device FSM (DF-T-02-002, DF-T-02-005) ──
fsm_transition_count = Counter(
    "fsm_transition_count",
    "Device FSM transitions",
    ["from_state", "to_state"],
)
fsm_illegal_transition_count = Counter(
    "fsm_illegal_transition_count",
    "Rejected illegal device FSM transitions",
)
fsm_event_dedup_count = Counter(
    "fsm_event_dedup_count",
    "Deduped duplicate device FSM events (same event_id)",
)
device_dead_count = Counter(
    "device_dead_count",
    "Devices marked DEAD by control plane",
    ["reason"],
)
device_state_count = Gauge(
    "device_state_count",
    "Devices grouped by control-plane FSM state",
    ["state"],
)

# ── Account action ledger reconciliation ──
account_action_reconcile_runs_total = Counter(
    "device_farm_account_action_reconcile_runs_total",
    "Account action reconciliation runs by outcome",
    ["status"],
)
account_actions_reconciled_total = Counter(
    "device_farm_account_actions_reconciled_total",
    "Account actions marked stale by reconciliation",
)
account_action_reconcile_duration_seconds = Histogram(
    "device_farm_account_action_reconcile_duration_seconds",
    "Account action reconciliation pass duration",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10],
)
# An action that happened on the phone but could not be written to the ledger is
# a silent audit hole: the step still succeeds, so nothing else surfaces it.
account_action_record_failed_total = Counter(
    "device_farm_account_action_record_failed_total",
    "Ledger writes that failed after the action was already performed",
    ["context"],
)

# ── Fleet stats (DF-T-02-013) ──
fleet_stats_duration_seconds = Histogram(
    "device_farm_fleet_stats_duration_seconds",
    "Fleet stats endpoint latency in seconds",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)
fleet_stats_requests_total = Counter(
    "device_farm_fleet_stats_requests_total",
    "Fleet stats endpoint requests",
    ["has_group_filter", "has_relay_filter"],
)

# ── Device lifecycle WS stream (DF-T-02-015) ──
lifecycle_ws_clients_connected = Gauge(
    "device_farm_lifecycle_ws_clients_connected",
    "Active /ws/lifecycle dashboard clients",
)
lifecycle_ws_backpressure_total = Counter(
    "device_farm_lifecycle_ws_backpressure_total",
    "Lifecycle WS send queue full events (consumer slow)",
    ["org_id"],
)
lifecycle_ws_events_sent_total = Counter(
    "device_farm_lifecycle_ws_events_sent_total",
    "Lifecycle WS messages delivered to clients",
    ["event_type"],
)

# ── Execution control (DF-T-04-016) ──
execution_control_total = Counter(
    "device_farm_execution_control_total",
    "Execution/campaign pause, resume, cancel operations",
    ["action", "effective"],
)
execution_control_duration_seconds = Histogram(
    "device_farm_execution_control_duration_seconds",
    "Wall time for execution control handlers",
    ["action"],
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
)

# ── Org scenario library (DF-T-04-001) ──
scenario_created_total = Counter(
    "scenario_created_count",
    "Org-scoped scenarios created",
)
scenario_archived_total = Counter(
    "scenario_archived_count",
    "Org-scoped scenarios archived",
)

# ── Org-scoped campaigns (DF-T-04-006) ──
campaign_created_total = Counter(
    "campaign_created_count",
    "Org-scoped campaigns created",
)
campaign_archived_total = Counter(
    "campaign_archived_count",
    "Org-scoped campaigns archived",
)
campaign_status_transition_total = Counter(
    "campaign_status_transition_count",
    "Campaign lifecycle FSM transitions",
    ["from_status", "to_status"],
)

# ── Campaign dispatch fan-out (DF-T-04-008) ──
campaign_dispatch_targets_count = Counter(
    "campaign_dispatch_targets_count",
    "Devices snapshotted per campaign dispatch",
)
campaign_dispatch_claim_fail_count = Counter(
    "campaign_dispatch_claim_fail_count",
    "Device claim failures during campaign dispatch",
)
campaign_dispatch_duration_seconds = Histogram(
    "campaign_dispatch_duration_seconds",
    "Wall time for campaign fan-out dispatch handler",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
)
campaign_dispatch_http_duration_seconds = Histogram(
    "campaign_dispatch_http_duration_seconds",
    "End-to-end campaign dispatch HTTP handler wall time",
    buckets=[0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30, 60],
)
campaign_dispatch_phase_duration_seconds = Histogram(
    "campaign_dispatch_phase_duration_seconds",
    "Campaign dispatch wall time by bounded internal phase",
    ["phase"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 30],
)

# ── Campaign account binding (DF-T-04-009) ──
campaign_account_fallback_triggered_count = Counter(
    "campaign_account_fallback_triggered_count",
    "Legacy implicit primary-account fallback triggers (should stay 0 on Epic 04 path)",
)
campaign_account_resolve_batch_size = Histogram(
    "campaign_account_resolve_batch_size",
    "Distinct accounts loaded per campaign dispatch fan-out",
    buckets=[0, 1, 2, 5, 10, 25, 50, 100, 250, 500],
)
# Metric names stay Facebook-flavoured so existing dashboards keep working;
# the platform label is what carries the second platform.
facebook_session_guard_decisions_total = Counter(
    "facebook_session_guard_decisions_total",
    "Platform session guard decisions",
    ["platform", "mode", "outcome", "reason"],
)
facebook_readiness_checks_total = Counter(
    "facebook_readiness_checks_total",
    "Platform readiness checks",
    ["platform", "status", "reason"],
)
facebook_login_attempts_total = Counter(
    "facebook_login_attempts_total",
    "Facebook login attempt state transitions",
    ["state", "reason"],
)

# ── Step retry (DF-T-04-011) ──
step_retry_attempt_count = Counter(
    "step_retry_attempt_count",
    "Step retry attempts before success or exhaustion",
    ["step_type", "reason"],
)
step_retry_backoff_capped_count = Counter(
    "step_retry_backoff_capped_count",
    "Step retry waits capped at MAX_BACKOFF_MS",
)

# ── DLQ lifecycle (DF-T-04-012) ──
dlq_opened_total = Counter(
    "dlq_opened_total",
    "Executions moved to DLQ after terminal failure",
)
dlq_replayed_total = Counter(
    "dlq_replayed_total",
    "DLQ entries replayed into a new execution",
)
dlq_closed_total = Counter(
    "dlq_closed_total",
    "DLQ entries closed by an operator",
)

# ── Execution event stream (DF-T-04-013) ──
execution_events_published_total = Counter(
    "execution_events_published_total",
    "Execution domain events published to bus/broker",
    ["event_type"],
)
execution_event_outbox_lag_seconds = Gauge(
    "execution_event_outbox_lag_seconds",
    "Age of oldest unpublished execution event in outbox (seconds)",
)
execution_event_outbox_backlog = Gauge(
    "execution_event_outbox_backlog",
    "Number of unpublished execution events waiting in the outbox",
)
execution_event_outbox_batch_duration_seconds = Histogram(
    "execution_event_outbox_batch_duration_seconds",
    "Wall time to claim and publish one execution-event outbox batch",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)
execution_event_outbox_batch_size = Histogram(
    "execution_event_outbox_batch_size",
    "Execution events claimed by one outbox poll",
    buckets=[0, 1, 5, 10, 25, 50, 100, 200, 500],
)
execution_event_outbox_publish_failures_total = Counter(
    "execution_event_outbox_publish_failures_total",
    "Execution event broker publication failures",
)
execution_event_bus_backpressure_total = Counter(
    "execution_event_bus_backpressure_total",
    "SSE subscriber queues full — event dropped from live fan-out",
)

# ── Scheduling (DF-E-05) ──
schedule_fallback_active = Gauge(
    "device_farm_schedule_fallback_active",
    "Whether scheduling fallback mode is active",
)
schedule_queue_depth = Gauge(
    "device_farm_schedule_queue_depth",
    "Scheduler-visible dispatch queue depth",
)
schedule_tick_lag_seconds = Gauge(
    "device_farm_schedule_tick_lag_seconds",
    "Observed scheduling tick lag in seconds",
)
schedule_missed_ticks_total = Counter(
    "device_farm_schedule_missed_ticks_total",
    "Schedule ticks missed by scheduler",
)
schedule_dispatch_success_total = Counter(
    "device_farm_schedule_dispatch_success_total",
    "Schedule dispatches finalized successfully",
)
schedule_dispatch_failed_total = Counter(
    "device_farm_schedule_dispatch_failed_total",
    "Schedule dispatches finalized with failure",
)
schedule_starvation_total = Counter(
    "device_farm_schedule_starvation_total",
    "Schedule fairness starvation decisions",
)

# ── Step capture (DF-T-04-014) ──
capture_success_total = Counter(
    "capture_success_total",
    "Successful pre/post/fail step captures",
    ["phase"],
)
capture_failure_total = Counter(
    "capture_failure_total",
    "Failed step captures (fail-soft unless require_capture)",
    ["phase"],
)
capture_skipped_throttle_total = Counter(
    "capture_skipped_throttle_total",
    "Steps skipped by org capture_throttle policy",
)

# ── Epic 06 content extraction (DF-E-06) ──
content_type_validate_total = Counter(
    "content_type_validate_total",
    "Content type registry validation outcomes",
    ["result"],
)
content_dedup_hit_total = Counter(
    "content_dedup_hit_total",
    "External-id dedup hits in collection scope",
    ["collection", "platform", "action"],
)
content_item_insert_total = Counter(
    "content_item_insert_total",
    "Content items persisted",
    ["platform", "content_type"],
)
extraction_latency_ms = Histogram(
    "extraction_latency_ms",
    "Extraction engine latency in milliseconds",
    ["engine"],
    buckets=[100, 250, 500, 1000, 2000, 3000, 5000, 8000, 15000],
)
capture_latency_ms = Histogram(
    "capture_latency_ms",
    "Extraction capture latency in milliseconds",
    ["kind", "persist"],
    buckets=[50, 100, 250, 500, 1000, 1500, 3000, 5000],
)
ocr_latency_ms = Histogram(
    "ocr_latency_ms",
    "OCR extraction latency in milliseconds",
    buckets=[100, 500, 1000, 2000, 5000, 10000, 30000],
)
hierarchy_latency_ms = Histogram(
    "hierarchy_latency_ms",
    "Hierarchy extraction latency in milliseconds",
    buckets=[50, 100, 250, 500, 1000, 2000, 3000, 10000],
)
hierarchy_node_count = Histogram(
    "hierarchy_node_count",
    "Parsed hierarchy node count",
    buckets=[10, 50, 100, 250, 500, 1000, 2500, 5000],
)
artifact_cleanup_deleted_total = Counter(
    "artifact_cleanup_deleted_total",
    "Artifacts soft-deleted by retention job",
)
artifact_cleanup_bytes_freed = Counter(
    "artifact_cleanup_bytes_freed",
    "Artifact bytes removed by retention job",
)
artifact_cleanup_duration_seconds = Histogram(
    "artifact_cleanup_duration_seconds",
    "Artifact retention cleanup duration",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)
artifact_pinned_total = Counter(
    "artifact_pinned_total",
    "Executions pinned to skip artifact retention",
)
