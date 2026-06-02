from __future__ import annotations

import threading
from dataclasses import asdict
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from services.social_ext.contract import (
    ExtractionStrategySchema,
    PlatformContentType,
    PlatformContentTypeSchema,
    PlatformExtension,
    PlatformScenarioLib,
)
from services.social_ext.facebook import build_facebook_extension


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _draft_extension(
    platform: str,
    *,
    strategies: dict[str, str],
    version: str = "0.1.0",
) -> PlatformExtension:
    strategy_schemas = {
        name: ExtractionStrategySchema(
            name=name,
            content_type=content_type,
            status="Draft",
        )
        for name, content_type in strategies.items()
    }
    return PlatformExtension(
        name=platform,
        version=version,
        coverage="Draft",
        enabled_by_default=False,
        handlers={},
        scenario_lib=PlatformScenarioLib(
            step_types=[],
            extraction_strategies=list(strategy_schemas),
            strategies=strategy_schemas,
        ),
        content_schema=PlatformContentTypeSchema(
            platform=platform,
            parser_module=f"agent-boot/relay/extra_data/parsers/{platform}",
            content_types=[
                PlatformContentType(
                    code=content_type,
                    object_type=content_type.rsplit("_", 1)[-1],
                    description=f"{platform} {content_type.rsplit('_', 1)[-1]} draft payload owned by agent-boot",
                )
                for content_type in sorted(set(strategies.values()))
            ],
        ),
    )


