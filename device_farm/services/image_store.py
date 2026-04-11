"""
image_store.py — Save/load step screenshots and element images.

Storage backends
~~~~~~~~~~~~~~~~
* Object storage / R2 (preferred): when ``minio_store.enabled()`` is True, images are
  uploaded to MinIO and URLs point to the MinIO object.
* Local filesystem (fallback): images saved to
  ``<captures_dir>/screenshots/<scenario_id>/step_<idx>_<type>.jpg``
  and served at ``/captures/screenshots/…``

Quality gate
~~~~~~~~~~~~
Images that fail ``minio_store.is_quality_ok()`` (blank/black frames) are
discarded entirely — no local write, no MinIO upload.
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path
from typing import Optional

from services import minio_store

log = logging.getLogger(__name__)

_CAPTURES_DIR: Path | None = None


def init(captures_dir: str | Path) -> None:
    global _CAPTURES_DIR
    _CAPTURES_DIR = Path(captures_dir)
    (_CAPTURES_DIR / "screenshots").mkdir(parents=True, exist_ok=True)


def _dir() -> Path:
    if _CAPTURES_DIR is None:
        raise RuntimeError("image_store not initialised — call init() first")
    return _CAPTURES_DIR


def _strip_data_url_prefix(value: str) -> str:
    """Accept both raw base64 and data URL payloads."""
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def _is_base64(value: str) -> bool:
    """True when value is a raw base64 string (not yet saved).

    Saved paths start with '/captures/' (local) or 'http' (MinIO).
    """
    return bool(value) and not value.startswith("/captures/") and not value.startswith("http")


def _save_image(data: bytes, local_path: Path, minio_key: str, skip_quality: bool = False) -> Optional[str]:
    """
    Persist image bytes via MinIO or local filesystem.

    Returns the URL/path string to store in the DB, or None when the image
    is rejected by the quality gate.
    skip_quality=True bypasses the blank-frame gate (used for element crops).
    """
    if not skip_quality and not minio_store.is_quality_ok(data):
        log.debug("image_store: skipped blank/black frame for %s", local_path.name)
        return None

    if minio_store.enabled():
        url = minio_store.upload(data, minio_key)
        if url:
            return url
        # Upload failed — fall through to local save

    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        # Return URL relative to the static mount point
        parts = local_path.parts
        # Find "screenshots" segment to build /captures/screenshots/... path
        try:
            idx = parts.index("screenshots")
            return "/captures/" + "/".join(parts[idx:])
        except ValueError:
            return f"/captures/{local_path.name}"
    except Exception as exc:
        log.warning("image_store: local save failed for %s: %s", local_path, exc)
        return None


def save_step_images(steps: list, scenario_id: str) -> list:
    """
    Walk steps, extract any base64 screenshot/element_image fields,
    validate quality, persist them, and replace with URL paths.

    Returns the modified steps list (original is not mutated).
    """
    base = _dir() / "screenshots" / scenario_id
    base.mkdir(parents=True, exist_ok=True)

    out = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            out.append(step)
            continue

        step = dict(step)
        screen = step.get("screen")
        if isinstance(screen, dict):
            screen = dict(screen)
            for field, suffix in (("screenshot", "screenshot"), ("element_image", "element")):
                val = screen.get(field)
                if val and _is_base64(val):
                    try:
                        raw = base64.b64decode(_strip_data_url_prefix(val), validate=True)
                    except Exception as exc:
                        log.warning("image_store: base64 decode failed for %s/%s: %s",
                                    scenario_id, field, exc)
                        continue
                    local_path = base / f"step_{idx}_{suffix}.jpg"
                    minio_key = f"screenshots/{scenario_id}/{local_path.name}"
                    # element_image is always an intentional element crop — skip
                    # blank-frame quality gate (which is designed to reject minicap
                    # black frames, not small UI element crops).
                    skip_quality = (field == "element_image")
                    url = _save_image(raw, local_path, minio_key, skip_quality=skip_quality)
                    if url:
                        screen[field] = url
                        log.debug("image_store: saved %s → %s", field, url)
                    else:
                        # Remove blank image so DB doesn't store it
                        screen.pop(field, None)
            step["screen"] = screen

        # tap_selector step stores element_image at top level
        val = step.get("element_image")
        if val and _is_base64(val):
            try:
                raw = base64.b64decode(_strip_data_url_prefix(val), validate=True)
            except Exception as exc:
                log.warning("image_store: base64 decode failed for top-level element_image: %s", exc)
                raw = None
            if raw is not None:
                local_path = base / f"step_{idx}_element.jpg"
                minio_key = f"screenshots/{scenario_id}/{local_path.name}"
                # top-level element_image is also an intentional crop and can be
                # very small; bypass blank-frame gate.
                url = _save_image(raw, local_path, minio_key, skip_quality=True)
                if url:
                    step["element_image"] = url
                else:
                    step.pop("element_image", None)

        out.append(step)
    return out


def delete_scenario_images(scenario_id: str) -> None:
    """Remove all saved images for a scenario (call on scenario delete)."""
    # MinIO cleanup
    minio_store.delete_prefix(f"screenshots/{scenario_id}/")

    # Local filesystem cleanup
    folder = _dir() / "screenshots" / scenario_id
    if folder.exists():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
