"""Campaign domain errors (shared by service + lifecycle layers)."""
from __future__ import annotations


class CampaignError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class CampaignDuplicateNameError(CampaignError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Campaign name already exists: {name}", code="CAMPAIGN_NAME_DUPLICATE")


class CampaignNotFoundError(CampaignError):
    def __init__(self) -> None:
        super().__init__("Campaign not found", code="CAMPAIGN_NOT_FOUND")


class CampaignRunningError(CampaignError):
    def __init__(self) -> None:
        super().__init__(
            "Campaign is running; cancel before delete",
            code="CAMPAIGN_RUNNING",
        )


class CampaignValidationError(CampaignError):
    pass
