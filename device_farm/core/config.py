
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import yaml

log = logging.getLogger(__name__)



@dataclass
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    cors_allow_all: bool = False
    cors_allowed_origins: List[str] = field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )
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
    index_file: str = "data/device_index.json"
    stf_package: str = "jp.co.cyberagent.stf"
    stf_apk_path: str = ""
    scrcpy_jar: str = "/opt/homebrew/share/scrcpy/scrcpy-server"
    scrcpy_max_fps: int = 30
    scrcpy_max_width: int = 800
    scrcpy_bitrate: int = 8_000_000       # H.264 bitrate bps for local ADB path (8 Mbps)
    scrcpy_relay_bitrate: int = 2_000_000 # H.264 bitrate for WiFi ADB relay path (keep ≤4Mbps to avoid IDR transfer lag)
    scrcpy_control: bool = True           # Enable scrcpy control socket for H264 IDR/keyframes
    u2_always_tunnel: bool = False        # Cloud/Docker: force WS tunnel for U2, never direct TCP to device_ip:7912


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
    # Viewer-gated default: do not start scrcpy unless a viewer explicitly attaches.
    auto_attach_scrcpy_on_connect: bool = False
    # When False, relay gRPC "device online" does not call attach_scrcpy_stream — use grid/control toggle or POST attach.
    auto_attach_scrcpy_on_relay_online: bool = False
    # When False, device-farm grid does not load MJPEG preview tiles (saves bandwidth server↔browser).
    dashboard_grid_preview_mjpeg: bool = True


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
class ObjectStorageConfig:
    """S3-compatible object storage (Cloudflare R2, MinIO, AWS S3, …) for screenshots.

    Set enabled: true and fill endpoint/keys to activate.
    Falls back to local filesystem when disabled (default).

    R2: endpoint = ``<ACCOUNT_ID>.r2.cloudflarestorage.com`` (no scheme), secure = true,
    region left empty uses ``auto`` automatically for R2 hosts.
    Public URLs: set public_base_url to your r2.dev URL or custom domain; set
    public_url_include_bucket false when the domain is already bound to one bucket
    (typical for R2 public access).
    """
    enabled: bool = False
    endpoint: str = ""
    access_key: str = ""
    secret_key: str = ""
    bucket: str = "device-farm"
    secure: bool = True
    # If set, URLs use public_base_url (see public_url_include_bucket).
    # Leave blank to use presigned URLs (1-week TTL).
    public_base_url: str = ""
    # When true: "<public_base_url>/<bucket>/<object>". When false: "<public_base_url>/<object>"
    # (use false for R2 r2.dev / custom domain at bucket root).
    public_url_include_bucket: bool = True
    # S3 region; empty string lets the client pick (R2 hosts use "auto" in minio_store).
    region: str = ""
    # Minimum JPEG size in bytes below which images are rejected as blank/black.
    # Blank frames compressed by minicap are typically < 2 KB.
    min_image_bytes: int = 3072


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
    workflow_execution_timeout: int = 0   # seconds; 0 = unlimited
    activity_start_to_close_timeout: int = 60  # seconds
    activity_retry_max_attempts: int = 3
    activity_retry_initial_interval: float = 1.0
    activity_retry_max_interval: float = 30.0
    activity_retry_backoff: float = 2.0


@dataclass
class RelayConfig:
    """gRPC ADB relay server (agent-boot/relay.py connects here)."""
    enabled: bool = False
    port: int = 50051
    api_key: str = ""   # set via RELAY_API_KEY env var or config.yaml
    tls_cert_file: str = ""
    tls_key_file: str = ""
    allow_insecure_grpc: bool = True


@dataclass
class RedisConfig:
    enabled: bool = False
    url: str = "redis://localhost:6379/0"
    prefix: str = "df:"


@dataclass
class AccountHistoryConfig:
    """Account profile timeline (account_events table)."""
    enabled: bool = True
    max_batch_size: int = 100
    max_pending: int = 1000
    retention_days: int = 90


