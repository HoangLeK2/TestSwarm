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
