
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
    ws_ping_interval: float = 30.0   # seconds between server pings
    ws_ping_timeout: float = 60.0   # seconds to wait for pong before closing


@dataclass
class PortsConfig:
    base_port: int = 20000
    stride: int = 10

    def for_device(self, index: int) -> "DevicePorts":
        base = self.base_port + index * self.stride
        return DevicePorts(
            u2=base + 0,
            minitouch=base + 1,
            stfservice=base + 2,
            stfagent=base + 3,
        )


@dataclass
class DevicePorts:
    u2: int
    minitouch: int
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
    minitouch_bin: str = "/data/local/tmp/minitouch"
    stf_package: str = "jp.co.cyberagent.stf"
    stf_apk_path: str = ""
    scrcpy_jar: str = "/opt/homebrew/share/scrcpy/scrcpy-server"
    scrcpy_max_fps: int = 30
    scrcpy_max_width: int = 800
    scrcpy_bitrate: int = 8_000_000  # H.264 bitrate bps (8 Mbps)


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
    target_app: str = ""


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

    op_delay = u2_raw.get("operation_delay", [0, 0.1])
    if isinstance(op_delay, list) and len(op_delay) == 2:
        op_delay = tuple(op_delay)
    else:
        op_delay = (0, 0.1)

    return Config(
        web=WebConfig(
            host=_get(web_raw, "host", "0.0.0.0"),
            port=_get(web_raw, "port", 8080),
            ws_ping_interval=float(_get(web_raw, "ws_ping_interval", 30.0)),
            ws_ping_timeout=float(_get(web_raw, "ws_ping_timeout", 60.0)),
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
            minitouch_bin=_get(device_raw, "minitouch_bin", "/data/local/tmp/minitouch"),
            stf_package=_get(device_raw, "stf_package", "jp.co.cyberagent.stf"),
            stf_apk_path=_get(device_raw, "stf_apk_path", ""),
            scrcpy_jar=_get(device_raw, "scrcpy_jar", "/opt/homebrew/share/scrcpy/scrcpy-server"),
            scrcpy_max_fps=_get(device_raw, "scrcpy_max_fps", 30),
            scrcpy_max_width=_get(device_raw, "scrcpy_max_width", 800),
            scrcpy_bitrate=_get(device_raw, "scrcpy_bitrate", 8_000_000),
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
        target_app=raw.get("target_app", ""),
    )


def setup_logging(cfg: LoggingConfig) -> None:
    level = getattr(logging, cfg.level.upper(), logging.INFO)
    logging.basicConfig(level=level, format=cfg.format)
