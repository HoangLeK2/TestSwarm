# DF-T-06-004 — OCR extraction pipeline (tiếng Việt + tiếng Anh)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-004 |
| **Title** | OCR extraction pipeline (tiếng Việt + tiếng Anh) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:infra`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-02 |
| **Truy vết — UC refs** | UC-06-02, UC-06-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi UI nền tảng social render text trong ảnh (banner, thumbnail, story-card, Canvas) thay vì TextView, hierarchy không expose ra. OCR là engine bắt buộc cho những trường hợp này. Đặc tả module yêu cầu OCR engine hỗ trợ tiếng Việt + tiếng Anh, trả text kèm tọa độ, latency < 5 s/ảnh. Engine không hiểu ngữ nghĩa — output là raw chuỗi + bounding box; mapping vào schema content nằm ở strategy / normalizer.

Persona hưởng lợi: Automation Builder (mở engine OCR khi gặp text-in-image), Social Data Operator (gián tiếp — không bị mất dữ liệu vì hierarchy rỗng).

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** gọi OCR engine trên một screenshot và nhận về danh sách (text, bounding_box, confidence)
> **Để** strategy của tôi có thể map text trong ảnh vào schema content type tương ứng

Persona phụ: Social Data Operator.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `OCRService.extract(image, lang=["vi","en"], region=None)` trả `[{text, bbox:(x,y,w,h), confidence}]` — trace FR-06-02.
- Hệ thống PHẢI hỗ trợ tiếng Việt và tiếng Anh trong cùng 1 lần gọi.
- Hệ thống PHẢI cho phép region crop (bounding box) để OCR chỉ vùng quan tâm — giảm chi phí và nhiễu.
- Hệ thống PHẢI trả kết quả trong < 5 s/ảnh ở chế độ chuẩn (full screen 1080×2400) — đo p50.
- Hệ thống PHẢI filter result có confidence < threshold (default 0.5) và đưa vào `low_confidence_results` riêng để strategy quyết định.
- Hệ thống PHẢI graceful degrade khi engine fail: trả `OCRError(code, partial_results)` thay vì crash; tích hợp retry policy ở DF-T-06-014.
- Hệ thống NÊN cung cấp metric latency, success rate, confidence distribution để observability.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: OCR ảnh tiếng Việt**

```
Given screenshot chứa text tiếng Việt "Xin chào bạn" trong vùng (100, 200, 400, 50)
When OCRService.extract(image, lang=["vi"]) được gọi
Then result chứa ít nhất 1 entry có text "Xin chào bạn" (cho phép tolerance 1 ký tự)
And confidence ≥ 0.7
And bbox gần đúng với (100, 200, 400, 50) (cho phép ± 10 pixel)
```

**AC-2: OCR ảnh tiếng Anh + tiếng Việt cùng lúc**

```
Given screenshot có cả "Hello world" và "Chào thế giới"
When OCRService.extract(image, lang=["vi","en"])
Then result chứa cả 2 chuỗi
And mỗi entry có lang detected tương ứng
```

**AC-3: Region crop**

```
Given screenshot 1080×2400 với text rải khắp
When OCRService.extract(image, region=(0,0,1080,400))
Then result chỉ chứa text nằm trong vùng top 400 pixel
And không có entry nào có y > 400
And latency thấp hơn so với full-screen extract
```

**AC-4: Latency SLO**

```
Given 100 ảnh chuẩn 1080×2400 (mỗi ảnh < 2 MB PNG)
When OCRService.extract chạy tuần tự
Then p50 < 5 s
And p95 < 10 s
And không ảnh nào > 30 s (timeout cứng)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm OCR ngôn ngữ thứ ba (Trung, Nhật, Hàn) — sẽ thêm theo demand.
- KHÔNG bao gồm semantic mapping text → schema field — đó là strategy/normalizer (DF-T-06-007).
- KHÔNG bao gồm OCR trên video frame — chỉ trên ảnh static.
- KHÔNG bao gồm AI-enhanced OCR (gọi GPT để verify) — đó là DF-T-06-005.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `OCRService` interface và implementation (default: Tesseract OCR + vie/eng language pack; có thể swap PaddleOCR/EasyOCR sau).
- [ ] Region crop preprocessing (PIL).
- [ ] Confidence threshold filter.
- [ ] Timeout 30 s.
- [ ] Background worker pool (4 worker default) để tránh block scenario executor.

