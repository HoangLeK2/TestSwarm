from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class ScenarioCreate(BaseModel):
    name: str = "Scenario"
    instructions: str = ""
    steps: list = []
    variables: dict = {}
    order: int = 0


class ScenarioUpdate(BaseModel):
    name: str | None = None
    instructions: str | None = None
    steps: list | None = None
    variables: dict | None = None
    order: int | None = None


class ScenarioOut(BaseModel):
    id: str
    campaign_id: str
    name: str
    instructions: str
    steps: list
    variables: dict
    order: int
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    name: str
    description: str = ""
    scenario: dict = {}
    variables: dict = {}
    device_ids: list[str] = []
    target_group_id: Optional[str] = None  # DF-004


class CampaignOut(BaseModel):
    id: str
    name: str
    description: str
    status: str
    scenario: Optional[dict] = None
    variables: dict = {}
    scenarios: list[ScenarioOut] = []
    user_id: Optional[str]
    created_at: datetime
    target_group_id: Optional[str] = None  # DF-004


class CampaignDeviceOut(BaseModel):
    id: str
    serial: str
    name: str
