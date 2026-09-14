---
title: "Một nguồn sự thật cho trace: phone → account → campaign → step → nguyên nhân"
description: "Gộp hai hệ ghi step chồng nhau về một nguồn (execution_events), mở khoá truy vấn theo account, và sửa retention đang xoá nhầm bản đầy đủ."
status: pending
priority: P0
effort: 3-4 days
branch: fix/bug-ui-node
tags: [backend, frontend, observability, execution-events, account-trace]
created: 2026-09-13
---

# Một Nguồn Sự Thật Cho Trace

## Summary

Hệ thống đang có **hai nơi ghi step song song**, và cái được đọc là cái thiếu:

| | `execution_events` | `execution_steps` |
|---|---|---|
| Row (local) | **8220** | 734 |
| Phủ | **mọi step, depth 1-4** | chỉ depth 0 (583/734 là `run_scenario`) |
| Context | account_id, device_serial, step_path, campaign_id, duration_ms, reason_code — **trong JSON** | không có account |
| Truy theo account | ✗ không index được | ✗ |
| Retention | **xoá sau 30 ngày** | vô thời hạn |
| Ai đọc | `/executions/{id}/trace` | `/executions/{id}/steps` ← **UI đang dùng** |

Hệ quả cụ thể: mở dấu vết của một account chỉ thấy 2 dòng `run_scenario`, trong
khi sub-scenario đã chạy hàng chục tap/input/scroll — chúng nằm đủ trong
`execution_events` nhưng không ai đọc.

Nguyên nhân kỹ thuật (đã xác minh trên source và DB):

1. `_execute_child_steps` gọi lại `run()` ở `depth+1` trong **cùng** workflow
   (`workflows.py:1664`). Event gom vào `self._pending_events` cho **mọi depth**
   rồi flush ở depth 0 — nên event đầy đủ.
2. `persist_step_checkpoint` chỉ chạy ở `depth == 0`, và `execution_steps` khoá
   `(execution_id, step_index)` — một không gian số nguyên phẳng không chứa nổi
   step lồng. Nên bảng này **về bản chất** không thể là nguồn trace.
3. `account_id` chỉ nằm trong `payload.trace`, không phải cột → không có index
   nào trả lời được "account A đã làm gì".
4. `outbox_poller.py:12` `RETENTION_DAYS = 30` xoá bản **đủ**; bản **thiếu** giữ
   mãi. Ban thường lộ sau nhiều tuần.

Mục tiêu: lấy một `account_id` bất kỳ và dựng lại được timeline đầy đủ —
ai, trên máy nào, trong campaign/run nào, tới step nào, sâu bao nhiêu, kết quả
ra sao, hỏng vì lý do gì — và nối được với thời điểm account bị ban.

## Non-goals

- **Không** đổi khoá `execution_steps`. Nó giữ vai trò projection "trạng thái
  hiện tại của step top-level + ảnh chụp", không phải nguồn trace.
- **Không** thêm bảng log mới. Bốn bảng hiện có đã đủ vai trò, vấn đề là chưa
  phân vai rõ.
- **Không** đụng `scenario-trace.log`. Nó là kênh đọc bằng mắt, không phải nguồn.
- **Không** nâng `_MAX_RETAINED_SUB_RESULTS`. Nó tồn tại để chặn tràn payload
  2MB của Temporal; event đi đường riêng nên không cần.

---

## Giai đoạn

### P1 — Mở khoá truy vấn theo account  ·  nút thắt duy nhất

Đây là thay đổi cấu trúc thật sự cần. Mọi thứ khác đã có và chạy đúng.

**Migration `131_execution_events_account_columns.py`**

```
ALTER TABLE execution_events
  ADD COLUMN account_id     VARCHAR(36),
  ADD COLUMN device_serial  VARCHAR(128),
  ADD COLUMN step_path      VARCHAR(512);
```

Cả ba nullable, không default → ALTER rẻ trên PG 11+, không rewrite bảng.

Backfill theo lô (id-range, không quét toàn bảng một phát):

```sql
UPDATE execution_events SET
  account_id    = payload::jsonb -> 'trace' ->> 'account_id',
  device_serial = payload::jsonb -> 'trace' ->> 'device_serial',
  step_path     = payload::jsonb -> 'trace' ->> 'step_path'
WHERE id BETWEEN :lo AND :hi AND account_id IS NULL;
```

