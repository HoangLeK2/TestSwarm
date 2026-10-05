"""Org-scoped campaign service (DF-T-04-006)."""

from services.campaign.dispatcher import (
    CampaignDispatchError,
    CampaignDispatcher,
    dispatch_campaign,
    finish_fan_out_execution,
    release_execution_device_claim,
)
from services.campaign.errors import (
    CampaignDuplicateNameError,
    CampaignError,
    CampaignNotFoundError,
    CampaignRunningError,
    CampaignValidationError,
)
from services.campaign.override_resolver import merge_effective_vars
from services.campaign.service import (
    CampaignView,
    archive_campaign,
    create_campaign,
    get_campaign_for_org,
    list_campaigns_for_org,
    map_scenario_ref_error,
    update_campaign,
)

__all__ = [
    "CampaignDuplicateNameError",
    "CampaignError",
    "CampaignNotFoundError",
    "CampaignRunningError",
    "CampaignValidationError",
    "CampaignView",
    "CampaignDispatchError",
    "CampaignDispatcher",
    "archive_campaign",
    "create_campaign",
    "dispatch_campaign",
    "finish_fan_out_execution",
    "get_campaign_for_org",
    "list_campaigns_for_org",
    "map_scenario_ref_error",
    "merge_effective_vars",
    "release_execution_device_claim",
    "update_campaign",
]
