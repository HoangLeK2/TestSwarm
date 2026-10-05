# Plan: Giảm độ trễ chạy kịch bản trên phone

Trạng thái: **đã code Phase 1–4**. Chưa chạy được `pytest` (shell bị rate-limit
trong phiên này) và chưa chạy thật trên máy — xem `todo-selector-latency.md`.

Plan cũ (log account + ảnh R2) vẫn nằm nguyên ở `tasks/plan.md` + `tasks/todo.md`,
không bị đụng tới.

## Kết luận điều tra (giữ nguyên từ bản gốc)

Đường truyền **không** chậm: `dismiss_popup` p50 = 96ms cho trọn chuỗi Temporal →
activity → relay → phone → DB. Thời gian mất vào step thất bại phải chờ hết
timeout, và vào recovery playbook.

Chi phí thật (chỉ leaf step):

| Nhóm lỗi | n | tổng (s) | trung bình |
|---|---:|---:|---:|
| `recovery_failed` | 6 | 618 | 103.072 ms |
| `other` | 18 | 559 | 31.065 ms |
| `cancelled by user` | 51 | 458 | 8.990 ms |
| `selector_miss` | 6 | 88 | 14.651 ms |
| `no_control_channel` | 1 | 18 | 18.032 ms |

## Đã làm

### Phase 1 — Selector không còn chết vì khoảng trắng

**Task 1 — fallback so khớp chuẩn hoá whitespace.**

- `services/scenario_selector.normalize_match_text()` — NFC → gộp `\s+` → strip.
  Không casefold, không bỏ dấu; phép chuẩn hóa quá rộng có thể tạo false positive.
- `runtime/element_resolver.phase_text_normalized()` — dump hierarchy 1 lần, quét
  `text` + `content-desc`, so khớp sau chuẩn hoá, trả bounds khi đúng 1 node.
  - **>1 node ⇒ trả None** (từ chối tap).
  - Node có `text` **trùng khít** `value` bị bỏ qua: `phase_selector` đã thấy nó
    và đã từ chối (khớp ngoài recorded hint). Phase mới không được rửa quyết
    định đó.
  - `_innermost()` gộp wrapper/child cùng chuỗi — Android treo cùng một chuỗi lên
    ViewGroup clickable và TextView con; đó là **một** element, không phải hai.
- Lắp vào `tasks/scenario/utils._execute_tap` sau `phase_selector`, trước
  `phase_healing`, chỉ khi selector không volatile.

**Khác plan gốc:** không gate theo "chuỗi có chênh lệch whitespace". Gate đó chỉ
đúng một chiều (selector có NBSP), sẽ bỏ sót chiều ngược lại (máy có NBSP,
selector không) — chính là chiều chưa xác minh được. Gate hiện tại là
`by ∈ {text, description, content-desc, accessibility id}`. Dump chỉ chạy khi đã
miss, tức đã tốn 8s; thêm ~200ms không đáng kể.

**Task 2 — sửa dữ liệu + chặn đầu vào.**

- `db/models/utils.normalize_variable_spaces()` — thay mọi space Unicode lạ
  (NBSP, narrow NBSP, các space typographic, BOM) bằng space thường, đệ quy.
- `@validates("variables")` trên `Campaign` và `Scenario`. Cả hai đường ghi
  (`create_campaign`, `update_campaign_entity`) đều set attribute qua ORM nên
  validator bắt được hết.
- Migration `db/migrations/121_normalize_variable_spaces.py` — đọc, chuẩn hoá,
  ghi lại, in before/after. `downgrade` no-op.

**Khác plan gốc:** **không** gộp khoảng trắng và **không** strip ở đường ghi.
`variables` cũng chứa caption nhiều dòng và mật khẩu; gộp/strip ở đó là làm hỏng
dữ liệu, không phải chuẩn hoá. Chỉ đụng ký tự vô hình.

### Phase 2 — Recovery không được đốt 103 giây

**Task 3 — trần thời gian cho playbook.**

103s đến từ `_try_recovery_playbooks`: nó chạy **tuần tự mọi rule khớp**, mỗi rule
là một scenario lồng đầy đủ, không có giới hạn thời gian nào. Bộ đếm
`max_attempts` / `max_attempts_per_step` giới hạn **số lần**, không giới hạn
**thời lượng** — mỗi tap trong playbook vẫn có thể chờ hết 8s của nó.

