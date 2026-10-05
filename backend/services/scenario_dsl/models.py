"""Validation result models for org scenario body (DF-T-04-002)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class BodyValidationIssue:
    code: str
    message: str
    location: str = ""
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }
        if self.details:
            out["details"] = self.details
        return out


@dataclass
class BodyValidationResult:
    status: Literal["valid", "invalid"] = "valid"
    errors: list[BodyValidationIssue] = field(default_factory=list)
    normalized_body: dict[str, Any] | None = None

    @property
    def is_runnable(self) -> bool:
        return self.status == "valid" and self.normalized_body is not None

    @property
    def primary_code(self) -> str | None:
        return self.errors[0].code if self.errors else None

    def add(self, issue: BodyValidationIssue) -> None:
        self.errors.append(issue)
        self.status = "invalid"

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "is_runnable": self.is_runnable,
            "errors": [e.to_dict() for e in self.errors],
        }
