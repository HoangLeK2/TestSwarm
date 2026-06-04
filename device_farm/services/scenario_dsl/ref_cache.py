"""In-memory cache for org scenario run_scenario resolution (one batch DB load)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from db.models.enums import ScenarioKind
from services.scenario_dsl.step_family import COMPOSITION_RUN_SCENARIO


def steps_from_body(kind: str, body: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        return []
    if kind == ScenarioKind.GRAPH.value:
        nodes = body.get("nodes") or []
        return [n for n in nodes if isinstance(n, dict)]
    steps = body.get("steps") or []
    return [s for s in steps if isinstance(s, dict)]


def extract_run_scenario_id(step: dict[str, Any]) -> str | None:
    if str(step.get("type") or "") != COMPOSITION_RUN_SCENARIO:
        return None
    config = step.get("config") if isinstance(step.get("config"), dict) else step
    ref_id = str(config.get("scenario_id") or "").strip()
    return ref_id or None


@dataclass
class OrgScenarioRefCache:
    """Org-scoped scenario bodies for nested depth checks without N+1 queries."""

    _kind_by_id: dict[str, str]
    _body_by_id: dict[str, dict[str, Any] | None]

    @classmethod
    def empty(cls) -> OrgScenarioRefCache:
        return cls(_kind_by_id={}, _body_by_id={})

    def register(self, scenario_id: str, kind: str, body: dict[str, Any] | None) -> None:
        self._kind_by_id[scenario_id] = kind
        self._body_by_id[scenario_id] = body

    def steps_for(self, scenario_id: str) -> list[dict[str, Any]]:
        kind = self._kind_by_id.get(scenario_id, ScenarioKind.SEQUENCE.value)
        return steps_from_body(kind, self._body_by_id.get(scenario_id))

    def collect_ref_ids(self, steps: list[dict[str, Any]]) -> set[str]:
        refs: set[str] = set()
        for step in steps:
            ref_id = extract_run_scenario_id(step)
            if ref_id:
                refs.add(ref_id)
        return refs
