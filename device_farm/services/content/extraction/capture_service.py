"""Screenshot + hierarchy capture for extraction pipeline (DF-T-06-003)."""
from __future__ import annotations

import hashlib
import io
import logging
import time
from datetime import datetime, timezone
from typing import Any

from PIL import Image, ImageDraw

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
    """Re-encode a device frame to PNG.

    ``optimize=True`` is deliberately not used: on a 1260x2800 device frame it
    costs ~260ms versus ~57ms, and saves ~1% of the output size.
    """
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return raw
    try:
        img = Image.open(io.BytesIO(raw))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as exc:
        raise CaptureError(
            "unsupported screenshot format",
            code="CAPTURE_FORMAT_INVALID",
            details={"error": str(exc)},
        ) from exc


def _diagnostic_png_from_hierarchy(device: Any, serial: str, kind: str) -> bytes | None:
    hierarchy = None
    try:
        hierarchy = device.hierarchy_xml(force_refresh=True)
    except TypeError:
        try:
            hierarchy = device.hierarchy_xml()
        except Exception:
            hierarchy = None
    except Exception:
        hierarchy = None
    if not hierarchy:
        return None
    text = str(hierarchy)
    tokens: list[str] = []
    for marker in ('text="', 'content-desc="', 'resource-id="'):
        start = 0
        while len(tokens) < 18:
            idx = text.find(marker, start)
            if idx < 0:
                break
            idx += len(marker)
            end = text.find('"', idx)
            if end < 0:
                break
            value = text[idx:end].strip()
            if value and value not in tokens:
                tokens.append(value[:120])
            start = end + 1
    lines = [
        "Device Farm failure evidence",
        "Screenshot unavailable; using UI hierarchy snapshot.",
        f"serial: {serial}",
        f"kind: {kind}",
        "",
        "Visible hierarchy tokens:",
        *(tokens or ["<no text/content-desc/resource-id tokens>"]),
    ]
    width, height = 900, 1200
    image = Image.new("RGB", (width, height), color=(248, 250, 252))
    draw = ImageDraw.Draw(image)
    y = 32
    for line in lines:
        draw.text((32, y), line, fill=(15, 23, 42))
        y += 30
        if y > height - 40:
            break
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


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
        # A failure screenshot must be the screen at the moment of failure. The
        # 30s cache is right for pre/post (same screen, repeated reads) and wrong
        # here: it hands back a frame from before the step that just broke.
        if not kind.endswith("_fail"):
            cached = _cache_get(_screenshot_cache, cache_key)
            if cached is not None:
                return cached

        if persist and (execution_ctx is None or not execution_ctx.execution_id):
            raise CaptureError(
                "persist=True requires execution_ctx.execution_id",
                code="MISSING_CONTEXT",
            )

        raw = device.take_screenshot()
        if not raw and kind.endswith("_fail"):
            request_frames = getattr(device, "request_stream_jpeg_frames", None)
            if callable(request_frames):
                try:
                    request_frames(duration_s=2.0)
                    deadline = time.monotonic() + 1.5
                    while not raw and time.monotonic() < deadline:
                        time.sleep(0.1)
                        raw = device.take_screenshot()
                except Exception:
                    raw = None
            fresh_capture = getattr(device, "capture_screenshot", None)
            if not raw and callable(fresh_capture):
                try:
                    raw = fresh_capture(
                        allow_ws_u2_fallback=True,
                        skip_cache=True,
                    )
                except TypeError:
                    raw = fresh_capture()
                if not isinstance(raw, (bytes, bytearray)):
                    raw = None
            if not raw:
                raw = _diagnostic_png_from_hierarchy(device, serial, kind)
        if not raw:
            raise CaptureError("device screenshot unavailable", code="DEVICE_OFFLINE")

        # Always PNG: callers write these bytes out as .png with an image/png
        # content type regardless of `persist` (see epic06_capture_adapter), so
        # handing back a raw JPEG here would mislabel the stored file.
        image = _png_bytes(raw)

        digest = _sha256(image)
        captured_at = datetime.now(timezone.utc)
        object_key: str | None = None
        artifact_id: str | None = None

        if persist and execution_ctx is not None:
            object_key, artifact_id = self._store_image(
                image, execution_ctx, db=db, digest=digest, captured_at=captured_at
            )

        handle = CaptureHandle(
            image_bytes=image,
            object_key=object_key,
            size_bytes=len(image),
            sha256=digest,
            captured_at=captured_at,
            artifact_id=artifact_id,
        )
        # Not cached when it is never read: entries are only evicted by a later
        # _cache_get on the same key, so caching fail frames would pin their PNG
        # bytes in a long-running worker for good.
        if not kind.endswith("_fail"):
            _cache_put(_screenshot_cache, cache_key, handle)
        self._observe_capture("screenshot", persist, started)
        return handle

    def _store_image(
        self,
        image: bytes,
        execution_ctx: ExecutionCaptureContext,
        *,
        db=None,
        digest: str | None = None,
        captured_at: datetime | None = None,
    ) -> tuple[str | None, str | None]:
        """Upload one screenshot and record it as an execution artifact."""
        digest = digest or _sha256(image)
        captured_at = captured_at or datetime.now(timezone.utc)
        object_key = _object_key(execution_ctx, "png")
        if not self._upload(object_key, image, "image/png"):
            from services import minio_store

            if minio_store.local_image_fallback_enabled():
                return None, None
            raise CaptureError(
                "object storage upload failed",
                code="OBJECT_STORAGE_UNAVAILABLE",
                details={"kind": execution_ctx.kind},
            )
        artifact_id = _try_persist_artifact(
            execution_ctx,
            db=db,
            object_key=object_key,
            mime="image/png",
            size=len(image),
            sha256=digest,
            captured_at=captured_at,
        )
        return object_key, artifact_id

    def persist_image(
        self,
        image: bytes,
        *,
        execution_ctx: ExecutionCaptureContext,
        db=None,
    ) -> str | None:
        """Store a screenshot the caller already has; returns the artifact id.

        Used for frames that were captured on agent-boot rather than here — the
        OCR path only ships one back when a read comes up empty.
        """
        if not image:
            return None
        png = _png_bytes(image)
        _, artifact_id = self._store_image(png, execution_ctx, db=db)
        return artifact_id

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
