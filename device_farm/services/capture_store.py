"""
capture_store.py — Persist step captures (screenshots, XML, JSON) to MinIO or local.

Storage backends (same pattern as image_store.py):
* Object storage (MinIO/R2/S3): when ``minio_store.enabled()`` is True.
* Local filesystem (fallback): ``<captures_dir>/<session>/step_*.{jpg,xml,json}``

Quality gate applies only to image/* content types — XML and JSON always pass.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from services import minio_store

log = logging.getLogger(__name__)

_CAPTURES_DIR: Path | None = None


def init(captures_dir: str | Path) -> None:
    global _CAPTURES_DIR
    _CAPTURES_DIR = Path(captures_dir)
    _CAPTURES_DIR.mkdir(parents=True, exist_ok=True)


def _dir() -> Path:
    if _CAPTURES_DIR is None:
        raise RuntimeError("capture_store not initialised — call init() first")
    return _CAPTURES_DIR


def save_capture(
    data: bytes,
    local_path: str,
    minio_key: str,
    content_type: str = "image/jpeg",
    skip_quality: bool = False,
) -> Optional[str]:
    """
    Persist capture bytes via MinIO or local filesystem.

    Returns URL (MinIO) or local path string, or None if rejected by quality gate.
    Non-image content types (XML/JSON) always skip the quality gate.
    Set skip_quality=True for intentional captures that should bypass the
    blank-frame gate (which targets minicap streaming artifacts, not step captures).
    """
    is_image = content_type.startswith("image/")

    if is_image and not skip_quality and not minio_store.is_quality_ok(data):
        log.debug("capture_store: quality reject for %s", os.path.basename(local_path))
        return None

    if minio_store.enabled():
        url = minio_store.upload(data, minio_key, content_type=content_type)
        if url:
            return url

    try:
        p = Path(local_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        return local_path
    except Exception as exc:
        log.warning("capture_store: local save failed for %s: %s", local_path, exc)
        return None


def delete_captures(prefix: str) -> None:
    """Delete all MinIO objects whose name starts with *prefix*."""
    minio_store.delete_prefix(prefix)
