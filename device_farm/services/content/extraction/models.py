"""Shared models and errors for Epic 06 extraction pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


class CaptureError(Exception):
    def __init__(self, message: str, *, code: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class OCRError(Exception):
    def __init__(self, message: str, *, code: str, partial_results: list | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.partial_results = partial_results or []


class HierarchyParseError(CaptureError):
    pass


class StrategyNotFoundError(Exception):
    def __init__(self, strategy: str, *, available: list[str]) -> None:
        super().__init__(f"Strategy not found: {strategy}")
        self.strategy = strategy
        self.available = available


class StrategyMismatchError(Exception):
    def __init__(self, reason: str, *, details: dict | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.details = details or {}


@dataclass(frozen=True)
class ExecutionCaptureContext:
    execution_id: str
    step_index: int
    kind: str
    org_id: str | None = None
    retention_class: str = "standard"


@dataclass
class CaptureHandle:
    image_bytes: bytes
    object_key: str | None
    size_bytes: int
    sha256: str
    captured_at: datetime
    mime_type: str = "image/png"
    artifact_id: str | None = None


@dataclass
class HierarchyHandle:
    xml_bytes: bytes
    object_key: str | None
    root: Any
    captured_at: datetime
    artifact_id: str | None = None


@dataclass
class HierarchyResult:
    data: list[dict[str, Any]] | dict[str, Any]
    raw_data: dict[str, Any]
    strategy_name: str
    latency_ms: float
    node_count: int = 0


@dataclass
class OCRExtractResult:
    results: list[dict[str, Any]] = field(default_factory=list)
    low_confidence_results: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: float = 0.0


class DeviceTransport(Protocol):
    def take_screenshot(self) -> bytes | None: ...

    def hierarchy_xml(self, *, force_refresh: bool = False) -> str | None: ...
