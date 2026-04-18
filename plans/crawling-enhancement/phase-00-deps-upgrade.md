# Phase 0: Dependency Upgrades (Quick Wins)

## Objective

Thêm các thư viện bổ sung từ research `research_mobile_crawl_libraries_2025.md`. Không thay đổi logic — chỉ upgrade/add deps và swap các call sites. Làm trước Phase 1 vì ít rủi ro, lợi ích ngay lập tức.

**Effort**: 1-2 ngày  
**Risk**: Thấp

---

## 0.1 Logging — Thay stdlib logging bằng loguru

**File**: `device_farm/pyproject.toml`
```toml
loguru = "^0.7"
```

**Migration** — tìm tất cả `import logging` trong project, thay bằng:
```python
# Before
import logging
logger = logging.getLogger(__name__)
logger.info("Extracted %d items", count)

# After
from loguru import logger
logger.info("Extracted {count} items", count=count)
```

**Config** (`main.py` hoặc `core/config.py`):
```python
from loguru import logger
import sys

def setup_logging(log_level: str = "INFO", log_dir: str = "logs"):
    logger.remove()  # remove default stderr handler
    logger.add(sys.stderr, level=log_level, colorize=True,
               format="<green>{time:HH:mm:ss}</green> | <level>{level}</level> | {message}")
    logger.add(
        f"{log_dir}/crawl_{{time:YYYY-MM-DD}}.log",
        rotation="100 MB",
        retention="7 days",
        compression="zip",
        level="DEBUG",
        encoding="utf-8",
    )
```

---

## 0.2 Relative Timestamp Parsing — dateparser

**Problem**: FB/TikTok/IG dùng "5 phút trước", "2 hours ago", "3 tháng trước" — hiện tại không parse được, lưu chuỗi thô vào DB.

**File**: `device_farm/pyproject.toml`
```toml
dateparser = "^1.2"
```

**Dùng trong parsers** (`tasks/fb_extract.py`, `tasks/ig_extract.py`, etc.):
```python
import dateparser
from datetime import datetime, timezone

def parse_post_timestamp(raw: str) -> datetime | None:
    """
    Parse: "5 phút trước", "2 hours ago", "March 15", "3/15/2026"
    Trả về UTC datetime hoặc None nếu không parse được.
    """
    if not raw:
        return None
    dt = dateparser.parse(
        raw,
        languages=["vi", "en"],
        settings={
            "RETURN_AS_TIMEZONE_AWARE": True,
            "PREFER_DAY_OF_MONTH": "first",
            "TO_TIMEZONE": "UTC",
        }
    )
    return dt
```

**DB**: `ContentItem.content_date` column đã có — giờ sẽ được populate đúng thay vì NULL.

---

## 0.3 Fast JSON — orjson

**File**: `device_farm/pyproject.toml`
```toml
orjson = "^3.9"
```

**Thay thế trong task_queue.py** (Phase 1 sẽ dùng Redis):
```python
# Before
import json
payload = json.dumps(task_dict)
task = json.loads(payload_str)

# After
import orjson
payload = orjson.dumps(task_dict)           # returns bytes
task = orjson.loads(payload_bytes_or_str)   # accepts bytes or str
```

**Các nơi khác** dùng JSON nhiều:
- `services/content_store.py` — serialize content items
- `runtime/core/task_queue.py` — queue payloads
- `api/` routes — response serialization (FastAPI đã dùng, thêm `orjson` response class)

FastAPI + orjson:
```python
from fastapi.responses import ORJSONResponse

app = FastAPI(default_response_class=ORJSONResponse)
```

---

## 0.4 Fast Content Hashing — xxhash

**Problem**: SHA256 cho content dedup an toàn nhưng chậm không cần thiết (dedup không cần cryptographic security).

**File**: `device_farm/pyproject.toml`
```toml
xxhash = "^3.4"
```

**Thay trong `services/content_store.py`**:
```python
# Before
import hashlib
content_hash = hashlib.sha256(body.encode()).hexdigest()

# After
import xxhash
content_hash = xxhash.xxh64(body.encode()).hexdigest()  # 10x nhanh hơn
```

> Giữ SHA256 cho security-sensitive fields (passwords, tokens). xxhash chỉ dùng cho content dedup.

