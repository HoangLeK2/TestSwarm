"""DF-009: OCR & Screen Text Extraction.

Provides three extraction strategies:
  1. UI Hierarchy text parsing (free, fastest, native text only)
  2. OCR via Tesseract (free, handles WebView/Canvas/images)
  3. AI Vision via OpenAI/Gemini (paid, best for structured data extraction)
"""
from runtime.extraction.ocr_engine import OCREngine
from runtime.extraction.ai_vision import AIVisionExtractor
from runtime.extraction.hierarchy_extractor import HierarchyExtractor

__all__ = ["OCREngine", "AIVisionExtractor", "HierarchyExtractor"]
