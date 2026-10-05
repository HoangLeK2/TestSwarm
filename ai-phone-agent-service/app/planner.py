from __future__ import annotations

from datetime import timedelta
from hashlib import sha256
from typing import Any, Protocol
from uuid import uuid4

from .contracts import (
    ActionProposal,
    ObservationRequest,
    PlanRequest,
    ScenarioDraft,
    ScenarioStep,
    utc_now,
)


class PlannerPort(Protocol):
    model_name: str
    model_revision: str

    def build_plan(self, request: PlanRequest) -> ScenarioDraft:
        ...

    def propose_action(
        self,
        observation: ObservationRequest,
        allowed_operations: set[str],
        step_index: int,
    ) -> ActionProposal:
        ...


class DeterministicPlanner:
    model_name = "deterministic-contract-planner"
    model_revision = "local-0.1"

    def build_plan(self, request: PlanRequest) -> ScenarioDraft:
        warnings: list[str] = []
        requested_goal = request.goal.strip()
        if "otp" in requested_goal.lower() or "captcha" in requested_goal.lower():
            warnings.append("Goal mentions OTP/CAPTCHA; execution policy must deny bypass attempts.")

        return ScenarioDraft(
            name=f"AI Device Lab draft for {request.app_package}",
            app_package=request.app_package,
            steps=[
                ScenarioStep(
                    type="launch",
                    label="Launch app under test",
                    params={"package": request.app_package},
                ),
                ScenarioStep(
                    type="wait",
                    label="Wait for first stable screen",
                    params={"timeout_ms": 5000},
                ),
                ScenarioStep(
                    type="assert",
                    label="Check the app reaches an observable screen",
                    params={"source": "ui_tree_or_screenshot"},
                    assertion={
                        "expected": "App renders an interactive screen without crash dialog",
                        "timeout_ms": 10000,
                    },
                ),
            ],
            warnings=warnings,
        )

    def propose_action(
        self,
        observation: ObservationRequest,
        allowed_operations: set[str],
        step_index: int,
    ) -> ActionProposal:
        operation = self._choose_operation(observation, allowed_operations, step_index)
        params: dict[str, Any]
        if operation == "launch":
            params = {"package": observation.app_package}
        elif operation == "tap":
            params = {"selector": self._first_clickable_selector(observation.ui_tree)}
        elif operation == "wait":
            params = {"duration_ms": 1000}
        elif operation == "finish":
            params = {"outcome": "needs_platform_evaluation"}
        else:
            params = {}

        input_marker = sha256(repr(observation.model_dump(mode="json")).encode()).hexdigest()[:16]
        return ActionProposal(
            action_id=f"act_{input_marker}_{uuid4().hex[:8]}",
            operation=operation,
            params=params,
            confidence=0.74 if operation != "finish" else 0.62,
            reason_code=f"proposal.{operation}",
            expires_at=utc_now() + timedelta(seconds=30),
        )

    def _choose_operation(
        self,
        observation: ObservationRequest,
        allowed_operations: set[str],
        step_index: int,
    ) -> str:
        if step_index <= 0 and "launch" in allowed_operations:
            return "launch"
        if self._first_clickable_selector(observation.ui_tree) and "tap" in allowed_operations:
            return "tap"
        if "wait" in allowed_operations:
            return "wait"
        return "finish"

    def _first_clickable_selector(self, ui_tree: dict[str, Any]) -> str | None:
        nodes = ui_tree.get("nodes")
        if not isinstance(nodes, list):
            return None
        for node in nodes:
            if not isinstance(node, dict):
                continue
            if node.get("clickable") is True:
                resource_id = node.get("resource_id") or node.get("id")
                text = node.get("text")
                if isinstance(resource_id, str) and resource_id:
                    return f"id={resource_id}"
                if isinstance(text, str) and text:
                    return f"text={text}"
        return None
