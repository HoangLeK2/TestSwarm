from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

Bounds = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class SocialActionObservation:
    """Platform-neutral view of one social action on the current screen."""

    state: str
    target_bounds: Bounds | None = None
    matched_label: str | None = None
    satisfied: bool = False

    @property
    def is_satisfied(self) -> bool:
        return self.satisfied


class SocialActionAdapter(Protocol):
    """Adapter boundary; adapters inspect only the screen given by the scenario."""

    platform: str

    def observe(
        self,
        *,
        action_type: str,
        action: str,
        hierarchy_xml: str,
        near_bounds: Bounds | None = None,
    ) -> SocialActionObservation:
        ...


class UnsupportedSocialAction(ValueError):
    pass
