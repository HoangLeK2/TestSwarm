# Research Report: Mobile Crawling Libraries for deviceFarmer (2025)

> Generated: 2026-04-16

---

## Executive Summary

deviceFarmer đã chọn đúng stack core: `uiautomator2` + `lxml` + `Tesseract`. Research này xác nhận những lựa chọn đó và chỉ ra các thư viện bổ sung có thể tăng đáng kể độ chính xác và tốc độ.

**3 upgrade quan trọng nhất:**
1. **PaddleOCR** thay Tesseract → +20-40% accuracy, nhanh hơn, hỗ trợ tiếng Việt/Trung/Nhật tốt hơn
2. **Airtest image recognition** → fallback khi XPath fail (click theo ảnh thay vì selector)
3. **Poco** → truy cập UI object hierarchy trực tiếp, bổ sung cho XML dump

---

## Thư viện hiện tại vs. Đề xuất

| Layer | Hiện tại | Đề xuất bổ sung |
|---|---|---|
| Device control | `uiautomator2` ✅ | Giữ nguyên |
| XML parsing | `lxml` + XPath ✅ | Giữ nguyên + `cssselect` |
| OCR | `Tesseract` | → **PaddleOCR** |
| Image matching | `airtest` (SSIM) ✅ | Thêm template matching |
| UI inspect | - | → **weditor / Poco** |
| Gesture human-like | Chưa có | → custom jitter wrapper |
| Multi-device | In-memory | → **asyncio + Redis** (Phase 1) |

---

## 1. Device Control & Automation

### uiautomator2 ⭐ ~8k (đang dùng)
- HTTP RPC server trên device; Python API clean
- WiFi connect qua atx-agent (không cần USB liên tục)
- **Giữ nguyên** — tốt nhất cho Android-only scraping

### Appium (không cần thêm)
- Nặng hơn uiautomator2; overhead WebDriver
- Chỉ cần nếu sau này làm iOS
- **Skip** cho mobile-only project

### facebook-wda
- iOS equivalent của uiautomator2
- **Dùng sau** nếu cần iOS support

---

## 2. UI Hierarchy & Inspection

### weditor / UIAutoDev
```bash
pip install weditor
python -m weditor
```
- Browser-based UI inspector cho uiautomator2
- Inspect real-time hierarchy, test XPath trước khi hardcode
- **Dùng ngay cho dev workflow** — không cần trong production

### Poco ⭐ ~3k
```bash
pip install pocoui
```
- Truy cập UI object trực tiếp (không cần XML dump)
- Hỗ trợ Android native apps + Unity games
- API ngắn hơn XPath:
  ```python
  poco = AndroidUiautomationPoco(use_airtest_input=True)
  poco("android.widget.TextView").attr("text")  # vs xpath //*[@class='...']
  ```
- **Dùng như fallback** khi XML hierarchy quá phức tạp

---

## 3. Image Recognition & Template Matching

### Airtest ⭐ ~9k (đã có trong deps)
```python
from airtest.core.api import Template, exists, touch

# Click theo ảnh — không cần selector
touch(Template("like_button.png", threshold=0.8))
assert_exists(Template("post_loaded.png"))
```
- Template matching (SSIM + ORB feature matching)
- **Quan trọng**: dùng khi platform update UI → XPath break nhưng ảnh vẫn nhận ra được
- **Đã có trong project** (`core/cv.py` dùng airtest) — cần expose ra step handler

### OpenCV (qua airtest)
- Airtest đã wrap OpenCV
- Thêm dùng trực tiếp cho: diff detection, crop regions, resize screenshots

---

## 4. OCR — Nên Upgrade

### PaddleOCR ⭐ ~45k — **RECOMMENDED**
```bash
pip install paddlepaddle paddleocr
```

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(use_angle_cls=True, lang="en")  # khởi tạo 1 lần, reuse

def extract_text_from_screenshot(img_path: str) -> list[str]:
    result = ocr.ocr(img_path, cls=True)
    lines = []
    for line in result[0]:
        text, confidence = line[1]
        if confidence > 0.7:
            lines.append(text)
    return lines
```

**Tại sao tốt hơn Tesseract:**
| | Tesseract | PaddleOCR (PP-OCRv5) |
|---|---|---|
| Accuracy (English) | ~85% | ~96% |
| Vietnamese | Poor | Good |
| Chinese/Japanese | Poor | Excellent |
| CPU speed | Slow | 3-5x faster |
| Mobile model size | N/A | 9.6 MB |
| Setup | Easy | Moderate |

- PP-OCRv5 (May 2025): +13% accuracy vs v4
- **Quan trọng với project**: social media có nhiều tiếng Việt, emoji, mixed text

### EasyOCR (alternative)
```bash
pip install easyocr
```
- Dễ setup hơn PaddleOCR
- Chậm hơn trên CPU
- Dùng nếu PaddleOCR quá nặng cho device

### Tesseract (hiện tại)
- Giữ làm fallback tier-3 (sau hierarchy → PaddleOCR → Tesseract)

---

## 5. Human-Like Behavior

### Không có thư viện riêng cho mobile — tự implement

```python
import random, asyncio

