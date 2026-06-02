"""Import org scenarios from portable payloads (DF-T-04-005)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.models.enums import OrgScenarioStatus
from db.models.org_scenario import OrgScenario
from services.org_scenario.events import emit_scenario_domain_event
from services.org_scenario.errors import OrgScenarioDuplicateNameError
from services.org_scenario_io.dependency_resolver import (
    create_stub_scenarios,
    resolve_dependency_names,
    resolve_import_body,
)
from services.org_scenario_io.errors import (
    OrgScenarioIOError,
    OrgScenarioImportValidationError,
    OrgScenarioMissingReferencesError,
)
from services.org_scenario_io.parser import parse_import_bytes
from services.org_scenario_io.schema_registry import migrate_export_payload
from services.org_scenario_io.serializer import verify_checksum as verify_export_checksum
from services.org_scenario_validation.validator import validate_org_scenario


@dataclass(frozen=True, slots=True)
class ImportResult:
    scenario_id: str
    name: str
    kind: str
    status: str
    scenario_version: int
    warnings: list[str]
    created_stub_names: list[str]


class ScenarioImporter:
    """Parse, migrate, validate, and commit imported org scenarios."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        org_id: str,
        created_by: str | None,
        resolve: str = "reject",
    ) -> None:
        self.db = db
        self.org_id = org_id
        self.created_by = created_by
        self.resolve = resolve

    async def import_bytes(self, content: bytes, *, filename: str | None = None) -> ImportResult:
        payload = parse_import_bytes(content, filename=filename)
        verify_export_checksum(payload)
        migrated, migration_warnings = migrate_export_payload(payload)
        return await self.import_payload(migrated, migration_warnings=migration_warnings)

    async def import_payload(
        self,
        payload: dict[str, Any],
        *,
        migration_warnings: list[str] | None = None,
        verify_checksum: bool = False,
    ) -> ImportResult:
        if verify_checksum:
            verify_export_checksum(payload)
        if migration_warnings is None:
            payload, migration_warnings = migrate_export_payload(payload)
        return await self._commit_import(payload, migration_warnings)

    async def _commit_import(
        self,
        migrated: dict[str, Any],
        migration_warnings: list[str],
    ) -> ImportResult:
        scenario_data = migrated["scenario"]
        name = str(scenario_data.get("name") or "").strip()
        if not name:
            raise OrgScenarioIOError("Import payload missing scenario.name", code="IMPORT_PAYLOAD_INVALID")
        kind = str(scenario_data.get("kind") or "sequence").strip()
        description = str(scenario_data.get("description") or "")
        tags = scenario_data.get("tags") or []
        if not isinstance(tags, list):
            tags = []
        body = scenario_data.get("body")
        if not isinstance(body, dict):
            raise OrgScenarioIOError("Import payload missing scenario.body", code="IMPORT_PAYLOAD_INVALID")

        dup = await repo.find_by_org_and_name_lower(self.db, self.org_id, name.lower())
        if dup is not None:
            raise OrgScenarioDuplicateNameError(name)

        missing, name_to_id = await resolve_dependency_names(
            self.db, org_id=self.org_id, body=body, kind=kind
        )
        created_stubs: list[str] = []
        if missing:
            if self.resolve != "create_stub":
                raise OrgScenarioMissingReferencesError(missing)
            stub_map = await create_stub_scenarios(
                self.db,
                org_id=self.org_id,
                names=missing,
                created_by=self.created_by,
            )
            name_to_id.update(stub_map)
            created_stubs = list(missing)

        resolved_body = resolve_import_body(body, kind, name_to_id=name_to_id)

        temp = OrgScenario(
            id=str(uuid4()),
            org_id=self.org_id,
            name=name,
            name_lower=name.lower(),
            description=description,
            kind=kind,
            status=OrgScenarioStatus.DRAFT.value,
            scenario_version=1,
            body_json=None,
            created_by=self.created_by,
        )
        result, normalized = await validate_org_scenario(
            self.db,
            temp,
            body=resolved_body,
        )
        if normalized is None or result.has_errors:
            primary = result.errors[0].code if result.errors else "SCENARIO_VALIDATION_FAILED"
            raise OrgScenarioImportValidationError(result, primary_code=primary)

        now = datetime.now(timezone.utc)
        row = await repo.create_org_scenario(
            self.db,
            org_id=self.org_id,
            name=name,
            kind=kind,
            description=description,
            body_json=normalized,
            created_by=self.created_by,
            tags=[str(t) for t in tags if str(t).strip()],
            last_validation_summary=result.to_summary_dict(),
            last_validated_at=now,
        )
        await emit_scenario_domain_event(
            self.db,
            event="scenario.created",
            org_id=self.org_id,
            scenario_id=row.id,
            user_id=self.created_by,
            details={"scenario_version": row.scenario_version, "imported": True},
        )
        return ImportResult(
            scenario_id=row.id,
            name=row.name,
            kind=row.kind,
            status=row.status,
            scenario_version=int(row.scenario_version or 1),
            warnings=migration_warnings,
            created_stub_names=created_stubs,
        )


async def import_scenario_bytes(
    db: AsyncSession,
    *,
    org_id: str,
    content: bytes,
    filename: str | None = None,
    created_by: str | None = None,
    resolve: str = "reject",
) -> ImportResult:
    importer = ScenarioImporter(
        db,
        org_id=org_id,
        created_by=created_by,
        resolve=resolve,
    )
    return await importer.import_bytes(content, filename=filename)
