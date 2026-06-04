"""Screenshot + hierarchy capture for extraction pipeline (DF-T-06-003)."""
from __future__ import annotations

import hashlib
import io
import logging
import time
from datetime import datetime, timezone
from typing import Any

from PIL import Image

from services.content.extraction.models import (
    CaptureError,
    CaptureHandle,
    ExecutionCaptureContext,
    HierarchyHandle,
    HierarchyParseError,
)

log = logging.getLogger(__name__)

_CAPTURE_TIMEOUT_S = 5.0
_CACHE_TTL_S = 30.0
_screenshot_cache: dict[tuple[str, int | None, str], tuple[float, CaptureHandle]] = {}
_hierarchy_cache: dict[tuple[str, int | None, str], tuple[float, HierarchyHandle]] = {}


def clear_capture_cache() -> None:
    """Test helper — reset in-memory capture cache."""
    _screenshot_cache.clear()
    _hierarchy_cache.clear()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _png_bytes(raw: bytes) -> bytes:
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception as exc:
        raise CaptureError(
            "unsupported screenshot format",
            code="CAPTURE_FORMAT_INVALID",
            details={"error": str(exc)},
        ) from exc


def _object_key(ctx: ExecutionCaptureContext, ext: str) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    org = ctx.org_id or "default"
    return f"{org}/{ctx.execution_id}/step-{ctx.step_index}/{ctx.kind}-{ts}.{ext}"


def _cache_get(cache: dict, key: tuple) -> Any | None:
    entry = cache.get(key)
    if not entry:
        return None
    ts, handle = entry
    if time.monotonic() - ts > _CACHE_TTL_S:
        cache.pop(key, None)
        return None
    return handle


def _cache_put(cache: dict, key: tuple, handle: Any) -> None:
    cache[key] = (time.monotonic(), handle)


