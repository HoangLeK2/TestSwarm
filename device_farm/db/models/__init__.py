"""
db.models package — SQLAlchemy ORM models grouped by domain.

Previously all models lived in a single db/models.py file. They are now
split into smaller modules for easier maintenance:

- user.py          — User
- organization.py  — Organization, OrganizationMember
- device.py        — Device, DeviceSession
- campaign.py      — Campaign, CampaignDevice
- crawl.py         — CrawlJob, CrawlPost
- account.py       — Account, DeviceAccount  (DF-007)
"""

from .user import User
from .organization import Organization, OrganizationMember
from .device import Device, DeviceSession
from .device_group import DeviceGroup, DeviceGroupMember
from .campaign import Campaign, CampaignDevice, Scenario
from .mcp_session import McpSession
from .crawl import CrawlJob, CrawlPost
from .scenario_template import ScenarioTemplate
from .account import Account, DeviceAccount

__all__ = [
    "User",
    "Organization",
    "OrganizationMember",
    "Device",
    "DeviceSession",
    "DeviceGroup",
    "DeviceGroupMember",
    "Campaign",
    "CampaignDevice",
    "Scenario",
    "McpSession",
    "CrawlJob",
    "CrawlPost",
    "ScenarioTemplate",
    "Account",
    "DeviceAccount",
]