---

## 0.5 OCR Upgrade — PaddleOCR thay Tesseract

**File**: `device_farm/pyproject.toml`
```toml
paddlepaddle = "^2.6"
paddleocr = "^2.8"
# Remove: pytesseract
```

**File**: `runtime/extraction/ocr_engine.py` (rewrite)

```python
from loguru import logger
from paddleocr import PaddleOCR

class OCREngine:
    _instance = None  # singleton

    @classmethod
    def _get(cls):
        if cls._instance is None:
            cls._instance = PaddleOCR(
                use_angle_cls=True,
                lang="en",       # hoặc "ch" nếu cần Chinese
                show_log=False,
            )
        return cls._instance

    @classmethod
    def extract_text(cls, image_path: str, min_confidence: float = 0.7) -> list[str]:
        result = cls._get().ocr(image_path, cls=True)
        if not result or not result[0]:
            return []
        return [
            text for (text, conf) in (line[1] for line in result[0])
            if conf >= min_confidence
        ]
```

**Extraction cascade** (cập nhật `tasks/scenario/steps/extraction.py`):
```
1. XML hierarchy (lxml XPath)  → free, ~50ms
2. PaddleOCR                   → free, ~200-500ms, ~96% accuracy
3. LLM Vision (Phase 4)        → costs money, ~3-10s (last resort)
```

**Remove khỏi pyproject.toml**: `pytesseract`, `tesseract` system dep.

---

## 0.6 Unicode Text Cleanup — ftfy

**File**: `device_farm/pyproject.toml`
```toml
ftfy = "^6.2"
```

**Dùng khi save content** (`services/content_store.py`):
```python
import ftfy

def clean_text(text: str) -> str:
    """Fix mojibake, weird Unicode từ social media"""
    if not text:
        return text
    return ftfy.fix_text(text).strip()

# Trước khi save ContentItem:
item.body = clean_text(item.body)
item.author = clean_text(item.author)
```

Social media hay có: fancy Unicode fonts (`𝗕𝗼𝗹𝗱`), emoji sequences bị broken, mojibake từ encoding sai.

---

## 0.7 CSS Selector Support — cssselect

**File**: `device_farm/pyproject.toml`
```toml
cssselect = "^1.2"
```

Cho phép dùng CSS selector thay XPath thuần trong parsers (ngắn hơn, dễ debug hơn):
```python
# Before (XPath)
nodes = xml_root.xpath('//*[contains(@resource-id,"like_count")]')

# After (CSS via cssselect)
from lxml.cssselect import CSSSelector
sel = CSSSelector('[resource-id*="like_count"]')
nodes = sel(xml_root)
```

---

## 0.8 Dev Tool — weditor (không production)

```bash
pip install weditor  # chỉ local dev
python -m weditor    # mở browser UI inspector
```

- Kết nối device, inspect hierarchy real-time
- Test XPath/selector trước khi hardcode trong parser
- **Không thêm vào pyproject.toml production** — chỉ dev dependency

---

## Summary — pyproject.toml additions

```toml
[project.dependencies]
# Logging
loguru = "^0.7"

# Timestamp parsing
dateparser = "^1.2"

# Performance
orjson = "^3.9"
xxhash = "^3.4"

# OCR upgrade
paddlepaddle = "^2.6"
paddleocr = "^2.8"

# Text cleanup
ftfy = "^6.2"

# CSS selectors for lxml
cssselect = "^1.2"

[project.optional-dependencies]
dev = [
    "weditor",   # UI inspector
    "rich",      # Pretty terminal output
]
```

## Files to Modify

| File | Change |
|------|--------|
| `device_farm/pyproject.toml` | Add 7 new deps |
| `main.py` | Setup loguru + ORJSONResponse |
| `runtime/extraction/ocr_engine.py` | Rewrite với PaddleOCR, xóa pytesseract |
| `services/content_store.py` | xxhash + ftfy + orjson |
| `tasks/fb_extract.py` | dateparser cho timestamps |
| `tasks/ig_extract.py` | dateparser (Phase 3) |
| `tasks/tiktok_extract.py` | dateparser (Phase 3) |
| `runtime/core/task_queue.py` | orjson (Phase 1) |
