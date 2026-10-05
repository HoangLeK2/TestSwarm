"""StepHandler contract for DF-E-08 platform extensions (DF-T-04-002)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class StepResult:
    """Minimal handler output contract (execution in DF-T-04-010)."""

    ok: bool
    message: str = ""
    data: dict[str, Any] | None = None
    retryable: bool = False


@runtime_checkable
class StepHandler(Protocol):
    """Platform-specific and core step handlers implement this interface."""

    async def execute(self, ctx: Any, step: dict[str, Any]) -> StepResult:
        """Run one normalized step; may raise on unrecoverable failure."""
