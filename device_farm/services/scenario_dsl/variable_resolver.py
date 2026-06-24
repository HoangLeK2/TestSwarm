"""Five-tier variable resolution for org scenario DSL (FR-04-09)."""

from __future__ import annotations

import os
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from common.variable_resolver import _BUILTIN_NAMES, _EXACT_VAR_RE, _VAR_PATTERN

# Priority (highest wins): runtime > account > device > scenario > campaign > builtins > env whitelist
_LAYER_ORDER: tuple[str, ...] = (
    "runtime",
    "account",
    "device",
    "scenario",
    "campaign",
    "builtin",
    "env",
)


@dataclass
class EffectiveVariableResolver:
    """Resolve ${var} with provenance for effective_config logging."""

    campaign_vars: dict[str, Any] = field(default_factory=dict)
    scenario_vars: dict[str, Any] = field(default_factory=dict)
    device_vars: dict[str, Any] = field(default_factory=dict)
    account_vars: dict[str, Any] = field(default_factory=dict)
    runtime_vars: dict[str, Any] = field(default_factory=dict)
    device_serial: str = ""
    device_model: str = ""
    env_whitelist: frozenset[str] = frozenset()

    def resolve(self, value: Any, step_index: int = 0) -> Any:
        resolved, _ = self.resolve_with_provenance(value, step_index=step_index)
        return resolved

    def resolve_with_provenance(
        self,
        value: Any,
        *,
        step_index: int = 0,
    ) -> tuple[Any, dict[str, str]]:
        provenance: dict[str, str] = {}
        return self._resolve_value(value, step_index, provenance), provenance

    def set_runtime(self, name: str, value: Any) -> None:
        self.runtime_vars[name] = value

    def _resolve_value(
        self,
        value: Any,
        step_index: int,
        provenance: dict[str, str],
    ) -> Any:
        if isinstance(value, str):
            return self._resolve_string(value, step_index, provenance)
        if isinstance(value, dict):
            resolved: dict[str, Any] = {}
            for k, v in value.items():
                if isinstance(v, str):
                    resolved[k] = self._resolve_string(v, step_index, provenance)
                else:
                    resolved[k] = self._resolve_value(v, step_index, provenance)
            return resolved
        if isinstance(value, list):
            out: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    out.append(self._resolve_string(item, step_index, provenance))
                else:
                    out.append(self._resolve_value(item, step_index, provenance))
            return out
        return value

    def _resolve_string(self, text: str, step_index: int, provenance: dict[str, str]) -> Any:
        m = _EXACT_VAR_RE.match(text)
        if m:
            name = m.group(1)
            val, layer = self._lookup(name, step_index)
            if val is None:
                return text
            if layer:
                provenance[name] = layer
            if isinstance(val, list):
                return random.choice(val)
            return val

        def _replacer(match: re.Match) -> str:  # type: ignore[type-arg]
            name = match.group(1)
            val, layer = self._lookup(name, step_index)
            if val is None:
                return match.group(0)
            if layer:
                provenance[name] = layer
            if isinstance(val, list):
                return str(random.choice(val))
            return str(val)

        return _VAR_PATTERN.sub(_replacer, text)

    def _lookup(self, name: str, step_index: int) -> tuple[Any, str | None]:
        if name in self.runtime_vars:
            return self.runtime_vars[name], "runtime"
        if name in self.account_vars:
            return self.account_vars[name], "account"
        if name in self.device_vars:
            return self.device_vars[name], "device"
        if name in self.scenario_vars:
            return self.scenario_vars[name], "scenario"
        if name in self.campaign_vars:
            return self.campaign_vars[name], "campaign"
        if name in _BUILTIN_NAMES:
            return self._resolve_builtin(name, step_index), "builtin"
        if name in self.env_whitelist:
            env_val = os.environ.get(name)
            if env_val is not None:
                return env_val, "env"
        return None, None

    def _resolve_builtin(self, name: str, step_index: int) -> Any:
        if name in ("__NOW__", "__DATE__", "__TIME__"):
            now = datetime.now()
            if name == "__NOW__":
                return now.isoformat()
            if name == "__DATE__":
                return now.strftime("%Y-%m-%d")
            return now.strftime("%H:%M:%S")
        if name == "__DEVICE_SERIAL__":
            return self.device_serial
        if name == "__DEVICE_MODEL__":
            return self.device_model
        if name == "__RANDOM_INT_1_100__":
            return random.randint(1, 100)
        if name == "__RANDOM_UUID__":
            return str(uuid.uuid4())
        if name == "__STEP_INDEX__":
            return step_index
        if name == "__LOOP_INDEX__":
            return 0
        return None

    @staticmethod
    def layer_priority() -> tuple[str, ...]:
        return _LAYER_ORDER

    @classmethod
    def for_campaign_device(
        cls,
        *,
        campaign_vars: dict[str, Any] | None,
        per_device_overrides: dict[str, Any] | None,
        device_id: str,
        scenario_vars: dict[str, Any] | None = None,
        account_vars: dict[str, Any] | None = None,
        runtime_vars: dict[str, Any] | None = None,
        device_serial: str = "",
        device_model: str = "",
    ) -> EffectiveVariableResolver:
        """Build resolver for one fan-out device (DF-T-04-008)."""
        overrides_map = per_device_overrides or {}
        device_layer = overrides_map.get(device_id)
        if not isinstance(device_layer, dict):
            device_layer = {}
        return cls(
            campaign_vars=dict(campaign_vars or {}),
            scenario_vars=dict(scenario_vars or {}),
            device_vars=dict(device_layer),
            account_vars=dict(account_vars or {}),
            runtime_vars=dict(runtime_vars or {}),
            device_serial=device_serial,
            device_model=device_model,
        )
