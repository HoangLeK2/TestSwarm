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
