from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

CONTRACT_VERSION = "1.0.0"


@runtime_checkable
class PlatformParser(Protocol):
    """Parser boundary for platform XML/screenshot extraction.

    Epic 08 keeps raw hierarchy parsing and raw_data persistence in agent-boot.
    Device Farm extensions may declare this interface, but active edge parsers
    are delegated to ``agent-boot/relay/extra_data``.
    """

    def parse(self, snapshot: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
        ...


@runtime_checkable
class PlatformHandler(Protocol):
    """Scenario step handler contract for platform-specific actions."""

    def execute(self, ctx: Any, step: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True, slots=True)
class PlatformContentType:
    code: str
    object_type: str
    storage_owner: str = "agent-boot"
    raw_data_owner: str = "agent-boot"
    persisted_in_device_farm: bool = False
    description: str = ""


@dataclass(frozen=True, slots=True)
class PlatformContentTypeSchema:
    platform: str
    content_types: list[PlatformContentType] = field(default_factory=list)
    parser_module: str | None = None


@dataclass(frozen=True, slots=True)
class ExtractionStrategySchema:
    name: str
    content_type: str
    storage_owner: str = "agent-boot"
    raw_data_owner: str = "agent-boot"
    persisted_in_device_farm: bool = False
    status: str = "Active"


@dataclass(frozen=True, slots=True)
class PlatformScenarioLib:
    step_types: list[str] = field(default_factory=list)
    extraction_strategies: list[str] = field(default_factory=list)
    strategies: dict[str, ExtractionStrategySchema] = field(default_factory=dict)
    templates: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PlatformExtension:
    name: str
    version: str
    coverage: str
    scenario_lib: PlatformScenarioLib
    content_schema: PlatformContentTypeSchema
    parser: PlatformParser | None = None
    handlers: dict[str, PlatformHandler] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    enabled_by_default: bool = False
    lifecycle: str = "loaded"
    min_contract_version: str = CONTRACT_VERSION