Index:

```
idx_execution_events_org_account_time  (org_id, account_id, occurred_at)
idx_execution_events_exec_path         (execution_id, step_path)
```

> ⚠ **Ràng buộc đã xác minh:** migration chạy trong `engine.begin()`
> (`db/database.py:277`), tức trong transaction → **không dùng được
> `CREATE INDEX CONCURRENTLY`**. Với 8220 row thì `CREATE INDEX` thường là
> tức thì. Nếu production lớn hơn nhiều, tách việc tạo index ra một bước
> vận hành riêng chạy ngoài migration runner. **Cần đo số row production
> trước khi deploy** — xem mục Rủi ro.

**Ghi cột ở đường write** — `services/execution/event_publisher.py`
`enqueue_execution_event` (dòng 53). Giá trị đã có sẵn trong
`payload["trace"]`, chỉ cần nhấc ra và truyền xuống `insert_execution_event`.
Không đổi chữ ký hàm với caller.

**Model** — `db/models/execution_event.py`: thêm 3 cột + 2 index.

**Verify**
- Test migration trên sqlite + assert cột/index tồn tại (theo mẫu
  `test_ledger_migration_runs_on_sqlite`).
- Test: emit một event có trace → đọc lại row → 3 cột khớp payload.
- Test backfill: chèn row kiểu cũ (chỉ JSON) → chạy backfill → cột được điền.
- Test tenancy: query theo `account_id` không rò qua org khác.

---

### P2 — Sửa retention ngược

`services/execution/outbox_poller.py`

- `RETENTION_DAYS` thành env-configurable (giữ mặc định 30 cho event ồn).
- **Không xoá** các loại mang giá trị điều tra:
  `step.failed`, `incident.*`, `execution.failed`, `execution.dlq.*`,
  `account_action.*` — giữ theo mốc dài hơn (đề xuất 365 ngày, env riêng).
- `step.started`/`step.completed` thành công vẫn xoá theo mốc ngắn: đó là phần
  chiếm chỗ (7123/8218 row = 87%).

**Verify** — test: chèn event cũ đủ loại, chạy purge, assert loại cần giữ còn
nguyên và loại ồn đã đi.

---

### P3 — UI đọc đúng nguồn

`/executions/{id}/trace` **đã tồn tại** và đã đọc `execution_events`
(`services/execution_trace.py:487`), có phân trang, đã merge context. Không cần
API mới cho mức execution.

- `AccountStepTraceDialog` (vừa làm ở thread này): panel step chuyển từ
  `/executions/{id}/steps` sang `/executions/{id}/trace`.
- Mapper `accounts/lib/run-step-log.ts` nhận thêm nhánh event → `StepLogEntry`,
  dùng `payload.depth` và `payload.trace.step_path` để dựng cây lồng nhau.
  `StepRow` đã nhận `depth` và `branchLabel` nên hiển thị được ngay.
- Ảnh chụp vẫn lấy từ `useExecutionArtifacts` như hiện tại.

**Verify** — chạy app thật, mở dialog trên execution có sub-scenario, assert
thấy step ở depth ≥ 1 (dữ liệu local đã có: `social_open_author_from_post_match`
depth 3, `scroll_down` depth 3).

---

### P4 — Timeline theo account, nối với sự kiện ban

Sau P1 thì đây chỉ là một query.

- `GET /accounts/{id}/trace?since=&until=&limit=` → đọc `execution_events`
  theo `(org_id, account_id, occurred_at)`.
- Mặc định neo quanh sự kiện ban nếu có: `account_events` với
  `event_type='account.state.changed'` và `details->>'to'='banned'`
  (đã có dữ liệu thật: `active → banned`, `"bị band"`, 2026-08-24 07:10:23).
- UI: thêm tab "Trước khi bị ban" trong dialog, mặc định cửa sổ T-24h.

**Verify** — test: dựng account có ban + step trước/sau mốc, assert cửa sổ trả
đúng khoảng và đúng thứ tự.

---

### P5 — Gộp ba bản định nghĩa context

Cùng một bộ field đang viết ba lần:

