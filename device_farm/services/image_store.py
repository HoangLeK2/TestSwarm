"""
image_store.py — Save/load step screenshots and element images to disk.

Images are stored at:
  <captures_dir>/screenshots/<scenario_id>/step_<idx>_<type>.jpg

The DB only stores the relative URL path, e.g.:
  /captures/screenshots/abc123/step_0_screenshot.jpg
"""
from __future__ import annotations

import base64
import logging
from pathlib import Path

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


def _is_base64(value: str) -> bool:
    """True when value is a raw base64 string (not yet saved to disk).
    Saved paths always start with '/captures/'.
    """
    return bool(value) and not value.startswith("/captures/")


def save_step_images(steps: list, scenario_id: str) -> list:
    """
    Walk steps, extract any base64 screenshot/element_image fields,
    save them to disk and replace with URL paths.

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
                    path = base / f"step_{idx}_{suffix}.jpg"
                    try:
                        path.write_bytes(base64.b64decode(val))
                        screen[field] = f"/captures/screenshots/{scenario_id}/{path.name}"
                        log.debug("image_store: saved %s", path)
                    except Exception as exc:
                        log.warning("image_store: failed to save %s/%s: %s", scenario_id, field, exc)
            step["screen"] = screen

        # tap_selector step stores element_image at top level
        val = step.get("element_image")
        if val and _is_base64(val):
            path = base / f"step_{idx}_element.jpg"
            try:
                path.write_bytes(base64.b64decode(val))
                step["element_image"] = f"/captures/screenshots/{scenario_id}/{path.name}"
            except Exception as exc:
                log.warning("image_store: failed to save top-level element_image: %s", exc)

        out.append(step)
    return out


def delete_scenario_images(scenario_id: str) -> None:
    """Remove all saved images for a scenario (call on scenario delete)."""
    folder = _dir() / "screenshots" / scenario_id
    if folder.exists():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        try:
            folder.rmdir()
        except OSError:
            pass
