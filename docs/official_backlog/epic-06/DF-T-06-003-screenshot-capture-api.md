# DF-T-06-003 — Screenshot & hierarchy capture API cho extraction pipeline

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-003 |
| **Title** | Screenshot & hierarchy capture API cho extraction pipeline |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L1` |
| **Truy vết — FR refs** | FR-06-12, FR-06-09 (input data nguồn) |
| **Truy vết — UC refs** | UC-06-04, UC-06-10, UC-06-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Ba engine extraction (hierarchy, OCR, AI vision) đều cần một nguồn ảnh và một nguồn hierarchy chuẩn hóa. DF-E-02 đã cung cấp endpoint `/api/screenshot/{serial}` và transport hierarchy capture, nhưng cách output của DF-E-02 chưa được "gói" lại thành interface hợp với extraction pipeline. Ticket này dựng adapter `CaptureService` trên đỉnh DF-E-02: nhận serial + tham số (full screen / region), gọi xuống transport, đẩy artifact lên MinIO/S3 với metadata (execution_id, step_index, kind), trả về handle để các engine consume mà không phải biết transport detail.

Đây là ticket "biên giới" giữa DF-E-06 và DF-E-02 — cô lập extraction pipeline khỏi thay đổi transport. Khi DF-E-02 chuyển từ ADB screenshot sang minicap hay đổi sang stream-based, các engine không phải biết.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** một API capture screenshot + hierarchy thống nhất, trả về handle ổn định, bất kể device đang dùng transport ADB hay scrcpy
> **Để** scenario và engine extraction không vỡ khi transport layer thay đổi

Persona phụ: Social Data Operator (mở artifact qua handle đó để xem evidence).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose `CaptureService.capture_screenshot(device_serial, region=None, persist=True, execution_ctx)` trả về `CaptureHandle(image_bytes, object_key, size, sha256, captured_at)` — trace FR-06-12.
- Hệ thống PHẢI expose `CaptureService.capture_hierarchy(device_serial, persist=True, execution_ctx)` trả về `HierarchyHandle(xml_bytes, object_key, root, captured_at)`.
- Khi `persist=True` và `execution_ctx` đầy đủ (execution_id, step_index, kind), hệ thống PHẢI đẩy artifact lên object storage và ghi `execution_artifacts` row.
- Khi `persist=False` (ví dụ engine dry-run), hệ thống KHÔNG đẩy lên object storage; chỉ trả về handle in-memory.
- Hệ thống PHẢI chuẩn hóa định dạng screenshot về PNG; nếu device trả format khác phải convert.
- Hệ thống PHẢI chuẩn hóa định dạng hierarchy về XML UTF-8 đúng schema UIAutomator.
- Hệ thống PHẢI gắn TTL ngắn (30 s) trên in-memory cache để retry trong cùng 1 step không chụp lại 2 lần.
- Hệ thống NÊN log latency capture từng phase (device→transport→service) để debug bottleneck.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Capture có persist**

```
Given device D online; execution E ở step 5
When scenario gọi capture_screenshot(D.serial, region=None, persist=True, ctx=(E.id, 5, "screenshot_pre"))
Then handle trả về có image PNG, sha256 hợp lệ, size > 0
And bảng execution_artifacts có 1 row mới (execution_id=E.id, step_index=5, kind=screenshot_pre)
And object_key có format "{org}/{execution}/step-{n}/{kind}-{ts}.png"
```

**AC-2: Capture không persist (dry-run)**

```
Given device D online
When dev gọi capture_screenshot(D.serial, persist=False, ctx=None)
Then handle trả về có image PNG in-memory
And không có row execution_artifacts được tạo
And không có object lên MinIO
```

**AC-3: Capture hierarchy + parse hợp lệ**

```
Given device D đang ở app Facebook (Feed)
When capture_hierarchy(D.serial, persist=True, ctx=(E.id, 5, "hierarchy_snapshot"))
Then handle.xml_bytes là XML UTF-8 hợp lệ
And handle.root là object đã parse, có thuộc tính bounds
And execution_artifacts có row kind=hierarchy_snapshot
```

**AC-4: Device offline**

```
Given device D offline
When capture_screenshot(D.serial, ...) được gọi
Then service raise CaptureError(code="DEVICE_OFFLINE")
And không có row execution_artifacts được ghi
And caller nhận lỗi sau ≤ 5 s timeout
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm transport implementation (ADB / minicap / scrcpy) — đó là DF-E-02.
- KHÔNG bao gồm signed URL trả về artifact — đó là DF-T-06-012.
- KHÔNG bao gồm retention/lifecycle — đó là DF-T-06-011.
- KHÔNG bao gồm region-based crop cho selector cụ thể — sẽ làm sau khi có demand, hiện chỉ hỗ trợ bounding box (x, y, w, h).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Class `CaptureService` với 2 method chính.
- [ ] Adapter `TransportAdapter` (gọi xuống DF-E-02 endpoint hoặc gRPC).
- [ ] PNG converter (nếu device trả JPEG).
- [ ] Hierarchy parser tối thiểu (chỉ root + children + bounds; full parse nằm ở DF-T-06-006).
- [ ] In-memory cache 30 s key = (serial, step_index).
- [ ] MinIO/S3 uploader.

