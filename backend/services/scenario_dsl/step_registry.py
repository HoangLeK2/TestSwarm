"""Thread-safe StepRegistry extension point (DF-T-04-002 / DF-E-08)."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from common.scenario_schema import SCENARIO_STEP_TYPES
from services.scenario_dsl.step_family import CORE_STEP_TYPES, STEP_FAMILY_VALUES
from services.scenario_dsl.step_handler import StepHandler

# Flat step types used by the runtime executor (common.scenario_schema) and legacy imports.
_LEGACY_RUNTIME_STEP_TYPES: frozenset[str] = frozenset(
    {
        *SCENARIO_STEP_TYPES,
        "install_apk",
    }
)


@dataclass(frozen=True, slots=True)
class StepRegistration:
    step_type: str
    handler: StepHandler
    schema: dict[str, Any] | None = None
    requires_account: bool = False


class StepRegistry:
    """Copy-on-write registry for platform-specific step types."""

    _lock = threading.RLock()
    _registrations: dict[str, StepRegistration] = {}

    @classmethod
    def register(
        cls,
        step_type: str,
        handler: StepHandler,
        schema: dict[str, Any] | None = None,
        *,
        requires_account: bool = False,
    ) -> None:
        clean = (step_type or "").strip()
        if not clean:
            raise ValueError("step_type is required")
        with cls._lock:
            updated = dict(cls._registrations)
            updated[clean] = StepRegistration(
                step_type=clean,
                handler=handler,
                schema=schema,
                requires_account=requires_account,
            )
            cls._registrations = updated

    @classmethod
    def unregister(cls, step_type: str) -> None:
        clean = (step_type or "").strip()
        with cls._lock:
            updated = dict(cls._registrations)
            updated.pop(clean, None)
            cls._registrations = updated

    @classmethod
    def get(cls, step_type: str) -> StepRegistration | None:
        return cls._registrations.get(step_type)

    @classmethod
    def registered_types(cls) -> frozenset[str]:
        return frozenset(cls._registrations.keys())

    @classmethod
    def is_known_type(cls, step_type: str) -> bool:
        clean = (step_type or "").strip()
        if not clean:
            return False
        if clean in cls._registrations:
            return True
        if clean in CORE_STEP_TYPES:
            return True
        if clean in _LEGACY_RUNTIME_STEP_TYPES:
            return True
        if "." in clean:
            family, _, _ = clean.partition(".")
            return family in STEP_FAMILY_VALUES and clean.startswith("platform_specific.")
        return False

    @classmethod
    def supported_families(cls) -> list[str]:
        return sorted(STEP_FAMILY_VALUES)

    @classmethod
    def reset_for_tests(cls) -> None:
        with cls._lock:
            cls._registrations = {}
