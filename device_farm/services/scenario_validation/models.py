from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

ValidationLevel = Literal["error", "warning", "info"]


@dataclass(frozen=True)
class ValidationIssue:
    level: ValidationLevel
    code: str
    message: str
    location: str = ""
    hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "level": self.level,
            "code": self.code,
            "message": self.message,
            "location": self.location,
        }
        if self.hint:
            out["hint"] = self.hint
        return out


@dataclass
class ValidationResult:
    status: Literal["valid", "invalid"] = "valid"
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)
    infos: list[ValidationIssue] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)

    def add(self, issue: ValidationIssue) -> None:
        if issue.level == "error":
            self.errors.append(issue)
            self.status = "invalid"
        elif issue.level == "warning":
            self.warnings.append(issue)
        else:
            self.infos.append(issue)

    def to_response_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "errors": [i.to_dict() for i in self.errors],
            "warnings": [i.to_dict() for i in self.warnings],
            "infos": [i.to_dict() for i in self.infos],
        }

    def to_summary_dict(self) -> dict[str, Any]:
        """Compact payload stored on scenarios.last_validation_summary."""
        return {
            "status": self.status,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "info_count": len(self.infos),
            "codes": [i.code for i in (*self.errors, *self.warnings, *self.infos)],
        }

    def all_issues(self) -> list[ValidationIssue]:
        return [*self.errors, *self.warnings, *self.infos]
