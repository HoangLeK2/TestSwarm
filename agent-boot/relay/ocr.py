"""On-device OCR for the relay — Tesseract subprocess over a device screenshot.

Runs OCR where the pixels already are. The alternative — shipping a ~800 KB
screenshot per call back to the farm — costs roughly 8 MB/s at the OCR rates
this farm runs at, aimed at a backend capped to 6 CPUs.

Engine notes:
  - Tesseract is invoked as a subprocess, so no Python OCR dependency is added
    (Pillow is already a relay dep) and the GIL is released while it runs.
  - Do NOT upscale. The classic "mobile screenshots are 72-96 DPI, scale 2-3x"
    advice does not hold for modern Android frames (1260x2800 for a 6" screen).
    Measured over 6 real screenshots: scale 1.0 → 285 words @ 90.2 confidence in
    234 ms/image; scale 2.0 → *fewer* words (268 @ 89.5) in 525 ms.
  - Crop to ``region`` before OCR, not after: a 30% band costs ~106 ms versus
    ~229 ms for the full screen.

The public surface is deliberately small (``run_ocr`` / ``available``) so the
engine can be swapped for an ONNX model later without touching the relay
protocol or the farm-side callers.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
from typing import Any

from PIL import Image, ImageFilter, ImageOps

logger = logging.getLogger("relay.ocr")

# Sparse text — screens are labels and buttons scattered around, not prose.
PSM_SPARSE = 11

_LANG_MAP = {"vi": "vie", "en": "eng", "vie": "vie", "eng": "eng"}
_DEFAULT_LANGS = ("vi", "en")
_MIN_CONFIDENCE = 0.5
# Tesseract's TSV columns; `conf` is a percentage and text is the last column.
_TSV_COLUMNS = 12
_TSV_CONF_IDX = 10
_TSV_TEXT_IDX = 11

_tesseract_cmd: str | None = None
_available: bool | None = None


def _cmd() -> str:
    global _tesseract_cmd
    if _tesseract_cmd is None:
        _tesseract_cmd = os.getenv("RELAY_TESSERACT_CMD") or shutil.which("tesseract") or "tesseract"
    return _tesseract_cmd


def available() -> bool:
    """True when a usable tesseract binary is on PATH. Cached after first probe."""
    global _available
    if _available is None:
        try:
            proc = subprocess.run([_cmd(), "--version"], capture_output=True, timeout=5)
            _available = proc.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            logger.info("tesseract unavailable (%s); OCR capability off", exc)
            _available = False
    return _available


def tesseract_lang(languages: Any) -> str:
    """Map farm language codes to a tesseract ``-l`` argument (e.g. "vie+eng")."""
    if isinstance(languages, str):
        languages = [languages]
    if not languages:
        languages = list(_DEFAULT_LANGS)
    parts: list[str] = []
    for lang in languages:
        code = _LANG_MAP.get(str(lang).strip().lower(), str(lang).strip().lower())
        if code and code not in parts:
            parts.append(code)
    return "+".join(parts) if parts else "eng"


def _crop(
    img: Image.Image, region: dict[str, float] | None
) -> tuple[Image.Image, int, int]:
    """Crop to a normalised region, returning the image and its origin.

    Accepts x1/y1/x2/y2 or x/y/w/h. The origin is returned rather than
    recomputed by the caller: it has to match the clamping applied here, or
    every box gets shifted for regions that run past the image edge.
    """
    if not region:
        return img, 0, 0
    w, h = img.size
    try:
        if {"x1", "y1", "x2", "y2"} <= region.keys():
            box = (
                int(float(region["x1"]) * w),
                int(float(region["y1"]) * h),
                int(float(region["x2"]) * w),
                int(float(region["y2"]) * h),
            )
        elif {"x", "y", "w", "h"} <= region.keys():
            x, y = float(region["x"]), float(region["y"])
            box = (
                int(x * w),
                int(y * h),
                int((x + float(region["w"])) * w),
                int((y + float(region["h"])) * h),
            )
        else:
            return img, 0, 0
    except (TypeError, ValueError):
        return img, 0, 0
    left, top, right, bottom = box
    if right <= left or bottom <= top:
        return img, 0, 0
    left, top = max(0, left), max(0, top)
    return img.crop((left, top, min(w, right), min(h, bottom))), left, top


def _preprocess(img: Image.Image) -> Image.Image:
    """Grayscale → sharpen → binarize. No rescale (see module docstring).

    SHARPEN earns its ~18ms: measured over 6 real screenshots it is 234ms for
    285 words with it versus 216ms for 271 without — 8% faster, 5% blinder.
    """
    img = ImageOps.grayscale(img).filter(ImageFilter.SHARPEN)
    # Mean threshold: a cheap Otsu stand-in that avoids pulling in numpy.
    hist = img.histogram()
    total = sum(hist)
    if not total:
        return img
    mean = sum(i * n for i, n in enumerate(hist)) // total
    return img.point(lambda p: 255 if p > mean else 0)


def _run_tesseract_tsv(img: Image.Image, lang: str, psm: int, timeout: float) -> list[list[str]]:
    """Feed the image to tesseract over stdin and parse its TSV output.

    Piping avoids a temp file per call — measured ~30ms cheaper than writing
    and re-reading a PNG, and it leaves nothing behind in /tmp if the process
    is killed mid-OCR. PNG (not BMP) on purpose: an uncompressed 3.5MB buffer
    through the pipe measured *slower* than compressing it first.
    """
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    try:
        # Each flag and its value must be a separate argv entry. Passing
        # "--psm 11" as one entry makes tesseract exit 1 with "unknown command
        # line argument", which reads as "no text on screen" downstream.
        proc = subprocess.run(
            [_cmd(), "stdin", "stdout", "-l", lang,
             "--psm", str(psm), "--oem", "3", "tsv"],
            input=buf.getvalue(), capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.warning("tesseract timed out after %.1fs lang=%s", timeout, lang)
        return []
    except OSError as exc:
        logger.warning("tesseract exec failed: %s", exc)
        return []

    if proc.returncode != 0:
        logger.warning(
            "tesseract tsv failed rc=%s lang=%s: %s",
            proc.returncode, lang, proc.stderr.decode("utf-8", "replace").strip()[:200],
        )
        return []

    lines = proc.stdout.decode("utf-8", "replace").strip().split("\n")
    if len(lines) < 2:
        return []
    return [cols for cols in (line.split("\t") for line in lines[1:]) if len(cols) == _TSV_COLUMNS]


def run_ocr(
    image_bytes: bytes,
    *,
    languages: Any = None,
    region: dict[str, float] | None = None,
    min_confidence: float = _MIN_CONFIDENCE,
    psm: int = PSM_SPARSE,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """OCR a screenshot, returning boxes in *original image* coordinates.

    Each box is ``{text, left, top, width, height, conf}`` with ``conf`` as a
    0-100 percentage, matching what the farm's ``_to_bbox`` already expects.
    Returns [] rather than raising when the engine is missing or the image is
    unreadable — a blank screen is a normal result, not an error.
    """
    if not image_bytes or not available():
        return []
    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as exc:
        logger.warning("OCR could not decode screenshot (%d bytes): %s", len(image_bytes), exc)
        return []

    try:
        # Crop before any colour conversion so a region read only pays for the
        # pixels it needs; _preprocess does the single conversion to greyscale.
        cropped, offset_x, offset_y = _crop(img, region)
        rows = _run_tesseract_tsv(_preprocess(cropped), tesseract_lang(languages), psm, timeout)
    except Exception as exc:
        logger.warning("OCR failed on a %s image: %s", img.mode, exc)
        return []

    threshold = min_confidence * 100 if min_confidence <= 1 else min_confidence
    out: list[dict[str, Any]] = []
    for cols in rows:
        text = cols[_TSV_TEXT_IDX].strip()
        if not text:
            continue
        try:
            conf = float(cols[_TSV_CONF_IDX])
            left, top, width, height = (int(cols[i]) for i in (6, 7, 8, 9))
        except (TypeError, ValueError):
            continue
        if conf < threshold:
            continue
        out.append({
            "text": text,
            "left": left + offset_x,
            "top": top + offset_y,
            "width": width,
            "height": height,
            "conf": int(conf),
        })
    return out
