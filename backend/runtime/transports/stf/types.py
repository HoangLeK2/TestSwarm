from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BatteryInfo:
    status: str = "unknown"       # charging, discharging, full, not_charging, unknown
    health: str = "unknown"       # good, dead, overheat, over_voltage, cold, unspecified_failure
    source: str = "unknown"       # ac, usb, wireless
    level: int = -1               # 0-100
    scale: int = 100
    temp: float = 0.0             # Celsius
    voltage: float = 0.0          # Volts


@dataclass
class ConnectivityInfo:
    connected: bool = False
    type: str = ""                # wifi, mobile, ethernet
    subtype: str = ""             # LTE, HSPA, etc.
    failover: bool = False
    roaming: bool = False


@dataclass
class PhoneStateInfo:
    state: str = "unknown"        # in_service, out_of_service, emergency_only, power_off
    manual: bool = False
    operator: str = ""


@dataclass
class DisplayInfo:
    width: int = 0
    height: int = 0
    xdpi: float = 0.0
    ydpi: float = 0.0
    fps: float = 0.0
    density: float = 0.0
    rotation: int = 0             # 0, 90, 180, 270
    secure: bool = False