class HumanGesture:
    """Wrap uiautomator2 calls với jitter"""
    
    def __init__(self, device):
        self.d = device
    
    async def tap(self, x: int, y: int):
        # Jitter vị trí ±5px
        jx = x + random.randint(-5, 5)
        jy = y + random.randint(-5, 5)
        self.d.click(jx, jy)
        await asyncio.sleep(random.uniform(0.3, 0.8))
    
    async def scroll(self, distance: int = 500):
        # Vary scroll distance và speed
        actual = distance + random.randint(-100, 100)
        duration = random.uniform(0.4, 0.9)
        self.d.swipe(540, 1200, 540, 1200 - actual, duration=duration)
        await asyncio.sleep(random.uniform(1.0, 2.5))
    
    async def type_text(self, text: str):
        # Type từng ký tự với delay ngẫu nhiên
        for char in text:
            self.d.send_keys(char)
            await asyncio.sleep(random.uniform(0.08, 0.25))
```

---

## 6. Data Processing & Storage

### tenacity (đã có) ✅
- Retry với exponential backoff

### orjson — **RECOMMEND thêm**
```bash
pip install orjson
```
- JSON serialize/deserialize nhanh hơn stdlib `json` ~10x
- Quan trọng khi xử lý nhiều content items

### msgpack
```bash
pip install msgpack
```
- Binary serialization cho Redis queue payloads — nhỏ hơn JSON ~30%
- Thay `json.dumps` trong `task_queue.py`

### xxhash — thay SHA256 cho dedup
```bash
pip install xxhash
```
```python
import xxhash
content_hash = xxhash.xxh64(body.encode()).hexdigest()  # 10x nhanh hơn SHA256
```
- SHA256: dùng khi cần cryptographic security
- xxHash: dùng cho content dedup (không cần secure, chỉ cần fast + low collision)

---

## 7. Parallel & Async

### asyncio (stdlib) ✅ — đang dùng
### aiohttp (đã có) ✅

### anyio — optional upgrade
```bash
pip install anyio
```
- Wrapper trên asyncio + trio
- Dùng nếu cần structured concurrency (cancel groups)

---

## 8. Monitoring & Debugging

### loguru — **RECOMMEND**
```bash
pip install loguru
```
```python
from loguru import logger
logger.add("logs/crawl_{time}.log", rotation="100 MB", retention="7 days", 
           level="DEBUG", compression="zip")
logger.info("Extracted {count} items from {platform}", count=10, platform="facebook")
```
- Structured logging; rotation tự động; colored output
- Dễ replace stdlib `logging`

### rich — optional
```bash
pip install rich
```
- Pretty terminal output khi debug locally
- Progress bars cho long-running campaigns

---

## 9. Content Processing

### dateparser — **RECOMMEND**
```bash
pip install dateparser
```
```python
import dateparser
# Parse "2 giờ trước", "yesterday", "5 minutes ago", "3 tháng trước"
dt = dateparser.parse("2 giờ trước", languages=["vi", "en"])
```
- **Quan trọng**: FB/TikTok dùng relative timestamps → cần convert sang datetime
- Hỗ trợ tiếng Việt

### ftfy — fix Unicode
```bash
pip install ftfy
```
```python
import ftfy
clean = ftfy.fix_text("Hᴏᴡ ᴀʀᴇ ʏᴏᴜ?")  # fix mojibake, weird chars
```
- Social media content có nhiều Unicode garbage, fancy fonts
- Clean trước khi lưu vào DB

---

## 10. Thư viện KHÔNG cần

| Thư viện | Lý do skip |
|---|---|
| Selenium | Web-only; không dùng cho mobile |
| BeautifulSoup | XML parse với lxml đã đủ |
| Scrapy | Web crawler; không phù hợp mobile |
| Appium | Quá nặng; uiautomator2 đủ dùng |
| Frida/Xposed | Over-engineering; chỉ cần nếu app dùng SSL pinning |

---

## Upgrade Priority

### P0 — Làm ngay, ít rủi ro
```toml
loguru = "^0.7"        # Better logging
dateparser = "^1.2"    # Parse relative timestamps
orjson = "^3.9"        # Faster JSON
```

### P1 — Upgrade OCR
```toml
paddlepaddle = "^2.6"
paddleocr = "^2.8"
# Remove: pytesseract (hoặc giữ làm fallback)
```

### P2 — Optimization
```toml
xxhash = "^3.4"        # Fast content hashing
cssselect = "^1.2"     # CSS selector → XPath cho lxml
```

### Dev tools (không vào production)
```bash
pip install weditor    # UI inspector
pip install rich       # Debug terminal output
```

---

## Sources
- [uiautomator2 GitHub](https://github.com/openatx/uiautomator2)
- [Airtest GitHub](https://github.com/AirtestProject/Airtest)
- [Poco GitHub](https://github.com/AirtestProject/Poco)
- [PaddleOCR PyPI](https://pypi.org/project/paddleocr/)
- [PaddleOCR vs Tesseract](https://www.koncile.ai/en/ressources/paddleocr-analyse-avantages-alternatives-open-source)
- [OCR comparison 2025](https://modal.com/blog/8-top-open-source-ocr-models-compared)
- [LambdaTest Appium alternatives](https://www.lambdatest.com/blog/appium-alternatives/)
