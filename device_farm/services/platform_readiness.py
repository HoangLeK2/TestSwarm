"""Platform-neutral app readiness vocabulary and resolver registry.

The status enum, result payload and hierarchy-scanning helpers are shared by every
platform. The actual marker tables that decide *what a logged-out Facebook screen
looks like* live in the per-platform module (``services/facebook_readiness.py``)
and register themselves here.

Adding a platform = add ``services/<platform>_readiness.py`` with its marker set
and call :func:`register_readiness_resolver`. Nothing in the scenario step layer
changes.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable

DEFAULT_PLATFORM = "facebook"


class PlatformReadinessStatus(StrEnum):
    READY = "ready"
    LOGGED_OUT = "logged_out"
    CHECKPOINT = "checkpoint"
    UNRESPONSIVE = "unresponsive"
    UNSUPPORTED_BUILD = "unsupported_build"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class PlatformReadinessResult:
    status: PlatformReadinessStatus
    reason: str
    attempted_at: datetime
    hierarchy_sha256: str | None = None
    app_package: str | None = None
    app_version: str | None = None
    matched_markers: tuple[str, ...] = ()
    platform: str | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == PlatformReadinessStatus.READY

    def evidence(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["attempted_at"] = self.attempted_at.isoformat()
        data["matched_markers"] = list(self.matched_markers)
        return {
            key: value for key, value in data.items() if value not in (None, [], ())
        }


# ── Shared hierarchy helpers ──────────────────────────────────────────────────

def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFKC", value or "")
    raw = raw.casefold()
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def attrs_blob(root: ET.Element) -> str:
    parts: list[str] = []
    for node in root.iter():
        for key in ("resource-id", "text", "content-desc", "class", "package"):
            value = node.attrib.get(key)
            if value:
                parts.append(value)
    return normalized(" ".join(parts))


def match_any(blob: str, patterns: tuple[tuple[str, str], ...]) -> tuple[str, ...]:
    matches: list[str] = []
    for name, pattern in patterns:
        if re.search(pattern, blob):
            matches.append(name)
    return tuple(matches)


def hierarchy_digest(raw: str) -> str | None:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest() if raw else None


# ── Resolver registry ─────────────────────────────────────────────────────────

ReadinessResolver = Callable[..., PlatformReadinessResult]

_RESOLVERS: dict[str, ReadinessResolver] = {}


def register_readiness_resolver(platform: str, resolver: ReadinessResolver) -> None:
    _RESOLVERS[(platform or "").strip().casefold()] = resolver


def get_readiness_resolver(platform: str) -> ReadinessResolver | None:
    return _RESOLVERS.get((platform or "").strip().casefold())


def resolve_platform_readiness(
    hierarchy_xml: str | None,
    *,
    platform: str = DEFAULT_PLATFORM,
    package: str | None = None,
    app_version: str | None = None,
) -> PlatformReadinessResult:
    """Resolve readiness for ``platform``, or report it as unsupported."""
    clean = (platform or DEFAULT_PLATFORM).strip().casefold()
    resolver = get_readiness_resolver(clean)
    if resolver is None:
        return PlatformReadinessResult(
            status=PlatformReadinessStatus.INCONCLUSIVE,
            reason="platform_readiness_not_implemented",
            attempted_at=utcnow(),
            app_package=package,
            app_version=app_version,
            platform=clean,
        )
    kwargs: dict[str, Any] = {"app_version": app_version}
    if package is not None:
        kwargs["package"] = package
    return resolver(hierarchy_xml, **kwargs)
