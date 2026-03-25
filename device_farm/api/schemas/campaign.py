from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ScenarioCreate(BaseModel):
    name: str = "Scenario"
    instructions: str = ""
    steps: list = []
    order: int = 0


class ScenarioUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    steps: list | None = None
    order: int | None = None


class ScenarioOut(BaseModel):
    id: str
    campaign_id: str
    name: str
    instructions: str
    steps: list
    order: int
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    scenario: dict = {}
    device_ids: list[str] = []


class CampaignOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    scenario: Optional[dict] = None
    scenarios: list[ScenarioOut] = []
    user_id: Optional[str]
    created_at: datetime


class CampaignDeviceOut(BaseModel):
    id: str
    serial: str
    name: str
