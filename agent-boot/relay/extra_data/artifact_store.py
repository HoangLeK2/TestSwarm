"""Agent-boot must not upload or relay screen/XML artifacts to cloud."""
from __future__ import annotations

from typing import Any


def merge_evidence_into_item(item: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    """No-op: parsed content fields only; evidence stays off cloud."""
    del evidence
    return item
