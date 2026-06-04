"""Constants for org scenario import/export (DF-T-04-005)."""

from __future__ import annotations

SYSTEM_ORG_ID = "__system"
EXPORT_SCHEMA_VERSION = "2.0"
MIN_SUPPORTED_SCHEMA_VERSION = "1.0"
UNSUPPORTED_SCHEMA_VERSIONS = frozenset({"0.5"})
MAX_IMPORT_BYTES = 1_048_576

SCRUBBED_EXPORT_FIELDS = frozenset(
    {
        "organization_id",
        "org_id",
        "created_by",
        "created_at",
        "updated_at",
        "deleted_at",
        "last_validation_summary",
        "last_validated_at",
    }
)