**Infra / DevOps** (`layer:infra`)

- [ ] Bake Tesseract 5.x + ngôn ngữ vie + eng vào Docker image worker.
- [ ] Cấu hình resource (CPU 2 core, RAM 1 GB) cho OCR worker.
- [ ] Horizontal scale OCR worker theo queue depth.

**Documentation** (`layer:docs`)

- [ ] Hướng dẫn Automation Builder khi nào chọn OCR vs Hierarchy vs AI vision.
- [ ] Cách dùng region để giảm chi phí.

**Test** (`layer:test`)

- [ ] Bộ test fixture 50 ảnh tiếng Việt thật (từ FB, IG).
- [ ] Test latency.
- [ ] Test với ảnh tối / chữ nhỏ (edge).

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-004-01 | Positive | Ảnh post FB tiếng Việt 1080×2400 | OCR full-screen | Trích được caption chính, confidence ≥ 0.7 |
| TC-DF-T-06-004-02 | Positive | Ảnh banner TikTok có text overlay tiếng Anh | OCR với region top 400px | Trả text trong vùng, không nhiễu vùng dưới |
| TC-DF-T-06-004-03 | Negative | Ảnh hoàn toàn trống (white canvas) | OCR | Result rỗng `[]`; không lỗi; latency < 1 s |
| TC-DF-T-06-004-04 | Negative | Service Tesseract bị kill (giả lập) | OCR call | `OCRError(ENGINE_UNAVAILABLE)`; retry policy kick in |
| TC-DF-T-06-004-05 | Edge | Ảnh chữ rất nhỏ (12px) trên nền nhiễu | OCR | Trả `low_confidence_results`; result chính rỗng; strategy nhận info "ảnh chất lượng thấp" |
| TC-DF-T-06-004-06 | Edge | Ảnh 4K (3840×2160) > 8 MB | OCR | Resize xuống 1080p trước khi process; vẫn dưới timeout; warning log "image_too_large_resized" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-003 (cần screenshot input).

**Chặn:** DF-T-06-007, DF-T-06-009, DF-T-06-014.

**Phụ thuộc giữa Epic:** Không.

**Rủi ro:**

- **Tesseract chất lượng kém với tiếng Việt có dấu phức tạp:** giảm thiểu: dùng vie_best traineddata; benchmark trên 50 ảnh fixture; nếu < 80% accuracy thì cân nhắc PaddleOCR.
- **OCR ngốn CPU khi 1000 device cùng request:** giảm thiểu: queue + autoscale worker; alert khi queue depth > 100.

**Phụ thuộc bên ngoài:** Tesseract 5.x với language pack vie, eng.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Test fixture 50 ảnh fixture đạt accuracy ≥ 80%.
- [ ] Latency p50 < 5 s, p95 < 10 s đo trên fixture.
- [ ] Tài liệu "khi nào chọn OCR" đã viết.
- [ ] Telemetry: `ocr_latency_ms`, `ocr_confidence_distribution`, `ocr_error_total{code}`.
- [ ] Code review ≥ 1 approve owner module.
- [ ] Changelog ghi nhận OCR engine ship cho 4 platform.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.2, §6 FR-06-02](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Ma trận năng lực:** [03-capability-matrix.md §4.3 "OCR extraction"](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** Automation Builder (§3.2).
- **Thuật ngữ:** [OCR](../../official_docs/00-glossary.md).