**Contract / API** (`layer:contract`)

- [ ] Khai báo dataclass `CaptureHandle`, `HierarchyHandle`, mã lỗi `DEVICE_OFFLINE`, `CAPTURE_TIMEOUT`, `CAPTURE_FORMAT_INVALID`.
- [ ] Không expose endpoint REST mới — service nội bộ; endpoint sẽ ở DF-T-06-009.

**Documentation** (`layer:docs`)

- [ ] Mô tả CaptureService trong `docs/modules/content.md`.
- [ ] Sequence diagram: scenario step → CaptureService → engine → MinIO.

**Test** (`layer:test`)

- [ ] Unit test với mock transport.
- [ ] Integration test với device emulator: capture pre/post step 100 lần, đo latency.
- [ ] Test offline device, timeout.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-003-01 | Positive | Device emulator online, ở app Facebook | `capture_screenshot` với persist=True | Trả PNG ≤ 2 MB, sha256 hợp lệ, row artifact tạo, object có trên MinIO |
| TC-DF-T-06-003-02 | Positive | Device emulator online | `capture_hierarchy` persist=True | Trả XML hợp lệ, parser root có ≥ 1 child, row artifact tạo |
| TC-DF-T-06-003-03 | Negative | Device offline | `capture_screenshot` | `CaptureError(DEVICE_OFFLINE)`; timeout ≤ 5 s; không upload |
| TC-DF-T-06-003-04 | Negative | Transport trả format không hỗ trợ (raw bitmap unknown) | `capture_screenshot` | `CaptureError(CAPTURE_FORMAT_INVALID)`; log đầy đủ format byte signature |
| TC-DF-T-06-003-05 | Edge | Trong cùng 1 step, capture được gọi 3 lần liên tiếp trong 1 s | 3 capture call | Chỉ 1 lần thực sự xuống transport; 2 lần sau trả từ cache; chỉ 1 row artifact ghi |
| TC-DF-T-06-003-06 | Edge | Persist=True nhưng ctx thiếu execution_id | Gọi capture | `CaptureError(MISSING_CONTEXT)`; không upload; gợi ý dev khai báo persist=False khi không có ctx |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-002 (cần bảng execution_artifacts).

**Chặn:** DF-T-06-004, DF-T-06-005, DF-T-06-006, DF-T-06-009.

**Phụ thuộc giữa Epic:** DF-E-02 phải cung cấp ổn định endpoint screenshot và transport hierarchy. Nếu DF-E-02 đổi contract, ticket này phải cập nhật adapter.

**Rủi ro:**

- **Capture chậm trên device pin yếu / nhiệt cao:** giảm thiểu: timeout cứng 5 s, log latency để Fleet Operator phát hiện device cần thay.
- **Object storage rate limit khi 1000 device cùng đẩy:** giảm thiểu: batch upload mỗi 500 ms, retry exponential backoff.

**Phụ thuộc bên ngoài:** DF-E-02 transport, MinIO/S3 endpoint.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit + integration test pass với mock và emulator.
- [ ] Latency p50 capture screenshot < 1.5 s đo trên 50 device emulator.
- [ ] `docs/modules/content.md` cập nhật sequence diagram.
- [ ] Telemetry: histogram `capture_latency_ms{kind, persist}`, counter `capture_error_total{code}`.
- [ ] Code review ≥ 1 approve owner module + owner Epic-02.
- [ ] Changelog ghi nhận CaptureService.
- [ ] Đã chạy thử trên fleet thật 24h, không leak memory.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.1, §6 FR-06-12](../../official_docs/modules/06-content-extraction-artifacts.md).
- **DF-E-02 spec:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) (transport).
- **Nhóm người dùng:** Automation Builder (§3.2).
- **Thuật ngữ:** [Hierarchy](../../official_docs/00-glossary.md), [Artifact](../../official_docs/00-glossary.md), [MinIO / S3](../../official_docs/00-glossary.md).