- `RecoveryPolicy.max_step_recovery_ms`, mặc định 30 000, `0` = tắt.
- `recovery_runner` tính deadline một lần cho mỗi step, kiểm tra **trước khi**
  khởi động từng playbook và `break` khi hết giờ.

**Chưa làm:** "bỏ cuộc sớm khi rule đầu không đổi trạng thái màn hình". Đó là
heuristic — rule sau làm việc khác rule trước, màn hình không đổi không có nghĩa
rule sau vô dụng. Trần thời gian đã đủ đạt tiêu chí "không còn leaf step ~103s".
**Giới hạn còn lại:** trần chặn *giữa* các playbook; một playbook đơn lẻ vẫn có
thể vượt trần. Muốn chặn bên trong thì phải truyền deadline xuống scenario lồng.

### Phase 3 — Chẩn đoán không còn mù

**Task 4 — `failure_class` / `reason_code` tới được DB.**

Truy vết: chỉ đường batch tổng quát (`run_scenario_task` → `step_runner`) mới gọi
`annotate_step_failure`. Ba đường khác dựng entry bằng tay chỉ với
`{index, type, ok, message}`:

1. `temporal/activities.py` — nhánh touch-primitive nhanh (`u2_batch`).
2. `temporal/workflows.py` `_flush_batch` — nhánh `except` khi activity ném lỗi.
3. `temporal/workflows.py` — mọi entry control-flow (`loop`, `if_*`, `extract`…).

Sửa ở **một** chỗ mà mọi đường đều đi qua: `build_execution_step_payload()` gọi
`annotate_step_failure` trước khi lọc `_ERROR_DETAIL_KEYS`.

- `reason_code='ok'`: `tasks/scenario/steps/extraction.py:1174` mặc định
  `diagnostic.get("reason_code", "ok")`. Step hỏng sau đó vẫn mang giá trị cũ.
  `classify_campaign_failure` nay bỏ qua `reason_code == "ok"`, và
  `annotate_step_failure` xoá nó khi không có lớp nào thay thế.
- Thêm `"no control channel"` vào `_DEVICE_LOST_MARKERS`.

### Phase 4 — Bớt phân mảnh batching

**Task 5 — thu hẹp `_CONTROL_FLOW_TYPES`: kết luận là KHÔNG.**

- `extract` trả `ExtractResult.break_requested` — đó là cách `stop_if_no_new`
  kết thúc vòng crawl. `DeviceActionBatchResult` **không có** trường nào chở nó.
  Gộp vào batch ⇒ vòng crawl chạy tới hết cap thay vì dừng sớm. Nó cũng cần
  `_LONG_TIMEOUT`, batch timeout tính theo số step không cấp được.
- `save_extraction` ghi DB trên worker và đẩy `__save_extraction_offsets__` ngược
  vào runtime_context để retry không lưu trùng.
- `run_scenario` (450 lần) cắt batch mỗi lần — đổi nó là đổi mô hình thực thi,
  đúng như plan gốc đã ghi nhận.
- Ngoài ra sửa set này đổi chuỗi command workflow phát ra ⇒ cần patch id cho run
  đang chạy dở.

Kết luận đã ghi thành comment tại `temporal/workflows.py:207` để không phải suy
lại lần sau.

## Rủi ro còn lại

| Rủi ro | Giảm thiểu |
|---|---|
| Phase mới tap nhầm node | >1 khớp thì từ chối; bỏ qua node trùng khít; không casefold, không bỏ dấu |
| Migration đụng dữ liệu campaign | Chỉ ký tự vô hình; in before/after mỗi dòng |
| Trần 30s cắt mất một recovery đang có ích | Chỉnh qua `recovery_policy.max_step_recovery_ms`; `0` để tắt |
| `annotate_step_failure` trong hot path ghi step | Chỉ chạy khi `ok=False`; thuần so chuỗi |

## Câu hỏi mở (chưa trả lời)

- Text thật trên màn hình nhóm có NBSP không, ở `text` hay `content-desc`?
  `adb exec-out uiautomator dump` khi máy đang mở màn hình đó. **Không chặn** —
  Task 1 đúng cho cả hai chiều.
- Nhóm `other` (18 leaf step, 31s trung bình) — xem lại sau khi Task 4 chạy thật.
- 51 step `cancelled by user` (458s): bạn hủy vì chậm, hay vì lý do khác?
