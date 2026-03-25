"""
Backward-compatible re-exports. Prefer ``from core.config import …`` in new code.
"""

from __future__ import annotations

from core.config import (
    AdbConfig,
    Config,
    DatabaseConfig,
    DeviceConfig,
    DevicePorts,
    DispatcherConfig,
    LoggingConfig,
    PortsConfig,
    TaskConfig,
    U2Config,
    WatchdogConfig,
    WebConfig,
    WifiDenseposeConfig,
    load_config,
    setup_logging,
)

__all__ = [
    "AdbConfig",
    "Config",
    "DatabaseConfig",
    "DeviceConfig",
    "DevicePorts",
    "DispatcherConfig",
    "LoggingConfig",
    "PortsConfig",
    "TaskConfig",
    "U2Config",
    "WatchdogConfig",
    "WebConfig",
    "WifiDenseposeConfig",
    "load_config",
    "setup_logging",
]
