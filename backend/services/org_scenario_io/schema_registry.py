"""Export payload schema migration (DF-T-04-005)."""

from __future__ import annotations

from typing import Any

from services.org_scenario_io.constants import (
    EXPORT_SCHEMA_VERSION,
    MIN_SUPPORTED_SCHEMA_VERSION,
    UNSUPPORTED_SCHEMA_VERSIONS,
)
from services.org_scenario_io.errors import OrgScenarioIOError


def migrate_export_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Upgrade legacy export payloads to the current schema version."""
    raw_version = str(payload.get("schema_version") or MIN_SUPPORTED_SCHEMA_VERSION)
    if raw_version in UNSUPPORTED_SCHEMA_VERSIONS:
        raise OrgScenarioIOError(
            f"Export schema version {raw_version!r} is not supported",
            code="SCHEMA_VERSION_UNSUPPORTED",
            details={"schema_version": raw_version, "supported_from": MIN_SUPPORTED_SCHEMA_VERSION},
        )

    warnings: list[str] = []
    migrated = dict(payload)

    if raw_version == "1.0":
        migrated["schema_version"] = EXPORT_SCHEMA_VERSION
        warnings.append("migrated from 1.0")
    elif raw_version == EXPORT_SCHEMA_VERSION:
        migrated["schema_version"] = EXPORT_SCHEMA_VERSION
    else:
        try:
            major = int(raw_version.split(".", 1)[0])
            min_major = int(MIN_SUPPORTED_SCHEMA_VERSION.split(".", 1)[0])
            current_major = int(EXPORT_SCHEMA_VERSION.split(".", 1)[0])
        except ValueError as exc:
            raise OrgScenarioIOError(
                f"Invalid export schema_version {raw_version!r}",
                code="SCHEMA_VERSION_UNSUPPORTED",
            ) from exc
        if major < min_major or major > current_major:
            raise OrgScenarioIOError(
                f"Export schema version {raw_version!r} is not supported",
                code="SCHEMA_VERSION_UNSUPPORTED",
                details={"schema_version": raw_version},
            )
        migrated["schema_version"] = EXPORT_SCHEMA_VERSION

    scenario = migrated.get("scenario")
    if not isinstance(scenario, dict):
        raise OrgScenarioIOError("Export payload missing scenario object", code="IMPORT_PAYLOAD_INVALID")

    return migrated, warnings
