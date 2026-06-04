"""
minio_store.py — S3-compatible image storage (Cloudflare R2, MinIO, …).

Production image captures must live in object storage. Local image fallback is
debug-only and is controlled by ``DEVICE_FARM_LOCAL_IMAGE_FALLBACK_ENABLED``.

Quality gate
~~~~~~~~~~~~
Blank/black frames produced by minicap during device state transitions are
typically compressed to < 2 KB by JPEG at any quality level. Images below
``min_bytes`` (default 3 KB) are rejected before saving. If PIL/NumPy are
available, an additional brightness check rejects near-black frames even when
compression gave a slightly larger file.

Usage
~~~~~
    # In server startup:
    from services import minio_store
    minio_store.init(cfg.object_storage)

    # In services that save images:
    from services import minio_store
    if minio_store.is_quality_ok(jpeg_bytes):
        url = minio_store.upload(jpeg_bytes, "screenshots/abc/step_0.jpg")
        if url:
            ...  # use object storage URL
        else:
            ...  # save locally
"""
from __future__ import annotations

import io
import logging
import threading
from typing import Optional

log = logging.getLogger(__name__)

_client = None
_bucket: str = ""
_public_base_url: str = ""
_public_url_include_bucket: bool = True
_enabled: bool = False
_min_bytes: int = 3072  # updated by init() from ObjectStorageConfig
_local_image_fallback_enabled: bool = False
_max_concurrent_uploads: int = 8
_upload_semaphore = threading.BoundedSemaphore(_max_concurrent_uploads)


def _endpoint_host(endpoint: str) -> str:
    ep = (endpoint or "").strip()
    for prefix in ("https://", "http://"):
        if ep.lower().startswith(prefix):
            ep = ep[len(prefix) :]
    return ep.split("/")[0].rstrip("/")


def init(config) -> None:
    """Initialise S3 client from ObjectStorageConfig. Safe to call when disabled."""
    global _client, _bucket, _public_base_url, _public_url_include_bucket, _enabled
    global _min_bytes, _local_image_fallback_enabled, _max_concurrent_uploads, _upload_semaphore
    _client = None
    _bucket = ""
    _public_base_url = ""
    _public_url_include_bucket = True
    _enabled = False
    _min_bytes = int(getattr(config, "min_image_bytes", 3072))
    _local_image_fallback_enabled = bool(getattr(config, "local_image_fallback_enabled", False))
    _max_concurrent_uploads = max(1, int(getattr(config, "max_concurrent_uploads", 8) or 8))
    _upload_semaphore = threading.BoundedSemaphore(_max_concurrent_uploads)
    if not config.enabled:
        return
    endpoint = _endpoint_host(getattr(config, "endpoint", "") or "")
    if not endpoint:
        log.warning("minio_store: object storage enabled but endpoint is empty — disabled")
        return
    try:
        from minio import Minio  # type: ignore[import]
        region = (getattr(config, "region", "") or "").strip()
        if not region and "r2.cloudflarestorage.com" in endpoint.lower():
            region = "auto"
        client_kwargs = dict(
            endpoint=endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=bool(config.secure),
        )
        if region:
            client_kwargs["region"] = region
        _client = Minio(**client_kwargs)
        _bucket = config.bucket
        _public_base_url = (config.public_base_url or "").rstrip("/")
        _public_url_include_bucket = bool(getattr(config, "public_url_include_bucket", True))
        if not _client.bucket_exists(_bucket):
            _client.make_bucket(_bucket)
            log.info("minio_store: created bucket %s", _bucket)
        _enabled = True
        log.info(
            "minio_store: connected to %s bucket=%s max_concurrent_uploads=%s",
            endpoint,
            _bucket,
            _max_concurrent_uploads,
        )
    except ImportError:
        log.warning(
            "minio_store: 'minio' package not installed — pip install minio"
            " — falling back to local storage"
        )
    except Exception as exc:
        log.warning("minio_store: init failed (%s) — falling back to local storage", exc)


