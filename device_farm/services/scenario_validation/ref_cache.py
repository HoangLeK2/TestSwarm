"""In-memory cache for scenario reference resolution (one DB round-trip per campaign)."""

from __future__ import annotations

from typing import Any

from db.models.campaign import Scenario
from services.scenario_validation.step_index import StepIndex


class ScenarioRefCache:
    """Campaign-scoped scenario lookup and version existence checks."""

    __slots__ = (
        "_by_id",
        "_by_name",
        "_versions",
        "_index_by_id",
    )

    def __init__(
        self,
        scenarios: list[Scenario],
        *,
        version_pairs: list[tuple[str, int]] | None = None,
    ) -> None:
        self._by_id: dict[str, Scenario] = {s.id: s for s in scenarios}
        self._by_name: dict[str, Scenario] = {}
        for s in scenarios:
            if s.name not in self._by_name:
                self._by_name[s.name] = s
        self._versions: set[tuple[str, int]] = set(version_pairs or [])
        self._index_by_id: dict[str, StepIndex] = {}

    def register(self, scenario: Scenario | Any) -> None:
        """Overlay or add a scenario row (e.g. draft body on the row being edited)."""
        sid = scenario.id
        self._by_id[sid] = scenario
        self._by_name[scenario.name] = scenario
        self._index_by_id.pop(sid, None)

    def get_by_id(self, scenario_id: str) -> Scenario | None:
        return self._by_id.get(scenario_id)

    def get_by_name(self, name: str) -> Scenario | None:
        return self._by_name.get(name)

    def has_version(self, scenario_id: str, version: int) -> bool:
        return (scenario_id, version) in self._versions

    def index_for(self, scenario_id: str, steps: list[dict]) -> StepIndex:
        """Cached run_scenario index for a scenario's step tree."""
        cached = self._index_by_id.get(scenario_id)
        if cached is not None:
            return cached
        built = StepIndex.build(steps)
        self._index_by_id[scenario_id] = built
        return built


def steps_from_row(row: Any) -> list[dict]:
    steps = getattr(row, "steps", None)
    if steps is None and isinstance(row, dict):
        steps = row.get("steps")
    return list(steps or [])
