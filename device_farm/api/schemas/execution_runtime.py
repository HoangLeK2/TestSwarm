"""Execution runtime status for operator UI (DF-T-04-010)."""
from __future__ import annotations

from pydantic import BaseModel


class TemporalRuntimeInfo(BaseModel):
    enabled: bool
    server_url: str = ""
    namespace: str = "default"
    task_queue: str = ""


class CampaignRunRuntimeInfo(BaseModel):
    engine: str
    dispatch_source: str
    fallback_mode_active: bool = False
    note: str = ""


class ExecutionRuntimeOut(BaseModel):
    temporal: TemporalRuntimeInfo
    campaign_run: CampaignRunRuntimeInfo
