"""Capacity planning report schemas (DF-T-02-010)."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class DeviceIdBreakdownOut(BaseModel):
    db_id: str
    device_serial: str
    adb_serial: Optional[str] = None
    relay_serial: Optional[str] = None


class CapacityStateBreakdownOut(BaseModel):
    total: int = 0
    available: int = 0
    busy: int = 0
    dead: int = 0
    reconnecting: int = 0
    connecting: int = 0
    unknown: int = 0


class CapacityGroupBreakdownOut(BaseModel):
    group_id: str
    total: int
    available: int
    busy: int
    dead: int


class CapacityRelayBreakdownOut(BaseModel):
    relay_host: str
    total: int
    available: int
    busy: int
    dead: int


class CapacityReportOut(BaseModel):
    filters: dict[str, Optional[str]]
    summary: CapacityStateBreakdownOut
    by_state: dict[str, int]
    by_group: list[CapacityGroupBreakdownOut] = Field(default_factory=list)
    by_relay: list[CapacityRelayBreakdownOut] = Field(default_factory=list)
    sample_devices: list[DeviceIdBreakdownOut] = Field(default_factory=list)
    devices_scanned: int = 0
    latency_ms: float = 0.0
