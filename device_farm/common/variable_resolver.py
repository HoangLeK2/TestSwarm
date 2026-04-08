from __future__ import annotations

"""
common/variable_resolver.py — Variable interpolation engine for scenario execution.

Support ${VAR} syntax in any string field of step.
Resolution order (priority decreasing):
  1. Runtime vars  (set_variable step, extraction results)
  2. Scenario-level vars  (scenario.variables)
  3. Campaign-level vars  (campaign.variables)
  4. Env vars  (only names listed in VariableContext.env_whitelist — opt-in, default empty)
  5. Built-in vars  (__NOW__, __DEVICE_SERIAL__, ...)
  6. Keep ${VAR} if not resolved
"""

import os
import random
import re
import uuid
from datetime import datetime
from typing import Any

_EXACT_VAR_RE = re.compile(r"^\$\{(\w+)\}$")
_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")

_BUILTIN_NAMES: frozenset[str] = frozenset({
    "__NOW__", "__DATE__", "__TIME__",
    "__DEVICE_SERIAL__", "__DEVICE_MODEL__",
    "__RANDOM_INT_1_100__", "__RANDOM_UUID__",
    "__STEP_INDEX__",
})


def _normalize_vars(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalize a variables dict.

    When variables come from a ScenarioTemplate they are stored as metadata dicts:
        {"GROUP_NAME": {"type": "string", "default": "foo", "description": "..."}}
    When they come from a plain scenario they are already plain values:
        {"GROUP_NAME": "foo"}

    This function extracts the 'default' key from any metadata dict so the
    variable resolver always works with plain values.
    """
    result: dict[str, Any] = {}
    for k, v in raw.items():
        if isinstance(v, dict) and "default" in v and "type" in v:
            result[k] = v["default"]
        else:
            result[k] = v
    return result


class VariableContext:
    """
    Manage variable scopes for one scenario execution.

    Each scenario execution creates a separate instance.
    Instance is passed throughout, including into nested loop/if commands,
    so runtime vars set inside loop are still visible after loop.

    Thread safety: no need for lock — each device runs scenario on a separate thread.
    """

    __slots__ = (
        "_runtime_vars",
        "_scenario_vars",
        "_campaign_vars",
        "_counters",
        "_device_serial",
        "_device_model",
        "_env_whitelist",
    )

    def __init__(
        self,
        scenario_vars: dict[str, Any] | None = None,
        campaign_vars: dict[str, Any] | None = None,
        device_serial: str = "",
        device_model: str = "",
        env_whitelist: frozenset[str] | None = None,
    ) -> None:
        self._runtime_vars: dict[str, Any] = {}
        self._scenario_vars: dict[str, Any] = _normalize_vars(scenario_vars or {})
        self._campaign_vars: dict[str, Any] = _normalize_vars(campaign_vars or {})
        self._counters: dict[str, int] = {}
        self._device_serial = device_serial
        self._device_model = device_model
        # Only env var names explicitly listed here are exposed to scenarios.
        # Default is empty — no env access — to prevent secret leakage.
        self._env_whitelist: frozenset[str] = env_whitelist or frozenset()


    def child_scope(self, extra_vars: dict[str, Any]) -> "VariableContext":
        """
        Create a child context that inherits all parent state but has additional
        scenario-level variables (e.g. overrides passed to a sub-scenario via
        run_scenario step).

        Isolation:
        - scenario_vars: merged (parent + extra_vars, extra takes priority)
        - campaign_vars: shared reference (read-only; no mutation in sub-scenarios)
        - runtime_vars: shallow-copied so writes inside sub-scenario don't bleed back
        - counters: fresh (sub-scenario counter space is independent)
        - device_serial/model: same as parent
        """
        child = VariableContext(
            scenario_vars={**self._scenario_vars, **extra_vars},
            campaign_vars=self._campaign_vars,
            device_serial=self._device_serial,
            device_model=self._device_model,
            env_whitelist=self._env_whitelist,
        )
        # Copy current runtime state so sub-scenario sees vars set by parent steps,
        # but mutations inside sub-scenario don't affect parent scope.
        child._runtime_vars = dict(self._runtime_vars)
        return child

    def set(self, name: str, value: Any) -> None:
        """Set a runtime variable."""
        self._runtime_vars[name] = value
        if isinstance(value, int) and not isinstance(value, bool):
            self._counters[name] = value
        else:
            self._counters.pop(name, None)

    def set_from_list(self, name: str, values: list[Any]) -> Any:
        """Choose random value from list and set it into runtime vars. Return the chosen value."""
        chosen = random.choice(values)
        self._runtime_vars[name] = chosen
        return chosen

    def increment(self, name: str, step: int = 1) -> int:
        """Increment counter (starts from 0) and save it into runtime vars. Return the new value."""
        current = self._counters.get(name, 0) + step
        self._counters[name] = current
        self._runtime_vars[name] = current
        return current

    def resolve(self, value: Any, step_index: int = 0) -> Any:
        """
        Resolve ${VAR} in value. Handle recursive dict and list.

        - str: resolve all ${VAR}. If the entire string is one var and the value
          is not a string → return original type (keep int/float/list/dict for step fields).
        - dict: resolve each value (keys are not resolved).
        - list: resolve each item.
        - Other types: return as is.
        """
        if isinstance(value, str):
            return self._resolve_string(value, step_index)
        if isinstance(value, dict):
            return {k: self.resolve(v, step_index) for k, v in value.items()}
        if isinstance(value, list):
            return [self.resolve(item, step_index) for item in value]
        return value

    def _resolve_string(self, text: str, step_index: int) -> Any:
        # Fast-path: entire string is "${VAR}" → keep original type
        m = _EXACT_VAR_RE.match(text)
        if m:
            val = self._lookup(m.group(1), step_index)
            if val is None:
                return text  # unresolved → keep as is
            if isinstance(val, list):
                return random.choice(val)
            return val

        # General path: resolve multiple ${VAR} → always return str
        def _replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            val = self._lookup(match.group(1), step_index)
            if val is None:
                return match.group(0)  # keep as is if not resolved
            if isinstance(val, list):
                return str(random.choice(val))
            return str(val)

        return _VAR_PATTERN.sub(_replacer, text)

    def _lookup(self, name: str, step_index: int) -> Any:
        if name in self._runtime_vars:
            return self._runtime_vars[name]
        if name in self._scenario_vars:
            return self._scenario_vars[name]
        if name in self._campaign_vars:
            return self._campaign_vars[name]
        if name in _BUILTIN_NAMES:
            return self._resolve_builtin(name, step_index)
        if name in self._env_whitelist:
            env_val = os.environ.get(name)
            if env_val is not None:
                return env_val
        return None

    def _resolve_builtin(self, name: str, step_index: int) -> Any:
        if name in ("__NOW__", "__DATE__", "__TIME__"):
            now = datetime.now()
            if name == "__NOW__":
                return now.isoformat()
            if name == "__DATE__":
                return now.strftime("%Y-%m-%d")
            return now.strftime("%H:%M:%S")
        if name == "__DEVICE_SERIAL__":
            return self._device_serial
        if name == "__DEVICE_MODEL__":
            return self._device_model
        if name == "__RANDOM_INT_1_100__":
            return random.randint(1, 100)
        if name == "__RANDOM_UUID__":
            return str(uuid.uuid4())
        if name == "__STEP_INDEX__":
            return step_index
        return None 
