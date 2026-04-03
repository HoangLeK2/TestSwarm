
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import yaml



@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    # Disable uvicorn WS ping: concurrent ping + frame drains cause
    # "assert waiter is None or waiter.cancelled()" in websockets legacy.
    # App-level heartbeat (ws.py:heartbeat every 5s) keeps connections alive.
    ws_ping_interval: Optional[float] = None
    ws_ping_timeout: Optional[float] = None


@dataclass
class PortsConfig:
    base_port: int = 20000
    stride: int = 10

    def for_device(self, index: int) -> "DevicePorts":
        base = self.base_port + index * self.stride
        return DevicePorts(
            u2=base + 0,
            stfservice=base + 1,
            stfagent=base + 2,
        )


@dataclass
class DevicePorts:
    u2: int
    stfservice: int
    stfagent: int


@dataclass
class AdbConfig:
    path: str = "adb"
    ping_timeout: int = 5
    connect_timeout: int = 10
    enabled: bool = True


@dataclass
class DeviceConfig:
    index_file: str = "device_index.json"
    stf_package: str = "jp.co.cyberagent.stf"
    stf_apk_path: str = ""
    scrcpy_jar: str = "/opt/homebrew/share/scrcpy/scrcpy-server"
    scrcpy_max_fps: int = 30
    scrcpy_max_width: int = 800
    scrcpy_bitrate: int = 8_000_000  # H.264 bitrate bps (8 Mbps)
    scrcpy_control: bool = True      # Enable scrcpy control channel for touch/key/text


@dataclass
class WatchdogConfig:
    interval: int = 10
    max_retries: int = 3
    frame_stale_threshold: int = 5
    u2_health_timeout: int = 5


@dataclass
class DispatcherConfig:
    loop_interval: float = 0.5
    max_tasks_per_minute: int = 60


@dataclass
class TaskConfig:
    default_timeout: int = 300
    default_max_retries: int = 2
    default_priority: int = 5


@dataclass
class LoggingConfig:
    level: str = "INFO"
    format: str = "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"


@dataclass
class U2Config:
    screenshot_interval: float = 0.25
    implicitly_wait: float = 10.0
    wait_timeout: float = 20.0
    operation_delay: Tuple[float, float] = (0, 0.1)


@dataclass
class WifiDenseposeConfig:
    """WiFi-DensePose integration: link from dashboard to WiFi sensing UI."""
    enabled: bool = False
    url: str = "http://localhost:3000"


@dataclass
class StreamingConfig:
    """Streaming mode controls how video is delivered to the browser.

    "periodic"   — JPEG screenshot polled every `dashboard_interval` seconds.
                   Low CPU, high latency (~3s). Good for monitoring dashboards.
    "continuous" — H264 WebCodecs relay via scrcpy. Raw AVCC bytes sent to browser;
                   VideoDecoder decodes in-browser (zero server-side decode per frame).
                   Typical latency: 50-100ms. Requires scrcpy-server on device.
    """
    mode: str = "periodic"             # "periodic" | "continuous"
    dashboard_interval: float = 3.0    # seconds between screenshots (periodic mode only)


@dataclass
class DatabaseConfig:
    """PostgreSQL connection config. Can also be set via DATABASE_URL env var."""
    url: str = ""           # Full DSN — overrides host/port/name/user/password
    host: str = "localhost"
    port: int = 5432
    name: str = "device_farm"
    user: str = "postgres"
    password: str = "postgres"
    enabled: bool = False   # Set True to enable PostgreSQL integration


@dataclass
class TemporalConfig:
    """Temporal workflow engine config (DF-002).

    Set enabled: true to use Temporal for durable campaign workflows.
    When disabled (default), campaigns fall back to the in-process TaskQueue.
    Requires Temporal Server: docker run -p 7233:7233 temporalio/auto-setup:latest
    """
    enabled: bool = False                    # Set true only when Temporal server is running
    server_url: str = "localhost:7233"       # Temporal gRPC endpoint
    namespace: str = "default"
    task_queue: str = "device-scenario"
    worker_count: int = 1                    # parallel worker threads per process; each has own event loop + thread pool
    worker_max_concurrent_activities: int = 10
    worker_max_concurrent_workflows: int = 50
    workflow_execution_timeout: int = 3600   # seconds
    activity_start_to_close_timeout: int = 60  # seconds
    activity_retry_max_attempts: int = 3
    activity_retry_initial_interval: float = 1.0
    activity_retry_max_interval: float = 30.0
    activity_retry_backoff: float = 2.0