class ExtractionCaptureService:
    """Epic 06 capture adapter over device transport + MinIO + execution_artifacts."""

    def __init__(self, *, timeout_s: float = _CAPTURE_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s

    def _ensure_device(self, device: Any) -> None:
        if device is None:
            raise CaptureError("device not found", code="DEVICE_OFFLINE")

    def capture_screenshot(
        self,
        device: Any,
        *,
        region: dict[str, float] | None = None,
        persist: bool = True,
        execution_ctx: ExecutionCaptureContext | None = None,
        db=None,
    ) -> CaptureHandle:
        started = time.perf_counter()
        self._ensure_device(device)
        serial = getattr(device, "serial", "unknown")
        step_index = execution_ctx.step_index if execution_ctx else None
        kind = execution_ctx.kind if execution_ctx else "screenshot"
        cache_key = (serial, step_index, kind)
        cached = _cache_get(_screenshot_cache, cache_key)
        if cached is not None:
            return cached

        if persist and (execution_ctx is None or not execution_ctx.execution_id):
            raise CaptureError(
                "persist=True requires execution_ctx.execution_id",
                code="MISSING_CONTEXT",
            )

        raw = device.take_screenshot()
        if not raw:
            raise CaptureError("device screenshot unavailable", code="DEVICE_OFFLINE")

        png = _png_bytes(raw)
        if region:
            png = self._crop_png(png, region)

        digest = _sha256(png)
        captured_at = datetime.now(timezone.utc)
        object_key: str | None = None
        artifact_id: str | None = None

        if persist and execution_ctx is not None:
            object_key = _object_key(execution_ctx, "png")
            if self._upload(object_key, png, "image/png"):
                artifact_id = _try_persist_artifact(
                    execution_ctx,
                    db=db,
                    object_key=object_key,
                    mime="image/png",
                    size=len(png),
                    sha256=digest,
                    captured_at=captured_at,
                )
            else:
                from services import minio_store

                if minio_store.local_image_fallback_enabled():
                    object_key = None
                else:
                    raise CaptureError(
                        "object storage upload failed",
                        code="OBJECT_STORAGE_UNAVAILABLE",
                        details={"kind": execution_ctx.kind},
                    )

        handle = CaptureHandle(
            image_bytes=png,
            object_key=object_key,
            size_bytes=len(png),
            sha256=digest,
            captured_at=captured_at,
            artifact_id=artifact_id,
        )
        _cache_put(_screenshot_cache, cache_key, handle)
        self._observe_capture("screenshot", persist, started)
        return handle

    def capture_hierarchy(
        self,
        device: Any,
        *,
        persist: bool = True,
        execution_ctx: ExecutionCaptureContext | None = None,
        db=None,
    ) -> HierarchyHandle:
        started = time.perf_counter()
        self._ensure_device(device)
        serial = getattr(device, "serial", "unknown")
        step_index = execution_ctx.step_index if execution_ctx else None
        kind = execution_ctx.kind if execution_ctx else "hierarchy_snapshot"
        cache_key = (serial, step_index, kind)
        cached = _cache_get(_hierarchy_cache, cache_key)
        if cached is not None:
            return cached

        if persist and (execution_ctx is None or not execution_ctx.execution_id):
            raise CaptureError(
                "persist=True requires execution_ctx.execution_id",
                code="MISSING_CONTEXT",
            )

        xml = device.hierarchy_xml(force_refresh=True)
        if not xml or not str(xml).strip():
            raise CaptureError("hierarchy unavailable", code="DEVICE_OFFLINE")

        xml_bytes = xml.encode("utf-8") if isinstance(xml, str) else bytes(xml)
        from services.content.extraction.hierarchy.parser import parse_hierarchy_root

        try:
            root = parse_hierarchy_root(xml if isinstance(xml, str) else xml.decode("utf-8"))
        except Exception as exc:
            raise HierarchyParseError(
                f"hierarchy parse failed: {exc}",
                code="HIERARCHY_PARSE_ERROR",
            ) from exc

        digest = _sha256(xml_bytes)
        captured_at = datetime.now(timezone.utc)
        object_key: str | None = None
        artifact_id: str | None = None

        if persist and execution_ctx is not None:
            object_key = _object_key(execution_ctx, "xml")
            if self._upload(object_key, xml_bytes, "application/xml"):
                artifact_id = _try_persist_artifact(
                    execution_ctx,
                    db=db,
                    object_key=object_key,
                    mime="application/xml",
                    size=len(xml_bytes),
                    sha256=digest,
                    captured_at=captured_at,
                )
            else:
                object_key = None

        handle = HierarchyHandle(
            xml_bytes=xml_bytes,
            object_key=object_key,
            root=root,
            captured_at=captured_at,
            artifact_id=artifact_id,
        )
        _cache_put(_hierarchy_cache, cache_key, handle)
        self._observe_capture("hierarchy", persist, started)
        return handle

    @staticmethod
    def _crop_png(png: bytes, region: dict[str, float]) -> bytes:
        img = Image.open(io.BytesIO(png))
        w, h = img.size
        if {"x1", "y1", "x2", "y2"}.issubset(region):
            box = (
                int(float(region["x1"]) * w),
                int(float(region["y1"]) * h),
                int(float(region["x2"]) * w),
                int(float(region["y2"]) * h),
            )
        else:
            x = float(region.get("x", 0))
            y = float(region.get("y", 0))
            rw = float(region.get("w", 1.0))
            rh = float(region.get("h", 1.0))
            box = (int(x * w), int(y * h), int((x + rw) * w), int((y + rh) * h))
        cropped = img.crop(box)
        out = io.BytesIO()
        cropped.save(out, format="PNG")
        return out.getvalue()

    @staticmethod
    def _upload(object_key: str, data: bytes, mime: str) -> bool:
        from services import minio_store

        if not minio_store.enabled():
            return False
        return bool(minio_store.upload(data, object_key, content_type=mime))

    @staticmethod
    def _observe_capture(kind: str, persist: bool, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        try:
            from web.metrics import capture_latency_ms

            capture_latency_ms.labels(kind=kind, persist=str(persist).lower()).observe(elapsed_ms)
        except Exception:
            pass
        log.debug("capture %s persist=%s latency_ms=%.1f", kind, persist, elapsed_ms)


def _try_persist_artifact(
    execution_ctx: ExecutionCaptureContext,
    *,
    db,
    object_key: str,
    mime: str,
    size: int,
    sha256: str,
    captured_at: datetime,
) -> str | None:
    exec_id = str(execution_ctx.execution_id or "").strip()
    if not exec_id or exec_id == "direct":
        return None
    try:
        if db is not None:
            import asyncio

            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("sync persist with running loop requires run_activity_coro")
            return loop.run_until_complete(
                persist_capture_artifact(
                    db,
                    execution_ctx,
                    object_key=object_key,
                    mime=mime,
                    size=size,
                    sha256=sha256,
                    captured_at=captured_at,
                )
            )
        from db.database import activity_session, run_activity_coro

        async def _run() -> str:
            async with activity_session() as session:
                return await persist_capture_artifact(
                    session,
                    execution_ctx,
                    object_key=object_key,
                    mime=mime,
                    size=size,
                    sha256=sha256,
                    captured_at=captured_at,
                )

        return run_activity_coro(_run())
    except Exception as exc:
        log.warning(
            "execution_artifacts persist failed execution=%s kind=%s: %s",
            exec_id,
            execution_ctx.kind,
            exc,
        )
        return None


async def _resolve_artifact_tenant(
    db,
    execution_ctx: ExecutionCaptureContext,
) -> tuple[str, str | None]:
    """Resolve org_id (required) and optional device_id for execution_artifacts rows."""
    from sqlalchemy import select

    from db.models.execution import Execution, ExecutionDevice

    org_id = str(execution_ctx.org_id or "").strip()
    exec_row = await db.get(Execution, execution_ctx.execution_id)
    if exec_row and not org_id and exec_row.org_id:
        org_id = str(exec_row.org_id)
    if not org_id:
        raise ValueError(
            f"execution_artifacts requires org_id for execution {execution_ctx.execution_id}"
        )

    device_id = await db.scalar(
        select(ExecutionDevice.device_id)
        .where(ExecutionDevice.execution_id == execution_ctx.execution_id)
        .limit(1)
    )
    return org_id, str(device_id) if device_id else None


async def persist_capture_artifact(db, execution_ctx: ExecutionCaptureContext, *, object_key: str, mime: str, size: int, sha256: str, captured_at: datetime) -> str:
    from db.crud.execution_artifact import create_execution_artifact

    org_id, device_id = await _resolve_artifact_tenant(db, execution_ctx)
    kwargs: dict[str, Any] = dict(
        org_id=org_id,
        execution_id=execution_ctx.execution_id,
        step_index=execution_ctx.step_index,
        kind=execution_ctx.kind,
        object_key=object_key,
        content_type_mime=mime,
        size_bytes=size,
        sha256=sha256,
        captured_at=captured_at,
        retention_class=execution_ctx.retention_class,
    )
    if device_id:
        kwargs["device_id"] = device_id

    row = await create_execution_artifact(db, **kwargs)
    return row.id