| Nơi | Vai trò hiện tại |
|---|---|
| `services/execution/trace_context.py::_TRACE_KEYS` | snapshot phía ghi |
| `temporal/activities.py::_build_activity_trace_context` | phía activity |
| `services/execution_trace.py::_build_context` | read-model |

Gộp về một `ExecutionIdentity` dùng chung. Thuần refactor, không đổi hành vi —
làm **sau** P1-P4 để không trộn rủi ro.

**Verify** — test đối chiếu: ba đường cũ và đường mới cho cùng output trên
cùng input.

---

### P6 — Ghi vai trò từng bảng vào tài liệu

`docs/adr-execution-trace-sources.md` — để không đẻ ra hệ thứ ba:

```
execution_events  → NGUỒN SỰ THẬT của trace. Append-only. Mọi step mọi depth.
execution_steps   → Projection: trạng thái hiện tại của step top-level + ảnh.
account_actions   → Ledger nghiệp vụ: "hôm nay gửi bao nhiêu lời mời".
account_events    → Vòng đời account, gồm sự kiện ban.
activity_logs     → Audit thao tác người dùng.
execution_dlq     → Lỗi cuối cùng của run.
scenario-trace.log→ Kênh đọc bằng mắt. Không phải nguồn.
```

Kèm quy tắc: một sự kiện **không** được emit ở hai nơi.

---

## Thứ tự và phụ thuộc

```
P1 (cột + index)  ──┬──►  P4 (timeline account)
                    └──►  P2 (retention)   [độc lập, làm song song được]
P3 (UI đọc trace) ── độc lập với P1, làm song song được
P5, P6 ── sau cùng
```

Đường tới hạn là **P1**. P3 có thể làm ngay vì `/executions/{id}/trace` đã sẵn.

## Rủi ro

| Rủi ro | Giảm thiểu |
|---|---|
| `CREATE INDEX` khoá ghi trên bảng outbox lớn ở production | Đo `count(*)` production trước. Dưới ~1M row thì chấp nhận được trong cửa sổ deploy; lớn hơn thì tách index ra bước vận hành riêng ngoài migration runner |
| Backfill quét bảng nóng | Chạy theo lô id-range, commit từng lô, dừng được giữa chừng |
| Giữ event lâu hơn làm phình bảng | Nhóm cần giữ lâu chỉ là **292/8218 row = 3,6%** (đã đếm). Bảng hiện 22 MB cho 8218 row ≈ 2,7 KB/row, nên giữ nhóm này 365 ngày gần như không tốn gì; nhóm success vẫn xoá theo mốc cũ |
| Đổi nguồn UI làm mất ảnh chụp | Ảnh đi đường `useExecutionArtifacts` riêng theo `step_index`, không phụ thuộc nguồn step |
| Event depth sâu làm UI quá tải | `/executions/{id}/trace` đã phân trang sẵn (`has_more_events`) |

## Definition of Done

Lấy `account_id` bất kỳ, dựng được timeline trả lời đủ:

```
AI        account + label
Ở ĐÂU     device serial + platform
KHI NÀO   timestamp
LÀM GÌ    semantic action / step_type, mọi depth
LÊN AI    target (post/person/profile)
BỐI CẢNH  campaign → execution → step_path (định vị chính xác trong cây)
KẾT QUẢ   ok / failed / cancelled
VÌ SAO    reason_code + message
LẦN MẤY   attempt
```

Và: một người vận hành đọc timeline hiểu được account đã làm gì **mà không cần
đọc XML, selector, source code hay stack trace**.

## Đã xong trước plan này (trong branch, chưa commit)

- `account_id`/`platform`/`campaign_id` gắn vào mọi dòng structlog + vào
  `execution_steps.effective_config_json.trace` (kể cả đường chạy trực tiếp).
- Bảng semantic `<entity>.<operation>` + câu người đọc cho từng step.
- Ledger mở từ 3 → 14 action domain, flush theo lô cuối scenario.
- `ACCOUNT_ACTION_LEDGER_MODE=enabled` trong `deploy.env` (production đang rơi
  về `disabled`).
- Sửa đường log đôi `logs/logs/` và thêm volume `farm_logs` cho deploy.
- `GET /api/executions?account_id=` + index migration 130.
- Dialog "Dấu vết step" trên trang Accounts (đã chạy thật, có ảnh chụp).
