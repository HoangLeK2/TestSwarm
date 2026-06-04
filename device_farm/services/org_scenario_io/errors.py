"""Import/export error types (DF-T-04-005)."""

from __future__ import annotations

from typing import Any


class OrgScenarioIOError(Exception):
    def __init__(self, message: str, *, code: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class OrgScenarioImportValidationError(OrgScenarioIOError):
    def __init__(self, result, *, primary_code: str) -> None:
        super().__init__("Scenario import validation failed", code=primary_code)
        self.result = result
        self.issues = [issue.to_dict() for issue in result.errors]
        self.primary_code = primary_code


class OrgScenarioMissingReferencesError(OrgScenarioIOError):
    def __init__(self, missing_names: list[str]) -> None:
        super().__init__(
            "Import references scenarios that do not exist in target org",
            code="MISSING_SCENARIO_REFERENCES",
            details={"missing_scenarios": missing_names},
        )
        self.missing_names = missing_names