def enabled() -> bool:
    """True when S3-compatible storage is configured and reachable."""
    return _enabled


def local_image_fallback_enabled() -> bool:
    """True only for explicit debug runs that may write image files locally."""
    return _local_image_fallback_enabled


def is_quality_ok(data: bytes, min_bytes: Optional[int] = None) -> bool:
    """
    Return True when the image passes the quality gate.

    Rejects:
    - Images smaller than ``min_bytes`` bytes (blank/black frames compress tiny).
    - Near-black frames: mean pixel brightness < 5/255 (PIL required; skipped
      gracefully if not available).
    """
    threshold = min_bytes if min_bytes is not None else _min_bytes
    if len(data) < threshold:
        log.debug("minio_store: quality reject — size %d < %d bytes", len(data), threshold)
        return False
    try:
        from PIL import Image  # type: ignore[import]
        import numpy as np  # type: ignore[import]
        img = Image.open(io.BytesIO(data)).convert("L")
        mean_brightness = float(np.array(img).mean())
        if mean_brightness < 5.0:
            log.debug("minio_store: quality reject — brightness %.1f", mean_brightness)
            return False
    except Exception:
        pass  # PIL / NumPy not available — trust size check alone
    return True


def upload(data: bytes, object_name: str, content_type: str = "image/jpeg") -> Optional[str]:
    """
    Upload bytes to the configured bucket. Returns public or presigned URL on success.

    Check ``enabled()`` first if you need a local fallback.
    """
    if not _enabled or _client is None:
        return None
    try:
        with _upload_semaphore:
            _client.put_object(
                _bucket,
                object_name,
                io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
        if _public_base_url:
            if _public_url_include_bucket:
                return f"{_public_base_url}/{_bucket}/{object_name}"
            return f"{_public_base_url}/{object_name}"
        from datetime import timedelta
        return _client.presigned_get_object(
            _bucket, object_name, expires=timedelta(weeks=1)
        )
    except Exception as exc:
        log.warning("minio_store: upload failed for %s: %s", object_name, exc)
        return None


def presigned_get(object_name: str, *, expires_seconds: int = 3600) -> str | None:
    """Return presigned GET URL with configurable TTL (Epic 06 artifact preview)."""
    if not _enabled or _client is None:
        return None
    try:
        from datetime import timedelta

        return _client.presigned_get_object(
            _bucket,
            object_name,
            expires=timedelta(seconds=max(60, min(expires_seconds, 86400))),
        )
    except Exception as exc:
        log.warning("minio_store: presigned_get failed for %s: %s", object_name, exc)
        return None


def get_object_bytes(object_name: str) -> bytes | None:
    """Fetch object bytes from the configured bucket."""
    if not _enabled or _client is None:
        return None
    try:
        response = _client.get_object(_bucket, object_name)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception as exc:
        log.warning("minio_store: get_object failed for %s: %s", object_name, exc)
        return None


def delete_object(object_name: str) -> bool:
    """Delete a single object from the configured bucket."""
    if not _enabled or _client is None:
        return False
    try:
        _client.remove_object(_bucket, object_name)
        return True
    except Exception as exc:
        log.warning("minio_store: delete_object failed for %s: %s", object_name, exc)
        return False


def delete_prefix(prefix: str) -> None:
    """Delete all objects whose name starts with *prefix* (e.g. on scenario delete)."""
    if not _enabled or _client is None:
        return
    try:
        from minio.deleteobjects import DeleteObject  # type: ignore[import]
        objects = _client.list_objects(_bucket, prefix=prefix, recursive=True)
        errors = list(
            _client.remove_objects(_bucket, (DeleteObject(o.object_name) for o in objects))
        )
        for err in errors:
            log.warning("minio_store: delete error: %s", err)
    except Exception as exc:
        log.warning("minio_store: delete_prefix failed for %s: %s", prefix, exc)
