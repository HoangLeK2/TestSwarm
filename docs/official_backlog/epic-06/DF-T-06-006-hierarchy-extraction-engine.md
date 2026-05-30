# DF-T-06-006 — Hierarchy extraction engine + strategy interface

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-006 |
| **Title** | Hierarchy extraction engine + strategy interface |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:automation-builder`, `coverage:L2` |
| **Truy vết — FR refs** | FR-06-01 |
| **Truy vết — UC refs** | UC-06-01, UC-06-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Hierarchy là engine mặc định và rẻ nhất — đọc cây UIAutomator của Android, áp một extraction strategy do người dựng định nghĩa, trả về data có cấu trúc. Strategy là plug-in: một class/function nhận `hierarchy_root` và trả về `{schema_fields: ..., raw_data: ...}`. Đặc tả module yêu cầu strategy nào không khớp phải báo lỗi nghiệp vụ rõ ràng (không silent rỗng); tốc độ < 3 s.

Ticket này hiện thực hai phần: (1) engine — gọi `CaptureService.capture_hierarchy`, parse XML, expose API duyệt cây; (2) interface `ExtractionStrategy` — registry plug-in để DF-E-08 đăng ký strategy platform-specific (`fb_posts`, `fb_comments`, `tiktok_videos`, ...). Bản thân ticket này chỉ ship strategy generic `screen_data` (lấy mọi TextView visible), không ship strategy platform-specific (đó là DF-E-08).

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** gọi engine hierarchy với 1 strategy name và nhận về data có cấu trúc khớp content type
> **Để** thay vì viết parser thủ công cho từng UI, tôi chỉ chọn strategy có sẵn

Persona phụ: Platform Engineer (đăng ký strategy mới cho platform mở rộng).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `HierarchyService.extract(serial, strategy_name, config, persist=True, execution_ctx)` trả `HierarchyResult(data, raw_data, strategy_name, latency_ms)` — trace FR-06-01.
- Hệ thống PHẢI duy trì `StrategyRegistry` cho phép đăng ký runtime hoặc qua entry-point Python.
- Hệ thống PHẢI ship strategy generic `screen_data` (collect mọi TextView, EditText với text non-empty + bbox + resource_id).
- Hệ thống PHẢI raise `StrategyNotFoundError` khi strategy_name không tồn tại trong registry.
- Hệ thống PHẢI raise `StrategyMismatchError` khi strategy chạy thành công về kỹ thuật nhưng không tìm thấy element kỳ vọng (ví dụ chiến lược `fb_posts` chạy trên màn hình IG không có element nào match).
- Hệ thống PHẢI provide các util duyệt cây: `find_by_resource_id`, `find_by_text`, `find_by_class`, `xpath`, `iter_children`.
- Hệ thống PHẢI đạt p50 latency < 3 s cho hierarchy thông thường (< 500 node).
- Hệ thống NÊN cache parsed tree trong 30 s cho cùng (serial, capture_ts) để không parse lại.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Strategy generic screen_data**

```
Given device D đang ở Settings app
When HierarchyService.extract(D.serial, strategy_name="screen_data", config={})
Then result.data là danh sách entry có text, bbox, resource_id
And mỗi entry text non-empty
And latency < 3 s
```

**AC-2: Strategy không tồn tại**

```
Given strategy registry chưa đăng ký "fb_posts" (chưa có DF-E-08)
When extract(... strategy_name="fb_posts")
Then raise StrategyNotFoundError(strategy="fb_posts")
And response include danh sách strategy đang có
```

**AC-3: Strategy match nhưng không có element**

```
Given device đang ở màn hình loading (chỉ có spinner)
When extract với strategy "screen_data"
Then nếu không có TextView nào visible → raise StrategyMismatchError(reason="no_text_found", hierarchy_node_count=N)
And caller có thể quyết định retry hoặc đổi engine
```

**AC-4: Engine traversal API**

```
Given hierarchy có 500 node trong đó có 3 node với resource_id "com.facebook.katana:id/like_btn"
When dev gọi find_by_resource_id("com.facebook.katana:id/like_btn")
Then trả về list 3 node
And mỗi node có bbox và class chính xác
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm strategy platform-specific `fb_posts`, `fb_comments`, `tiktok_videos`, ... — đó là DF-E-08.
- KHÔNG bao gồm UI hỗ trợ Automation Builder dò resource_id (selector inspector) — đó là DF-E-11 (Frontend).
- KHÔNG bao gồm caching cross-process — chỉ in-memory 30 s.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `HierarchyParser` (lxml hoặc xml.etree) — parse UIAutomator XML.
- [ ] `Node` dataclass với bbox, class, text, resource_id, content_description, children, parent.
- [ ] Util `find_by_*` và `xpath`.
- [ ] `StrategyRegistry` với entry-point Python `device_farm.strategies`.
- [ ] Built-in strategy `screen_data`.
- [ ] `HierarchyService.extract` orchestrator.

