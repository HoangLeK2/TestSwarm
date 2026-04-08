"""
OCR Engine — Tesseract wrapper with preprocessing optimized for mobile screenshots.

Performance notes:
  - Tesseract works best at 300+ DPI; mobile screenshots are ~72-96 DPI → upscale 2-3x
  - Preprocessing order matters: scale → grayscale → sharpen → binarize
  - PSM 11 (sparse) for full screenshots, PSM 7 (single line) for elements
  - Each tesseract call spawns a subprocess (~50ms + ~50MB RAM)
  - Limit concurrent calls to min(cpu_count, 4) to avoid memory explosion
"""
from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np
from PIL import Image, ImageFilter, ImageOps

log = logging.getLogger(__name__)

# PSM modes for reference
PSM_AUTO = 3            # Fully automatic page segmentation
PSM_SINGLE_BLOCK = 6   # Assume single uniform block of text
PSM_SINGLE_LINE = 7    # Treat as single text line
PSM_SINGLE_WORD = 8    # Treat as single word
PSM_SPARSE = 11         # Sparse text — find as much text as possible


class OCREngine:
    """Tesseract OCR with image preprocessing tuned for mobile screenshots."""

    def __init__(self, tesseract_cmd: str | None = None, max_workers: int = 4) -> None:
        self._cmd = tesseract_cmd or shutil.which("tesseract") or "tesseract"
        self._max_workers = max_workers
        self._available: bool | None = None

    @property
    def available(self) -> bool:
        if self._available is None:
            self._available = self._check()
        return self._available

    def _check(self) -> bool:
        try:
            r = subprocess.run(
                [self._cmd, "--version"],
                capture_output=True, timeout=5,
            )
            return r.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def extract_text(
        self,
        image_bytes: bytes,
        language: str = "eng",
        region: dict[str, float] | None = None,
        psm: int = PSM_SPARSE,
        preprocess: bool = True,
        scale_factor: float = 2.0,
        whitelist: str | None = None,
    ) -> str:
        if not self.available:
            raise RuntimeError(
                "Tesseract not installed. Install: brew install tesseract (macOS) "
                "or apt-get install tesseract-ocr (Linux)"
            )

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        if region:
            img = self._crop_region(img, region)

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
        scale_factor: float = 2.0,
    ) -> list[dict[str, Any]]:
        if not self.available:
            raise RuntimeError("Tesseract not installed")

        img = Image.open(io.BytesIO(image_bytes))
        if img.mode == "RGBA":
            img = img.convert("RGB")

        orig_w, orig_h = img.size

        if region:
            img = self._crop_region(img, region)

        crop_w, crop_h = img.size

        if preprocess:
            img = self._preprocess(img, scale_factor=scale_factor)

        tsv = self._run_tesseract_tsv(img, language, psm)
        results = []
        for entry in tsv:
            if entry.get("conf", -1) < 0 or not entry.get("text", "").strip():
                continue
            # Scale coordinates back to original image space
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

    @staticmethod
    def _preprocess(img: Image.Image, scale_factor: float = 2.0) -> Image.Image:
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
                 f"--psm {psm}", "--oem 3", "tsv"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
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
