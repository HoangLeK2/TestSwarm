
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class ScenarioPreviewRequest(BaseModel):
    steps: List[Dict[str, Any]]


class TapRequest(BaseModel):
    x: int
    y: int


class SwipeRequest(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int
    ms: int = 300


class KeyRequest(BaseModel):
    key: str


class TapSelectorRequest(BaseModel):
    by: str  # "resource-id" | "text" | "xpath" | "class name"
    value: str


class HitTestRequest(BaseModel):
    x: int = 0
    y: int = 0
    rx: float = -1.0
    ry: float = -1.0


class InputTextRequest(BaseModel):
    text: str


class LongTapRequest(BaseModel):
    x: int
    y: int
    duration_ms: int = 800


class ScrollRequest(BaseModel):
    direction: str = "down"
    distance: float = 0.5


class OpenUrlRequest(BaseModel):
    url: str
    package: Optional[str] = None


class AdbRegisterRequest(BaseModel):
    """Body for app-after-scan: phone sends its IP so backend can connect via ADB."""

    ip: str
    port: int = 5555
    device_key: Optional[str] = None


class TaskRequest(BaseModel):
    fn_name: str = "example"
    priority: int = 5
    target: Optional[str] = None
    timeout: float = 300
    max_retries: int = 2


class FleetRunRequest(BaseModel):
    steps: List[Dict[str, Any]]
    filter_state: str = "READY"
    filter_model: Optional[str] = None
    max_devices: Optional[int] = None
    priority: int = 5
    timeout: float = 300
    max_retries: int = 1
    filter_group_id: Optional[str] = None
    filter_tags: Optional[str] = None


class ScrcpyAttachRequest(BaseModel):
    device_ip: str | None = None  # Auto-detected from DB if omitted
    adb_port: int = 5555
    enable_control: bool = True  # Enable scrcpy control channel for touch/key input


class StartSessionRequest(BaseModel):
    device_id: str
    user_id: Optional[str] = None


class EndSessionRequest(BaseModel):
    session_id: str