**Contract / API** (`layer:contract`)

- [ ] Dataclass `HierarchyResult`, mã lỗi `StrategyNotFoundError`, `StrategyMismatchError`, `HierarchyParseError`.
- [ ] Đặc tả interface `ExtractionStrategy.extract(hierarchy_root, config) -> {data, raw_data}`.

**Documentation** (`layer:docs`)

- [ ] "How to write an extraction strategy" trong `docs/modules/content.md`.
- [ ] Bộ ví dụ strategy với mock hierarchy.

**Test** (`layer:test`)

- [ ] Unit test parser với 10 hierarchy fixture (FB Feed, IG Profile, TikTok Feed, ...).
- [ ] Unit test util find_*.
- [ ] Integration test với device emulator.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-006-01 | Positive | Device ở Settings, hierarchy có 50 node | Extract strategy screen_data | Trả ≥ 10 entry text; latency < 3s |
| TC-DF-T-06-006-02 | Positive | Hierarchy fixture FB Feed | Tìm resource_id `*_like_btn` | Trả 3 node với bbox đúng |
| TC-DF-T-06-006-03 | Negative | Strategy "fb_posts" chưa registered | Extract với strategy đó | `StrategyNotFoundError`; response list strategy hiện có |
| TC-DF-T-06-006-04 | Negative | Hierarchy XML malformed | Parse | `HierarchyParseError` với line info; không crash service |
| TC-DF-T-06-006-05 | Edge | Hierarchy có 5000 node (UI lồng nhau cực sâu) | Extract screen_data | Vẫn parse được; latency có thể > 3 s nhưng < 10 s timeout; warning log "large_hierarchy" |
| TC-DF-T-06-006-06 | Edge | Strategy chạy OK nhưng data rỗng | Extract trên màn hình loading | `StrategyMismatchError(no_text_found)` cho strategy screen_data |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-003 (CaptureService cho hierarchy XML).

**Chặn:** DF-T-06-007, DF-T-06-009, DF-E-08 (cần interface để đăng ký strategy).

**Phụ thuộc giữa Epic:** DF-E-08 sẽ đăng ký strategy platform-specific qua interface này. Cần freeze interface trước khi DF-E-08 implement.

**Rủi ro:**

- **UIAutomator XML format thay đổi giữa các Android version:** giảm thiểu: test trên Android 9, 10, 11, 12, 13; có version fallback parser.
- **Memory leak khi giữ node tree lớn:** giảm thiểu: weakref cho parent; benchmark RSS trên scenario 1h.

**Phụ thuộc bên ngoài:** Android UIAutomator XML format chuẩn.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit + integration test pass; 10 hierarchy fixture pass.
- [ ] Latency p50 < 3 s đo trên fixture.
- [ ] Interface `ExtractionStrategy` được DF-E-08 review và confirm khả dụng.
- [ ] `docs/modules/content.md` "How to write a strategy" hoàn thiện.
- [ ] Telemetry: `hierarchy_latency_ms`, `hierarchy_node_count`, `strategy_error_total{code, strategy}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve từ DF-E-08 owner.
- [ ] Changelog ghi nhận hierarchy engine + strategy interface.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.2, §6 FR-06-01](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Ma trận năng lực:** [03-capability-matrix.md §4.1 "UI hierarchy extraction"](../../official_docs/03-capability-matrix.md).
- **Nhóm người dùng:** Automation Builder (§3.2), Platform Engineer (§3.4).
- **Thuật ngữ:** [Hierarchy extraction](../../official_docs/00-glossary.md), [Extraction strategy](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-08.