@dataclass
class Config:
    web: WebConfig = field(default_factory=WebConfig)
    ports: PortsConfig = field(default_factory=PortsConfig)
    adb: AdbConfig = field(default_factory=AdbConfig)
    device: DeviceConfig = field(default_factory=DeviceConfig)
    watchdog: WatchdogConfig = field(default_factory=WatchdogConfig)
    dispatcher: DispatcherConfig = field(default_factory=DispatcherConfig)
    task: TaskConfig = field(default_factory=TaskConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    u2: U2Config = field(default_factory=U2Config)
    wifi_densepose: WifiDenseposeConfig = field(default_factory=WifiDenseposeConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    streaming: StreamingConfig = field(default_factory=StreamingConfig)
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    target_app: str = ""
    force_u2_mode: bool = False


def _build_temporal_config(raw: dict) -> TemporalConfig:
    """Build TemporalConfig from YAML, with env var overrides for Docker."""
    cfg = TemporalConfig(
        **{k: v for k, v in raw.items() if k in TemporalConfig.__dataclass_fields__}
    )
    # Allow env override for Docker: TEMPORAL_SERVER_URL=temporal:7233
    env_url = os.environ.get("TEMPORAL_SERVER_URL")
    if env_url:
        cfg.server_url = env_url
    env_ns = os.environ.get("TEMPORAL_NAMESPACE")
    if env_ns:
        cfg.namespace = env_ns
    env_queue = os.environ.get("TEMPORAL_TASK_QUEUE")
    if env_queue:
        cfg.task_queue = env_queue
    env_wc = os.environ.get("TEMPORAL_WORKER_COUNT")
    if env_wc:
        try:
            cfg.worker_count = max(1, int(env_wc))
        except ValueError:
            pass
    return cfg


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        return Config()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def _get(section: dict, key: str, default):
        return section.get(key, default)

    web_raw = raw.get("web", {})
    ports_raw = raw.get("ports", {})
    adb_raw = raw.get("adb", {})
    device_raw = raw.get("device", {})
    watchdog_raw = raw.get("watchdog", {})
    dispatcher_raw = raw.get("dispatcher", {})
    task_raw = raw.get("task", {})
    logging_raw = raw.get("logging", {})
    u2_raw = raw.get("u2", {})
    wd_raw = raw.get("wifi_densepose", {})
    streaming_raw = raw.get("streaming", {})

    op_delay = u2_raw.get("operation_delay", [0, 0.1])
    if isinstance(op_delay, list) and len(op_delay) == 2:
        op_delay = tuple(op_delay)
    else:
        op_delay = (0, 0.1)

    return Config(
        web=WebConfig(
            host=_get(web_raw, "host", "0.0.0.0"),
            port=_get(web_raw, "port", 8080),
            ws_ping_interval=None,  # disabled: concurrent drain assertion in websockets legacy
            ws_ping_timeout=None,
        ),
        ports=PortsConfig(
            base_port=_get(ports_raw, "base_port", 20000),
            stride=_get(ports_raw, "stride", 10),
        ),
        adb=AdbConfig(
            path=_get(adb_raw, "path", "adb"),
            ping_timeout=_get(adb_raw, "ping_timeout", 5),
            connect_timeout=_get(adb_raw, "connect_timeout", 10),
            enabled=_get(adb_raw, "enabled", True),
        ),
        device=DeviceConfig(
            index_file=_get(device_raw, "index_file", "device_index.json"),
            stf_package=_get(device_raw, "stf_package", "jp.co.cyberagent.stf"),
            stf_apk_path=_get(device_raw, "stf_apk_path", ""),
            scrcpy_jar=_get(device_raw, "scrcpy_jar", "/opt/homebrew/share/scrcpy/scrcpy-server"),
            scrcpy_max_fps=_get(device_raw, "scrcpy_max_fps", 30),
            scrcpy_max_width=_get(device_raw, "scrcpy_max_width", 800),
            scrcpy_bitrate=_get(device_raw, "scrcpy_bitrate", 8_000_000),
            scrcpy_control=bool(_get(device_raw, "scrcpy_control", True)),
        ),
        watchdog=WatchdogConfig(
            interval=_get(watchdog_raw, "interval", 10),
            max_retries=_get(watchdog_raw, "max_retries", 3),
            frame_stale_threshold=_get(watchdog_raw, "frame_stale_threshold", 5),
            u2_health_timeout=_get(watchdog_raw, "u2_health_timeout", 5),
        ),
        dispatcher=DispatcherConfig(
            loop_interval=_get(dispatcher_raw, "loop_interval", 0.5),
            max_tasks_per_minute=_get(dispatcher_raw, "max_tasks_per_minute", 60),
        ),
        task=TaskConfig(
            default_timeout=_get(task_raw, "default_timeout", 300),
            default_max_retries=_get(task_raw, "default_max_retries", 2),
            default_priority=_get(task_raw, "default_priority", 5),
        ),
        logging=LoggingConfig(
            level=_get(logging_raw, "level", "INFO"),
            format=_get(logging_raw, "format",
                        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"),
        ),
        u2=U2Config(
            screenshot_interval=_get(u2_raw, "screenshot_interval", 0.25),
            implicitly_wait=_get(u2_raw, "implicitly_wait", 10.0),
            wait_timeout=_get(u2_raw, "wait_timeout", 20.0),
            operation_delay=op_delay,
        ),
        wifi_densepose=WifiDenseposeConfig(
            enabled=_get(wd_raw, "enabled", False),
            url=_get(wd_raw, "url", "http://localhost:3000"),
        ),
        database=DatabaseConfig(
            **{k: v for k, v in raw.get("database", {}).items()
               if k in DatabaseConfig.__dataclass_fields__}
        ),
        streaming=StreamingConfig(
            mode=_get(streaming_raw, "mode", "periodic"),
            dashboard_interval=float(_get(streaming_raw, "dashboard_interval", 3.0)),
        ),
        temporal=_build_temporal_config(raw.get("temporal", {})),
        target_app=raw.get("target_app", ""),
        force_u2_mode=bool(raw.get("force_u2_mode", False)),
    )


def setup_logging(cfg: LoggingConfig) -> None:
    level = getattr(logging, cfg.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=cfg.format)
