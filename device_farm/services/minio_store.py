"""
minio_store.py — Optional MinIO/S3 image storage with quality validation.

When MinIO is disabled (default), upload() returns None and callers fall back
to local filesystem storage — zero behaviour change.

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
    minio_store.init(cfg.minio)

    # In services that save images:
    from services import minio_store
    if minio_store.is_quality_ok(jpeg_bytes):
        url = minio_store.upload(jpeg_bytes, "screenshots/abc/step_0.jpg")
        if url:
            ...  # use MinIO URL
        else:
            ...  # save locally
"""
from __future__ import annotations

import io
import logging
from typing import Optional

log = logging.getLogger(__name__)

_client = None
_bucket: str = ""
_public_base_url: str = ""
_enabled: bool = False
_min_bytes: int = 3072  # updated by init() from MinioConfig


def init(config) -> None:
    """Initialise MinIO client from MinioConfig. Safe to call when disabled."""
    global _client, _bucket, _public_base_url, _enabled, _min_bytes
    _min_bytes = int(getattr(config, "min_image_bytes", 3072))
    if not config.enabled:
        return
    try:
        from minio import Minio  # type: ignore[import]
        _client = Minio(
            config.endpoint,
            access_key=config.access_key,
            secret_key=config.secret_key,
            secure=config.secure,
        )
        _bucket = config.bucket
        _public_base_url = (config.public_base_url or "").rstrip("/")
        if not _client.bucket_exists(_bucket):
            _client.make_bucket(_bucket)
            log.info("minio_store: created bucket %s", _bucket)
        _enabled = True
        log.info("minio_store: connected to %s bucket=%s", config.endpoint, _bucket)
    except ImportError:
        log.warning(
            "minio_store: 'minio' package not installed — pip install minio"
            " — falling back to local storage"
        )
    except Exception as exc:
        log.warning("minio_store: init failed (%s) — falling back to local storage", exc)


def enabled() -> bool:
    """True when MinIO is configured and reachable."""
    return _enabled


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
    Upload bytes to MinIO. Returns the public/presigned URL on success, None on failure.

    Check ``enabled()`` first if you need a local fallback.
    """
    if not _enabled or _client is None:
        return None
    try:
        _client.put_object(
            _bucket,
            object_name,
            io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )
        if _public_base_url:
            return f"{_public_base_url}/{_bucket}/{object_name}"
        from datetime import timedelta
        return _client.presigned_get_object(
            _bucket, object_name, expires=timedelta(weeks=1)
        )
    except Exception as exc:
        log.warning("minio_store: upload failed for %s: %s", object_name, exc)
        return None


def delete_prefix(prefix: str) -> None:
    """Delete all MinIO objects whose name starts with *prefix* (e.g. on scenario delete)."""
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
