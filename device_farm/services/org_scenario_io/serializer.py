"""Export org scenarios to portable YAML/JSON payloads (DF-T-04-005)."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from db.crud import org_scenario as repo
from db.models.org_scenario import OrgScenario
from services.org_scenario_io.constants import EXPORT_SCHEMA_VERSION, SCRUBBED_EXPORT_FIELDS
from services.org_scenario_io.ref_utils import collect_run_scenario_ids, rewrite_run_scenario_refs_for_export


def _canonical_json(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(payload_without_checksum: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload_without_checksum).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def verify_checksum(payload: dict[str, Any]) -> None:
    from services.org_scenario_io.errors import OrgScenarioIOError

    expected = payload.get("checksum")
    if not expected:
        return
    body = {k: v for k, v in payload.items() if k != "checksum"}
    actual = compute_checksum(body)
    if str(expected) != actual:
        raise OrgScenarioIOError("Export checksum mismatch; file may have been edited", code="CHECKSUM_MISMATCH")


class ScenarioSerializer:
    """Build portable export payloads with scrubbed tenant fields."""

    def __init__(self, db: AsyncSession, *, org_id: str) -> None:
        self.db = db
        self.org_id = org_id

    async def build_payload(
        self,
        row: OrgScenario,
        *,
        tags: list[str],
        version: int | None = None,
    ) -> dict[str, Any]:
        body = row.body_json if isinstance(row.body_json, dict) else {}
        export_version = int(version or row.scenario_version or 1)
        ref_ids = collect_run_scenario_ids(body, row.kind)
        id_to_name: dict[str, str] = {}
        if ref_ids:
            id_to_name = await repo.get_org_scenario_names_by_ids(
                self.db, self.org_id, sorted(ref_ids)
            )
        portable_body = rewrite_run_scenario_refs_for_export(
            body, row.kind, id_to_name=id_to_name
        )
        scenario_block = {
            "name": row.name,
            "description": row.description or "",
            "kind": row.kind,
            "tags": sorted(tags),
            "scenario_version": export_version,
            "body": portable_body,
        }
        payload = {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "scenario": scenario_block,
        }
        payload["checksum"] = compute_checksum(payload)
        return payload

    @staticmethod
    def scrub_metadata(raw: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in raw.items() if k not in SCRUBBED_EXPORT_FIELDS}


def serialize_payload(payload: dict[str, Any], *, fmt: str) -> tuple[bytes, str]:
    if fmt == "json":
        return (
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            "application/json",
        )
    import yaml

    return (
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True).encode("utf-8"),
        "application/x-yaml",
    )