class SocialPlatformRegistry:
    """Copy-on-write registry for Epic 08 platform extensions."""

    def __init__(self, *, load_defaults: bool = True) -> None:
        self._lock = threading.RLock()
        self._extensions: dict[str, PlatformExtension] = {}
        self._org_flags: dict[str, dict[str, dict[str, Any]]] = {}
        self._version_history: dict[str, list[dict[str, Any]]] = {}
        if load_defaults:
            self.load_defaults()

    def load_defaults(self) -> None:
        self.register(build_facebook_extension(), actor="system")
        self.register(
            _draft_extension(
                "tiktok",
                strategies={"tiktok_posts": "tiktok_video", "tiktok_comments": "tiktok_comment"},
            ),
            actor="system",
        )
        self.register(
            _draft_extension(
                "threads",
                strategies={"threads_posts": "threads_post", "threads_comments": "threads_comment"},
            ),
            actor="system",
        )
        self.register(
            _draft_extension(
                "instagram",
                strategies={"ig_posts": "ig_post", "ig_comments": "ig_comment"},
            ),
            actor="system",
        )

    def register(self, extension: PlatformExtension, *, actor: str = "system") -> None:
        name = self._clean_platform(extension.name)
        if extension.parser is not None and not extension.handlers:
            raise ValueError(f"PLUGIN_HANDLER_REQUIRED: {name}")
        step_types = set(extension.scenario_lib.step_types)
        for alias, canonical in extension.aliases.items():
            if canonical not in step_types:
                raise ValueError(f"PLUGIN_ALIAS_TARGET_UNKNOWN: {alias}->{canonical}")
        with self._lock:
            updated = dict(self._extensions)
            updated[name] = extension
            self._extensions = updated
            self._record_event(
                name,
                "loaded",
                actor=actor,
                to_version=extension.version,
            )

    def unregister(self, platform: str) -> None:
        name = self._clean_platform(platform)
        with self._lock:
            updated = dict(self._extensions)
            updated.pop(name, None)
            self._extensions = updated

    def load_platform(
        self,
        platform: str,
        *,
        version: str | None = None,
        actor: str = "system",
    ) -> PlatformExtension:
        name = self._clean_platform(platform)
        extension = self._build_known_extension(name, version=version)
        self.register(extension, actor=actor)
        return extension

    def unload_platform(self, platform: str, *, actor: str = "system") -> dict[str, Any]:
        name = self._clean_platform(platform)
        with self._lock:
            extension = self._extensions.get(name)
            if extension is None:
                raise KeyError(name)
            updated = dict(self._extensions)
            updated.pop(name, None)
            self._extensions = updated
            return self._record_event(
                name,
                "unloaded",
                actor=actor,
                from_version=extension.version,
            )

    def migrate_platform(
        self,
        platform: str,
        version: str,
        *,
        actor: str = "system",
    ) -> PlatformExtension:
        name = self._clean_platform(platform)
        new_version = (version or "").strip()
        if not new_version:
            raise ValueError("version is required")
        with self._lock:
            extension = self._extensions.get(name)
            if extension is None:
                raise KeyError(name)
            if self._major(extension.version) != self._major(new_version):
                self._record_event(
                    name,
                    "migrate_rejected",
                    actor=actor,
                    from_version=extension.version,
                    to_version=new_version,
                    code="PLUGIN_INCOMPATIBLE_MAJOR_BUMP",
                )
                raise ValueError("PLUGIN_INCOMPATIBLE_MAJOR_BUMP")
            migrated = replace(extension, version=new_version)
            updated = dict(self._extensions)
            updated[name] = migrated
            self._extensions = updated
            self._record_event(
                name,
                "migrated",
                actor=actor,
                from_version=extension.version,
                to_version=new_version,
            )
            return migrated

    def version_history(self, platform: str) -> list[dict[str, Any]]:
        name = self._clean_platform(platform)
        return list(self._version_history.get(name, []))

    def get_platform(self, platform: str) -> PlatformExtension | None:
        return self._extensions.get(self._clean_platform(platform))

    def list_platforms(self) -> list[PlatformExtension]:
        return sorted(self._extensions.values(), key=lambda ext: (not ext.enabled_by_default, ext.name))

    def steps_for_platform(self, platform: str) -> dict[str, Any]:
        ext = self.get_platform(platform)
        if ext is None:
            raise KeyError(platform)
        return {
            "platform": ext.name,
            "version": ext.version,
            "coverage": ext.coverage,
            "step_types": list(ext.scenario_lib.step_types),
            "legacy_aliases": dict(ext.aliases),
            "extraction_strategies": {
                name: asdict(schema)
                for name, schema in ext.scenario_lib.strategies.items()
            },
            "content_types": [asdict(content_type) for content_type in ext.content_schema.content_types],
        }

    def flags_for_org(self, org_id: str) -> dict[str, dict[str, Any]]:
        org = self._clean_org(org_id)
        flags = self._org_flags.get(org, {})
        result: dict[str, dict[str, Any]] = {}
        for ext in self.list_platforms():
            override = flags.get(ext.name, {})
            enabled = bool(override.get("enabled", ext.enabled_by_default))
            result[ext.name] = {
                "platform": ext.name,
                "enabled": enabled,
                "default_enabled": ext.enabled_by_default,
                "coverage": ext.coverage,
                "version": ext.version,
                "note": override.get("note") or "",
                "updated_at": override.get("updated_at"),
            }
        return result

    def set_org_platform_enabled(
        self,
        org_id: str,
        platform: str,
        enabled: bool,
        *,
        note: str = "",
    ) -> dict[str, Any]:
        org = self._clean_org(org_id)
        name = self._clean_platform(platform)
        if name not in self._extensions:
            raise KeyError(name)
        with self._lock:
            org_flags = dict(self._org_flags.get(org, {}))
            updated = {
                "platform": name,
                "enabled": bool(enabled),
                "note": note.strip(),
                "updated_at": _now_iso(),
            }
            org_flags[name] = updated
            all_flags = dict(self._org_flags)
            all_flags[org] = org_flags
            self._org_flags = all_flags
        return updated

    @staticmethod
    def _clean_platform(platform: str) -> str:
        clean = (platform or "").strip().lower()
        if not clean:
            raise ValueError("platform is required")
        return clean

    @staticmethod
    def _clean_org(org_id: str) -> str:
        clean = (org_id or "").strip()
        if not clean:
            raise ValueError("org_id is required")
        return clean

    def _record_event(
        self,
        platform: str,
        event: str,
        *,
        actor: str,
        from_version: str | None = None,
        to_version: str | None = None,
        code: str | None = None,
    ) -> dict[str, Any]:
        entry = {
            "platform": platform,
            "event": event,
            "actor": actor,
            "from_version": from_version,
            "to_version": to_version,
            "code": code,
            "at": _now_iso(),
        }
        history = dict(self._version_history)
        history[platform] = [*history.get(platform, []), entry]
        self._version_history = history
        return entry

    @staticmethod
    def _major(version: str) -> str:
        return str(version or "0").strip().split(".", 1)[0]

    @staticmethod
    def _build_known_extension(platform: str, *, version: str | None = None) -> PlatformExtension:
        if platform == "facebook":
            extension = build_facebook_extension()
            return replace(extension, version=version or extension.version)
        if platform == "tiktok":
            return _draft_extension(
                "tiktok",
                version=version or "0.1.0",
                strategies={"tiktok_posts": "tiktok_video", "tiktok_comments": "tiktok_comment"},
            )
        if platform == "threads":
            return _draft_extension(
                "threads",
                version=version or "0.1.0",
                strategies={"threads_posts": "threads_post", "threads_comments": "threads_comment"},
            )
        if platform == "instagram":
            return _draft_extension(
                "instagram",
                version=version or "0.1.0",
                strategies={"ig_posts": "ig_post", "ig_comments": "ig_comment"},
            )
        raise KeyError(platform)


_REGISTRY = SocialPlatformRegistry(load_defaults=True)


def get_social_platform_registry() -> SocialPlatformRegistry:
    return _REGISTRY