@dataclass
class SafeModeConfig:
    """Operator-level switch for restricted / low-bandwidth deployments.

    read_only
        Reject every write method (POST/PUT/PATCH/DELETE) that would mutate
        scenarios, templates, devices, sessions, schedules, or campaigns.
        Auth endpoints stay reachable so the UI can still log in and browse.
    stream_hierarchy
        When false, /hierarchy, /ui_elements, and /hit_test return 503. The
        hierarchy XML is typically 10–50 KB per dump, so disabling is the
        cheapest way to cut bandwidth on observe-only setups.

    Env overrides: FARM_READ_ONLY=1, FARM_STREAM_HIERARCHY=0.
    """
    read_only: bool = False
    stream_hierarchy: bool = True


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
    object_storage: ObjectStorageConfig = field(default_factory=ObjectStorageConfig)
    relay: RelayConfig = field(default_factory=RelayConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    account_history: AccountHistoryConfig = field(default_factory=AccountHistoryConfig)
    safe_mode: SafeModeConfig = field(default_factory=SafeModeConfig)
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


def _normalize_object_storage_endpoint(raw_endpoint: str) -> str:
    ep = (raw_endpoint or "").strip()
    for prefix in ("https://", "http://"):
        if ep.lower().startswith(prefix):
            ep = ep[len(prefix) :]
    return ep.rstrip("/")


def _build_object_storage_config(raw: dict) -> ObjectStorageConfig:
    """Build ObjectStorageConfig from YAML ``object_storage`` / legacy ``minio`` + env."""
    legacy = raw.get("minio") if isinstance(raw.get("minio"), dict) else {}
    current = raw.get("object_storage") if isinstance(raw.get("object_storage"), dict) else {}
    merged = {**legacy, **current}
    cfg = ObjectStorageConfig(
        **{k: v for k, v in merged.items() if k in ObjectStorageConfig.__dataclass_fields__}
    )
    if cfg.endpoint:
        cfg.endpoint = _normalize_object_storage_endpoint(cfg.endpoint)

    # R2 (preferred), then legacy MinIO env names
    ep = (
        os.environ.get("R2_ENDPOINT")
        or os.environ.get("MINIO_ENDPOINT")
        or ""
    ).strip()
    if ep:
        cfg.endpoint = _normalize_object_storage_endpoint(ep)
        cfg.enabled = True

    access = (
        os.environ.get("R2_ACCESS_KEY_ID")
        or os.environ.get("R2_ACCESS_KEY")
        or os.environ.get("MINIO_ACCESS_KEY")
        or ""
    ).strip()
    if access:
        cfg.access_key = access

    secret = (
        os.environ.get("R2_SECRET_ACCESS_KEY")
        or os.environ.get("R2_SECRET_KEY")
        or os.environ.get("MINIO_SECRET_KEY")
        or ""
    ).strip()
    if secret:
        cfg.secret_key = secret

    bucket = (os.environ.get("R2_BUCKET") or os.environ.get("MINIO_BUCKET") or "").strip()
    if bucket:
        cfg.bucket = bucket

    pub = (os.environ.get("R2_PUBLIC_BASE_URL") or os.environ.get("MINIO_PUBLIC_BASE_URL") or "").strip()
    if pub:
        cfg.public_base_url = pub.rstrip("/")

    secure_raw = os.environ.get("R2_SECURE") or os.environ.get("MINIO_SECURE")
    if secure_raw is not None and str(secure_raw).strip() != "":
        cfg.secure = str(secure_raw).strip().lower() in ("1", "true", "yes", "on")

    region = (os.environ.get("R2_REGION") or "").strip()
    if region:
        cfg.region = region

    inc = os.environ.get("R2_PUBLIC_URL_INCLUDE_BUCKET")
    if inc is not None and str(inc).strip() != "":
        cfg.public_url_include_bucket = str(inc).strip().lower() in ("1", "true", "yes", "on")

    return cfg


def _build_relay_config(raw: dict) -> RelayConfig:
    """Build RelayConfig from YAML + env var overrides."""
    cfg = RelayConfig(
        **{k: v for k, v in raw.items() if k in RelayConfig.__dataclass_fields__}
    )
    if os.environ.get("RELAY_API_KEY"):
        cfg.api_key = os.environ["RELAY_API_KEY"]
    # Accept both RELAY_PORT (preferred) and RELAY_GRPC_PORT (legacy docker-compose name)
    _relay_port_env = os.environ.get("RELAY_PORT") or os.environ.get("RELAY_GRPC_PORT")
    if _relay_port_env:
        try:
            cfg.port = int(_relay_port_env)
        except ValueError:
            pass
    if os.environ.get("RELAY_TLS_CERT_FILE"):
        cfg.tls_cert_file = os.environ["RELAY_TLS_CERT_FILE"].strip()
    if os.environ.get("RELAY_TLS_KEY_FILE"):
        cfg.tls_key_file = os.environ["RELAY_TLS_KEY_FILE"].strip()
    allow_insecure = os.environ.get("RELAY_ALLOW_INSECURE_GRPC")
    if allow_insecure is not None and str(allow_insecure).strip() != "":
        cfg.allow_insecure_grpc = str(allow_insecure).strip().lower() in ("1", "true", "yes", "on")
    return cfg


def _build_database_config(raw: dict) -> DatabaseConfig:
    """YAML database section + ``DATABASE_URL`` env (Docker Compose sets this)."""
    cfg = DatabaseConfig(
        **{k: v for k, v in raw.items() if k in DatabaseConfig.__dataclass_fields__}
    )
    env_url = (os.environ.get("DATABASE_URL") or "").strip()
    if env_url:
        cfg.url = env_url
    return cfg


def _build_safe_mode_config(raw: dict) -> SafeModeConfig:
    """YAML safe_mode section + env overrides (FARM_READ_ONLY, FARM_STREAM_HIERARCHY)."""
    cfg = SafeModeConfig(
        **{k: v for k, v in raw.items() if k in SafeModeConfig.__dataclass_fields__}
    )
    env_ro = (os.environ.get("FARM_READ_ONLY") or "").strip().lower()
    if env_ro in {"1", "true", "yes", "on"}:
        cfg.read_only = True
    elif env_ro in {"0", "false", "no", "off"}:
        cfg.read_only = False
    env_sh = (os.environ.get("FARM_STREAM_HIERARCHY") or "").strip().lower()
    if env_sh in {"0", "false", "no", "off"}:
        cfg.stream_hierarchy = False
    elif env_sh in {"1", "true", "yes", "on"}:
        cfg.stream_hierarchy = True
    return cfg


def _build_redis_config(raw: dict) -> RedisConfig:
    """YAML redis section + ``REDIS_URL`` env override."""
    cfg = RedisConfig(
        **{k: v for k, v in raw.items() if k in RedisConfig.__dataclass_fields__}
    )
    env_url = (os.environ.get("REDIS_URL") or "").strip()
    if env_url:
        cfg.url = env_url
        cfg.enabled = True
    return cfg


def load_config(path: str = "config.yaml") -> Config:
    if not os.path.exists(path):
        return Config()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    def _get(section: dict, key: str, default):
        return section.get(key, default)

    def _as_bool(value, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, str):
            text = value.strip().lower()
            if text in {"1", "true", "yes", "on"}:
                return True
            if text in {"0", "false", "no", "off"}:
                return False
            return default
        return bool(value)

    web_raw = raw.get("web", {})
    ports_raw = raw.get("ports", {})
    adb_raw = raw.get("adb", {})
    device_raw = raw.get("device", {})
    watchdog_raw = raw.get("watchdog", {})
    dispatcher_raw = raw.get("dispatcher", {})
    task_raw = raw.get("task", {})
    logging_raw = raw.get("logging", {})
    u2_raw = raw.get("u2", {})
    u2_batch_raw = raw.get("u2_batch", {})
    wd_raw = raw.get("wifi_densepose", {})
    streaming_raw = raw.get("streaming", {})

    op_delay = u2_raw.get("operation_delay", [0, 0.1])
    if isinstance(op_delay, list) and len(op_delay) == 2:
        op_delay = tuple(op_delay)
    else:
        op_delay = (0, 0.1)

    def _normalize_cors_origins(raw_origins) -> list[str]:
        if not isinstance(raw_origins, list):
            return []
        allowed: list[str] = []
        for raw_origin in raw_origins:
            origin = str(raw_origin).strip()
            if not origin:
                continue
            # Reject wildcard-style origins to prevent accidental allow-all CORS.
            if origin == "*" or "*" in origin:
                log.warning("Ignoring unsafe CORS origin with wildcard: %s", origin)
                continue
            parsed = urlparse(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                log.warning("Ignoring invalid CORS origin: %s", origin)
                continue
            normalized = f"{parsed.scheme}://{parsed.netloc}"
            if normalized not in allowed:
                allowed.append(normalized)
        return allowed

    web_cors_allowed_origins = _get(web_raw, "cors_allowed_origins", None)
    if not isinstance(web_cors_allowed_origins, list):
        web_cors_allowed_origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    web_cors_allowed_origins = _normalize_cors_origins(web_cors_allowed_origins)

    env_cors_origins = os.environ.get("CORS_ALLOWED_ORIGINS", "").strip()
    if env_cors_origins:
        web_cors_allowed_origins = _normalize_cors_origins(env_cors_origins.split(","))

    if _as_bool(_get(u2_batch_raw, "enabled", False), False):
        os.environ.setdefault("U2_BATCH_ENABLED", "true")

    return Config(
        web=WebConfig(
            host=_get(web_raw, "host", "0.0.0.0"),
            port=_get(web_raw, "port", 8080),
            cors_allow_all=bool(
                str(os.environ.get("CORS_ALLOW_ALL", _get(web_raw, "cors_allow_all", False))).strip().lower()
                in ("1", "true", "yes", "on")
            ),
            cors_allowed_origins=web_cors_allowed_origins,
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
            index_file=_get(device_raw, "index_file", "data/device_index.json"),
            stf_package=_get(device_raw, "stf_package", "jp.co.cyberagent.stf"),
            stf_apk_path=_get(device_raw, "stf_apk_path", ""),
            scrcpy_jar=(
                os.environ.get("DEVICE_FARM_SCRCPY_JAR", "").strip()
                or _get(device_raw, "scrcpy_jar", "/opt/homebrew/share/scrcpy/scrcpy-server")
            ),
            scrcpy_max_fps=_get(device_raw, "scrcpy_max_fps", 30),
            scrcpy_max_width=_get(device_raw, "scrcpy_max_width", 800),
            scrcpy_bitrate=_get(device_raw, "scrcpy_bitrate", 8_000_000),
            scrcpy_relay_bitrate=_get(device_raw, "scrcpy_relay_bitrate", 2_000_000),
            scrcpy_control=_as_bool(_get(device_raw, "scrcpy_control", True), True),
            u2_always_tunnel=_as_bool(
                os.environ.get(
                    "DEVICE_FARM_U2_ALWAYS_TUNNEL",
                    _get(device_raw, "u2_always_tunnel", False),
                ),
                False,
            ),
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
        database=_build_database_config(raw.get("database", {})),
        streaming=StreamingConfig(
            mode=_get(streaming_raw, "mode", "periodic"),
            dashboard_interval=float(_get(streaming_raw, "dashboard_interval", 3.0)),
            auto_attach_scrcpy_on_connect=_as_bool(
                _get(
                    streaming_raw,
                    "auto_attach_scrcpy_on_connect",
                    _get(streaming_raw, "auto_attach_scrcpy", False),
                ),
                True,
            ),
            dashboard_grid_preview_mjpeg=_as_bool(
                _get(streaming_raw, "dashboard_grid_preview_mjpeg", True),
                True,
            ),
            auto_attach_scrcpy_on_relay_online=_as_bool(
                _get(streaming_raw, "auto_attach_scrcpy_on_relay_online", False),
                True,
            ),
        ),
        temporal=_build_temporal_config(raw.get("temporal", {})),
        object_storage=_build_object_storage_config(raw),
        relay=_build_relay_config(raw.get("relay", {})),
        redis=_build_redis_config(raw.get("redis", {})),
        account_history=AccountHistoryConfig(
            **{
                k: v
                for k, v in (raw.get("account_history") or {}).items()
                if k in AccountHistoryConfig.__dataclass_fields__
            }
        ),
        safe_mode=_build_safe_mode_config(raw.get("safe_mode", {})),
        target_app=raw.get("target_app", ""),
        force_u2_mode=bool(raw.get("force_u2_mode", False)),
    )


def setup_logging(cfg: LoggingConfig) -> None:
    import importlib
    from logging.handlers import TimedRotatingFileHandler
    from pathlib import Path

    structlog = importlib.import_module("structlog")

    class _TraceFileFilter(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            name = record.name or ""
            return (
                name == "scenario_trace"
                or name == "api_trace"
                or name.startswith("tasks.scenario")
                or name.startswith("tasks.scenario_task")
                or name.startswith("api.routes.device_control.scenarios")
                or name.startswith("api.routes")
                or name.startswith("web.server")
                or name.startswith("runtime.core.device_client")
            )

    level = getattr(logging, cfg.level.upper(), logging.INFO)
    log_dir = Path(os.getenv("FARM_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    scenario_log_path = Path(os.getenv("SCENARIO_LOG_FILE", str(log_dir / "scenario-trace.log")))
    if not scenario_log_path.is_absolute():
        scenario_log_path = log_dir / scenario_log_path
    scenario_log_path.parent.mkdir(parents=True, exist_ok=True)

    pre_chain = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
    ]
    from observability.logging import redact_event

    shared_processors = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
        redact_event,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
    ]

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.dev.ConsoleRenderer(colors=True),
            foreign_pre_chain=pre_chain,
        )
    )

    scenario_handler = TimedRotatingFileHandler(
        filename=str(scenario_log_path),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    scenario_handler.setLevel(level)
    scenario_handler.addFilter(_TraceFileFilter())
    scenario_handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=structlog.processors.JSONRenderer(),
            foreign_pre_chain=pre_chain,
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(console_handler)
    root.addHandler(scenario_handler)

    structlog.configure(
        processors=shared_processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
