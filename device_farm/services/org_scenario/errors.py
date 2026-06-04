"""Org-scenario domain errors (shared by service and import/export)."""

from __future__ import annotations

from typing import Any


class OrgScenarioError(Exception):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class OrgScenarioDuplicateNameError(OrgScenarioError):
    def __init__(self, name: str) -> None:
        super().__init__(f"Scenario name already exists: {name}", code="SCENARIO_NAME_DUPLICATE")


class OrgScenarioInUseError(OrgScenarioError):
    def __init__(self, referenced_by: list[dict[str, Any]]) -> None:
        super().__init__("Scenario is referenced by active campaigns", code="SCENARIO_IN_USE")
        self.referenced_by = referenced_by


class OrgScenarioNotFoundError(OrgScenarioError):
    def __init__(self) -> None:
        super().__init__("Scenario not found", code="SCENARIO_NOT_FOUND")


class OrgScenarioValidationError(OrgScenarioError):
    pass


class OrgScenarioBodyValidationError(OrgScenarioError):
    def __init__(self, result, *, primary_code: str) -> None:
        super().__init__("Scenario validation failed", code=primary_code)
        from services.scenario_validation.models import ValidationResult

        self.result: ValidationResult = result
        self.issues = [issue.to_dict() for issue in result.errors]
        self.primary_code = primary_code
