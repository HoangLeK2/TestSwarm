"""
OCR Engine — PaddleOCR primary, Tesseract subprocess fallback.

Backend selection (auto):
  1. PaddleOCR if `paddleocr` installed (~96% accuracy, fast, no subprocess overhead)
  2. Tesseract subprocess if `tesseract` binary on PATH (legacy fallback)
  3. RuntimeError if neither available

PaddleOCR notes:
  - Lazy singleton init (~1-2s first call, subsequent <50ms)
  - GPU off by default; set `OCR_USE_GPU=1` to enable
  - Confidence threshold via `min_confidence` param (default 0.7)

Tesseract notes (legacy path, kept for backwards compat):
  - Do NOT upscale modern Android screenshots. They are already dense (1260x2800
    for a 6" screen), so the classic "72-96 DPI → upscale 2-3x" advice hurts here.
    Measured over six representative mobile screenshots: scale 1.0 gave 285 words @ 90.2 conf
    in 234ms/image, scale 2.0 gave *fewer* words (268 @ 89.5) in 525ms. Hence
    `scale_factor` defaults to 1.0 — raise it only for genuinely low-res sources.
  - Preprocessing order matters: scale → grayscale → sharpen → binarize
  - PSM 11 (sparse) for full screenshots, PSM 7 (single line) for elements
  - Each tesseract call spawns a subprocess (~50ms + ~50MB RAM)
  - Limit concurrent calls to min(cpu_count, 4) to avoid memory explosion
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)

# PSM modes for reference (Tesseract backend only)
PSM_AUTO = 3            # Fully automatic page segmentation
PSM_SINGLE_BLOCK = 6    # Assume single uniform block of text
PSM_SINGLE_LINE = 7     # Treat as single text line
PSM_SINGLE_WORD = 8     # Treat as single word
PSM_SPARSE = 11         # Sparse text — find as much text as possible


# ─── PaddleOCR singleton (lazy import; heavy deps) ──────────────────────────
_paddle_singleton: Any = None
_paddle_unavailable: bool = False


def _get_paddle() -> Any:
    """Return PaddleOCR instance or None if not available."""
    global _paddle_singleton, _paddle_unavailable
    if _paddle_unavailable:
        return None
    if _paddle_singleton is not None:
        return _paddle_singleton
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:
        _paddle_unavailable = True
        return None
    try:
        _paddle_singleton = PaddleOCR(
            use_angle_cls=True,
            lang=os.getenv("OCR_LANG", "en"),
            use_gpu=os.getenv("OCR_USE_GPU", "0").lower() in {"1", "true", "yes"},
            show_log=False,
        )
    except Exception as exc:
        log.warning("PaddleOCR init failed (%s); falling back to Tesseract", exc)
        _paddle_unavailable = True
        return None
    return _paddle_singleton


class OCREngine:
    """OCR with auto backend selection (PaddleOCR → Tesseract fallback)."""

    def __init__(
        self,
        tesseract_cmd: str | None = None,
        max_workers: int = 4,
        backend: str | None = None,
    ) -> None:
        """
        backend: "paddle", "tesseract", or None (auto-select).
        """
        self._cmd = tesseract_cmd or shutil.which("tesseract") or "tesseract"
        self._max_workers = max_workers
        self._tesseract_available: bool | None = None
        self._backend = backend  # explicit override, else auto

    # ─── Backend resolution ──────────────────────────────────────────────
    @property
    def available(self) -> bool:
        """True if any OCR backend is available."""
        if self._backend == "paddle":
            return _get_paddle() is not None
        if self._backend == "tesseract":
            return self._tesseract_check()
        # auto: prefer Paddle, else Tesseract
        return _get_paddle() is not None or self._tesseract_check()

    def _resolve_backend(self) -> str:
        # Validate explicit backend choice still works.
        if self._backend == "paddle":
            if _get_paddle() is not None:
                return "paddle"
        elif self._backend == "tesseract":
            if self._tesseract_check():
                return "tesseract"
        elif self._backend is None:
            # auto: prefer Paddle, else Tesseract
            if _get_paddle() is not None:
                return "paddle"
            if self._tesseract_check():
                return "tesseract"
        raise RuntimeError(
            "No OCR backend available. Install PaddleOCR (`pip install device-farm[ocr]`) "
            "or install Tesseract binary (`brew install tesseract` / `apt-get install tesseract-ocr`)."
        )

    def _tesseract_check(self) -> bool:
        if self._tesseract_available is None:
            try:
                r = subprocess.run([self._cmd, "--version"], capture_output=True, timeout=5)
                self._tesseract_available = r.returncode == 0
            except (FileNotFoundError, subprocess.TimeoutExpired):
                self._tesseract_available = False
        return self._tesseract_available

    # ─── Public API (unchanged signatures) ───────────────────────────────
    def extract_text(
        self,
        image_bytes: bytes,
        language: str = "eng",
        region: dict[str, float] | None = None,
        psm: int = PSM_SPARSE,
        preprocess: bool = True,
        scale_factor: float = 1.0,
        whitelist: str | None = None,
        min_confidence: float = 0.7,
    ) -> str:
        backend = self._resolve_backend()
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")
        if region:
            img = self._crop_region(img, region)

        if backend == "paddle":
            return self._paddle_text(img, min_confidence=min_confidence)

        # tesseract path
        if preprocess:
            img = self._preprocess(img, scale_factor=scale_factor)
        return self._run_tesseract(img, language, psm, whitelist)

    def extract_with_boxes(
        self,
        image_bytes: bytes,
        language: str = "eng",
        region: dict[str, float] | None = None,
        psm: int = PSM_SPARSE,
        preprocess: bool = True,
        scale_factor: float = 1.0,
        min_confidence: float = 0.7,
    ) -> list[dict[str, Any]]:
        backend = self._resolve_backend()
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        if region:
            img = self._crop_region(img, region)

        if backend == "paddle":
            return self._paddle_boxes(img, min_confidence=min_confidence)

        # tesseract path
        crop_w, crop_h = img.size
        if preprocess:
            img = self._preprocess(img, scale_factor=scale_factor)
        tsv = self._run_tesseract_tsv(img, language, psm)
        results = []
        for entry in tsv:
            if entry.get("conf", -1) < 0 or not entry.get("text", "").strip():
                continue
            sx = crop_w / img.width if img.width else 1
            sy = crop_h / img.height if img.height else 1
            results.append({
                "text": entry["text"].strip(),
                "left": int(entry["left"] * sx),
                "top": int(entry["top"] * sy),
                "width": int(entry["width"] * sx),
                "height": int(entry["height"] * sy),
                "conf": entry["conf"],
            })
        return results

    # ─── PaddleOCR helpers ───────────────────────────────────────────────
    @staticmethod
    def _paddle_text(img: Image.Image, min_confidence: float = 0.7) -> str:
        ocr = _get_paddle()
        if ocr is None:
            return ""
        arr = np.array(img)
        try:
            result = ocr.ocr(arr, cls=True)
        except Exception as exc:
            log.warning("PaddleOCR call failed: %s", exc)
            return ""
        if not result or not result[0]:
            return ""
        lines = []
        for line in result[0]:
            try:
                _box, (text, conf) = line[0], line[1]
                if conf >= min_confidence and text:
                    lines.append(text)
            except (IndexError, ValueError, TypeError):
                continue
        return "\n".join(lines).strip()

    @staticmethod
    def _paddle_boxes(img: Image.Image, min_confidence: float = 0.7) -> list[dict[str, Any]]:
        ocr = _get_paddle()
        if ocr is None:
            return []
        arr = np.array(img)
        try:
            result = ocr.ocr(arr, cls=True)
        except Exception as exc:
            log.warning("PaddleOCR call failed: %s", exc)
            return []
        if not result or not result[0]:
            return []
        out: list[dict[str, Any]] = []
        for line in result[0]:
            try:
                box, (text, conf) = line[0], line[1]
                if conf < min_confidence or not text:
                    continue
                # box = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]; bounding rect:
                xs = [pt[0] for pt in box]
                ys = [pt[1] for pt in box]
                left, top = int(min(xs)), int(min(ys))
                right, bottom = int(max(xs)), int(max(ys))
                out.append({
                    "text": text,
                    "left": left,
                    "top": top,
                    "width": right - left,
                    "height": bottom - top,
                    "conf": int(conf * 100),  # percent for parity with tesseract
                })
            except (IndexError, ValueError, TypeError):
                continue
        return out

    # ─── Tesseract helpers (legacy fallback) ─────────────────────────────
    @staticmethod
    def _preprocess(img: Image.Image, scale_factor: float = 1.0) -> Image.Image:
        if scale_factor > 1.0:
            new_size = (int(img.width * scale_factor), int(img.height * scale_factor))
            img = img.resize(new_size, Image.LANCZOS)

        img = ImageOps.grayscale(img)
        img = img.filter(ImageFilter.SHARPEN)

        arr = np.array(img)
        threshold = int(arr.mean())  # simple Otsu approximation
        arr = ((arr > threshold) * 255).astype(np.uint8)
        img = Image.fromarray(arr)

        return img

    @staticmethod
    def _crop_region(img: Image.Image, region: dict[str, float]) -> Image.Image:
        w, h = img.size
        box = (
            int(region.get("x1", 0) * w),
            int(region.get("y1", 0) * h),
            int(region.get("x2", 1.0) * w),
            int(region.get("y2", 1.0) * h),
        )
        return img.crop(box)

    def _run_tesseract(
        self, img: Image.Image, lang: str, psm: int, whitelist: str | None,
    ) -> str:
        config_parts = [f"--psm {psm}", "--oem 3"]
        if whitelist:
            config_parts.append(f"-c tessedit_char_whitelist={whitelist}")
        config = " ".join(config_parts)

        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            img.save(tmp.name, format="PNG")
            result = subprocess.run(
                [self._cmd, tmp.name, "stdout", "-l", lang] + config.split(),
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0 and result.stderr:
                log.debug(f"Tesseract stderr: {result.stderr[:200]}")
            return result.stdout.strip()

    def _run_tesseract_tsv(
        self, img: Image.Image, lang: str, psm: int,
    ) -> list[dict[str, Any]]:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=True) as tmp:
            img.save(tmp.name, format="PNG")
            result = subprocess.run(
                [self._cmd, tmp.name, "stdout", "-l", lang,
                 "--psm", str(psm), "--oem", "3", "tsv"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                log.warning(
                    "Tesseract tsv failed rc=%s: %s",
                    result.returncode, result.stderr.strip()[:200],
                )
                return []

            lines = result.stdout.strip().split("\n")
            if len(lines) < 2:
                return []

            headers = lines[0].split("\t")
            entries = []
            for line in lines[1:]:
                cols = line.split("\t")
                if len(cols) != len(headers):
                    continue
                entry = dict(zip(headers, cols))
                try:
                    entry["conf"] = int(float(entry.get("conf", -1)))
                    entry["left"] = int(entry.get("left", 0))
                    entry["top"] = int(entry.get("top", 0))
                    entry["width"] = int(entry.get("width", 0))
                    entry["height"] = int(entry.get("height", 0))
                except (ValueError, TypeError):
                    continue
                entries.append(entry)
            return entries
