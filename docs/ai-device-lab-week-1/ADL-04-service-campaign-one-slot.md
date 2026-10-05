# ADL-04 — Domain production: service campaign, lane, slot và attempt

## 1. Giao nhận và điều kiện bắt đầu

| Thuộc tính | Yêu cầu |
|---|---|
| Scope / trạng thái | Production bắt buộc / NOT_STARTED |
| Implementer / reviewers | BE domain + FE operator / DB reviewer + runtime reviewer + QA; tên người giao D1 |
| Phụ thuộc | ADL-00 và ADL-02 đạt; ADL-01 chứng minh runtime |
| Bàn giao | Migration, repository/service/API, operator read view, contract tests và SQL reconciliation |
| Estimate | UNVALIDATED; tách giờ migration, API, UI, concurrency tests và review trước nhận việc |

**Outcome:** service campaign quản lý hợp đồng dịch vụ độc lập với runtime campaign; 12 lane là identity bền vững, daily slot khác retry attempt. Case một lane/ngày là phép thử contract, không giới hạn sản phẩm vào một máy.

## 2. Source và khoảng trống

- `backend/db/models/campaign.py`: Campaign, Scenario và CampaignDevice; không có service-day/plan entitlement.
- `backend/db/models/execution.py`: execution có idempotency/correlation/version reference; không có unique service slot.
- `backend/db/models/execution_step.py`: unique execution+step_index, attempts_json cho retry **step**; không dùng nó thay attempt **run**.
- `backend/db/models/schedule.py`: ScheduleRun là lịch sử trigger, không là đơn vị quota dịch vụ.
- Đây là source inspection; schema production mới là thiết kế đề xuất, cần DB review trước migration.

## 3. Contract dữ liệu và invariants

| Entity | Trường bắt buộc / ràng buộc |
|---|---|
| ServiceCampaign | org_id, runtime_campaign_id, owner_id, package, timezone, plan_version, status, lock_version, started_at/end_at; một app/campaign; payment không tự set started_at |
| Lane | org_id, service_campaign_id, ordinal 1..12, tester_label; unique campaign+ordinal; device assignment lưu lịch sử riêng |
| RunSlot | org_id, campaign_id, lane_id, service_day 1..14, planned_at, status; unique campaign+lane+day; service_day do server tính |
| RunAttempt | org_id, slot_id, attempt_no, execution_id, immutable scenario_version/build reference, idempotency_key, reason, timestamps, outcome; unique slot+attempt_no và idempotency_key |

FK/application checks phải ngăn lane/slot/attempt liên kết khác org hoặc khác campaign. Build reference thống nhất interface với ADL-10; không tạo FK tới bảng chưa có migration và không dùng nullable build để đóng task. Seed/import hỗ trợ chưa thay đổi kết quả runtime. Cấm cascade xóa history đã thanh toán/chạy; dùng archived/tombstone khi cần.

Campaign lifecycle: draft → ready → active → needs_attention → active hoặc finished; cancel/expiry do ADL-19b. Transition server-side, audit, optimistic lock. Slot execution state và app assertion verdict là **hai trường riêng**; reserve/queued/blocked không là app pass.

## 4. Bước triển khai

1. Chốt schema, version/build interface và state transitions với 02/10/16; ghi ADR quyết định và error codes.
2. Viết migrations/indexes/constraints cùng upgrade test trên PostgreSQL; kiểm FK và không mất dữ liệu runtime có sẵn.
3. Repository tenant-scoped và allocation attempt trong transaction; API create/read/archive service campaign, list lanes/slots/attempts có pagination, authorization server-side.
4. Nối operator view sử dụng generated client; chưa bật Start trước readiness 06. Slot generation 168 thuộc 07, delivery/event belongs 16.
5. Chạy race tests, readback API/SQL; kiểm API schema/client sync sau sửa migration path.

## 5. Acceptance

- [ ] AC1: campaign/lane/slot/attempt persisted và tenant relationship invariant được DB/API test.
- [ ] AC2: retry run thêm attempt, không thêm slot; retry step giữ cùng run attempt.
- [ ] AC3: concurrent allocation cùng intent chỉ có một accepted attempt; correlation truy lại execution.
- [ ] AC4: đổi build/scenario/device không mutate snapshots của attempt cũ.
- [ ] AC5: service state, slot state, app verdict và Play status không dùng chung enum/counter.

## 6. Test matrix

| ID | Setup và thao tác | Kết quả / evidence |
|---|---|---|
| 04-T1 | Org A create campaign, lane, slot; đọc API và SQL | IDs/FK/version khớp; không có runtime start tự động |
| 04-T2 | Hai DB sessions/processes allocate cùng idempotency key tại barrier | Một attempt; loser nhận existing result/conflict chuẩn; SQL unique invariant |
| 04-T3 | Run retry rồi step retry | Hai run attempts, một slot; step retry không tăng run-attempt count |
| 04-T4 | Edit scenario/build sau attempt #1 | Old snapshots/refs không đổi; attempt #2 dùng version mới được duyệt |
| 04-T5 | Payload lane org B vào campaign org A | Rejected; không tạo orphan/partial rows |
| 04-T6 | Upgrade migration trên DB runtime fixture, đọc lại rồi recovery | Existing executions còn nguyên; FK/index hợp lệ |

## 7. Review, evidence và đóng task

DB reviewer ký transaction/constraints; runtime reviewer ký run-vs-step semantics; QA độc lập chạy T2/T5/T6. Lưu schema diff, commands/exit codes, sanitized SQL counts, API responses, UI recording, commit/version và findings. Finding → REWORK → rerun impacted matrix → review lại. DONE khi AC1–5 và tests PASS; chưa đóng 05/07/16 chỉ vì schema tồn tại. Rollback chỉ khi chưa có service writes; đã có writes phải dùng forward recovery giữ history.
