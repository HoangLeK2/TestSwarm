"""Parse import files with size limits and safe YAML (DF-T-04-005)."""

from __future__ import annotations

import json
from typing import Any

import yaml

from services.org_scenario_io.constants import MAX_IMPORT_BYTES
from services.org_scenario_io.errors import OrgScenarioIOError


def parse_import_bytes(content: bytes, *, filename: str | None = None) -> dict[str, Any]:
    if len(content) > MAX_IMPORT_BYTES:
        raise OrgScenarioIOError(
            f"Import file exceeds {MAX_IMPORT_BYTES} byte limit",
            code="IMPORT_FILE_TOO_LARGE",
        )
    if not content.strip():
        raise OrgScenarioIOError("Import file is empty", code="IMPORT_PAYLOAD_INVALID")

    name = (filename or "").lower()
    text = content.decode("utf-8")

    try:
        if name.endswith(".yaml") or name.endswith(".yml"):
            parsed = yaml.safe_load(text)
        elif name.endswith(".json"):
            parsed = json.loads(text)
        else:
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise OrgScenarioIOError("Import file is not valid YAML or JSON", code="IMPORT_PAYLOAD_INVALID") from exc

    if not isinstance(parsed, dict):
        raise OrgScenarioIOError("Import payload must be a JSON/YAML object", code="IMPORT_PAYLOAD_INVALID")
    return parsed
