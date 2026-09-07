# Plan: Sửa luồng log account + ảnh bằng chứng khi step lỗi

## Context

Hai triệu chứng người dùng báo, hoá ra cùng một gốc: **bằng chứng của một hành động
không đi cùng bản ghi của hành động đó.**

1. **Ảnh lỗi không hiển thị.** Campaign chạy với `capture_mode: "error_only"`
   (`services/campaign/execution_runtime.py:316`), nên ảnh duy nhất tồn tại của cả run là
   ảnh chụp lúc step fail. Đường đi của ảnh đó có 4 chỗ đứt độc lập — chỉ cần một chỗ
   đứt là UI trắng trơn, và tất cả đều thất bại im lặng (chỉ một dòng WARNING).

2. **Log account không nói được account đã làm gì.** Bảng `account_actions` có sẵn cột
   `artifact_refs` (`db/models/account_action.py:43`, migration `102`), được
   `execution_trace.py:156` đọc ra, `service.py:217` nhận tham số — nhưng **chưa từng có
   một call site nào ghi vào**. Log ghi "account A gửi kết bạn cho B" mà không có ảnh nào
   chứng minh.

3. **Performance.** Ghi ledger tạo một engine + connection Postgres mới cho mỗi action
   (`db/database.py:180-215`); path batch `social_connect_visible_people` gọi
   `prepare_action` + `finalize_action` **trong vòng lặp trên từng target**
   (`social_actions.py:1253-1293`) → batch 20 người = 40 lần dựng connection. Phía đọc,
   feed `/api/analytics/activity` `UNION ALL` 3 bảng rồi `COUNT(*)` toàn bộ union mỗi lần
   load trang, và nhánh `account_actions` không dùng được index nào vì tenancy đi qua
   `JOIN accounts` thay vì `account_actions.org_id`.

4. **Một bug gửi trùng.** `social_actions.py:1298` — sau khi ĐÃ bấm Add Friend cho N người
   thật, nếu ghi ledger lỗi thì step bị `_fail` → campaign retry → **gửi lại cho đúng
   những người đó**. Ledger là audit, không phải điều kiện của hành động.

Kết quả mong muốn: một step fail để lại ảnh xem được vĩnh viễn, gắn thẳng vào bản ghi
account action; ledger không còn tự bắn vào chân mình; và chi phí ghi/đọc log giảm mà
không đụng vào hai hàm CRITICAL-risk.

## Quyết định của người dùng (đã chốt)

| Câu hỏi | Chốt |
|---|---|
| Ảnh bằng chứng | **Chỉ khi lỗi.** Giữ `error_only`, không chụp cho action thành công. |
| URL ảnh hết hạn | **Lưu `object_key`, ký lúc đọc.** Không phụ thuộc `R2_PUBLIC_BASE_URL`. |
| `stable_action_key` | **Sửa luôn** — key theo `target_id`, bỏ tên hiển thị. |

## Impact analysis (bắt buộc theo CLAUDE.md)

| Symbol | Risk | impactedCount |
|---|---|---|
| `build_step_capture_payload` | LOW | 7 |
| `ExtractionCaptureService.capture_screenshot` | LOW | 0 |
| `_extract_step_artifacts` | LOW | 2 |
| `_finalize_action` | LOW | 2 |
| `run_activity_coro_blocking` | **CRITICAL** | 33 (6 flows) |
| `run_activity_coro` | **CRITICAL** | 503 (24 flows) |

⚠️ **Plan này KHÔNG sửa `run_activity_coro` / `run_activity_coro_blocking`.** Sửa cơ chế
loop dùng chung ở đó là fix gốc cho engine churn, nhưng blast radius là 503 symbol / 24
execution flow. Thay vào đó Phase 3 **giảm số lần gọi** (batch), giữ nguyên transport.
Xem "Deferred" ở cuối.

## Architecture decisions

- **URL không lưu cứng.** Artifact ref mang `object_key`; API resolve lúc đọc theo thứ tự
  `proxy /artifacts/{id}/content` → ký mới từ `object_key` → url cũ (legacy). Dùng lại
  `services/content/artifact_service.presigned_artifact_url()` đã có, không viết hàm ký mới.
- **Index tuyệt đối, không index cục bộ.** Path Temporal chạy mỗi step thành một
  mini-scenario 1-step nên `step_idx` bên trong luôn = 0. Thay vì đánh số lại cả scenario,
  mini-scenario mang `_step_index_offset` và `build_step_capture_payload` cộng offset một
  lần — sửa đồng thời cache key, object key, tên file local, và `step_index` trong artifact ref.
- **Ảnh lỗi không bao giờ lấy từ cache.** Cache 30s ở `content/extraction/capture_service.py:104`
  đúng cho pre/post, sai về bản chất cho fail: ảnh lỗi phải là màn hình tại thời điểm lỗi.
- **`_fail` chỉ đúng TRƯỚC hành động.** `social_actions.py:2296` claim-before-act → giữ
  `_fail`. Ba site post-hoc (`1298`, `1413`, `2223`) → ghi lỗi vào result, không fail step.
- **Batch nằm trong session, không nằm ngoài.** Các call `prepare/finalize` ở path batch đều
  là bookkeeping sau khi tap đã xảy ra → gom cả list vào một `activity_session()`.
- **Tenancy qua `org_id`, không qua join.** `AccountAction` là `TenantScopedModel`, có sẵn
  `org_id`. Bỏ `JOIN accounts` khỏi keys-query khi `user.org_id` có giá trị → index dùng được.
  (`AccountEvent` **không** có `org_id` → giữ join cho nhánh đó.)

---

## Phase 1 — Một step lỗi để lại ảnh xem được

### Task 1: Artifact URL không hết hạn

**Description:** `epic06_capture_adapter.py:73` ký presigned URL TTL 1 giờ rồi lưu cứng
vào `artifacts_json[].screenshot_url`. Sau 1 giờ R2 trả 403 → ảnh vỡ. Mang `object_key`
qua payload → artifact ref → DB, và resolve URL lúc đọc.

**Acceptance criteria:**
- [ ] `build_step_capture_payload` trả thêm `screenshot_object_key` (và `hierarchy_object_key` khi có)
- [ ] `_artifact_ref` ghi các key đó vào artifact ref
- [ ] `_extract_step_artifacts` resolve: proxy by artifact_id → ký mới từ object_key → url cũ
- [ ] Row cũ (chỉ có url) vẫn resolve được, không 500

**Verification:**
- [ ] `cd device_farm && uv run pytest tests/test_epic04_step_capture.py tests/test_epic04_execution_steps.py`
- [ ] Test mới: artifact ref có object_key → API trả URL ký mới, không trả chuỗi đã lưu
- [ ] Manual: mở lại một execution cũ >1h, ảnh vẫn load

**Dependencies:** None
**Files:** `services/execution/epic06_capture_adapter.py`, `services/execution/capture_service.py`, `api/routes/executions.py`, `tests/test_epic04_step_capture.py`
**Reuse:** `services/content/artifact_service.presigned_artifact_url()`
**Scope:** M (4 files)

---

### Task 2: Ảnh lỗi đúng step, đúng thời điểm

**Description:** Path Temporal (`temporal/activities.py:250`) đóng gói mỗi step thành
mini-scenario 1-step → `step_idx` luôn 0. Hệ quả: cache key `(serial, 0, "screenshot_fail")`
dùng chung cho mọi step (TTL 30s) nên step thứ hai fail trong vòng 30s **nhận lại ảnh của
step trước**; object key đều là `step-0/`; UI gắn nhãn "B1" cho mọi ảnh lỗi.

**Acceptance criteria:**
- [ ] `_build_activity_mini_scenario` nhận và set `_step_index_offset` = index thật
- [ ] `build_step_capture_payload` cộng offset cho cache key, object key, prefix file, và trả `step_index` tuyệt đối trong payload
- [ ] `_record_capture_result` dùng `payload["step_index"]` khi có
- [ ] `capture_screenshot` bỏ qua cache khi `kind` kết thúc bằng `_fail`

**Verification:**
- [ ] `uv run pytest tests/test_epic04_step_capture.py tests/test_scenario_capture.py`
- [ ] Test mới: hai step khác nhau cùng fail trong 30s → hai `object_key` khác nhau, hai `step_index` khác nhau
- [ ] Manual: chạy campaign có 2 step fail liên tiếp, kiểm tra UI hiện 2 ảnh với số step đúng

**Dependencies:** Task 1 (cùng đụng `build_step_capture_payload`)
**Files:** `temporal/activities.py`, `services/execution/epic06_capture_adapter.py`, `services/content/extraction/capture_service.py`, `services/execution/capture_service.py`
**Scope:** M (4 files)

---

### Task 3: Không mất ảnh khi retry, không thất bại im lặng

**Description:** `step_runner.py:298` và `:353` reset `step_result = {"index":…, "ok": True}`
khi retry → mọi artifact ref của lần thử vừa fail bị vứt. Step retry 3 lần rồi pass = không
còn dấu vết nào. Và `_handle_capture_failure` chỉ log WARNING khi `require_capture=False`
(mặc định) → operator không phân biệt được "không có lỗi" với "chụp hỏng".

**Acceptance criteria:**
- [ ] Retry giữ lại `artifacts`/`artifacts_json` đã tích luỹ thay vì reset trắng
- [ ] `_handle_capture_failure` luôn ghi `step_result["capture_error"] = {phase, message}`, không chỉ khi `require_capture`
- [ ] Hành vi `require_capture=True` không đổi (vẫn fail step)

**Verification:**
- [ ] `uv run pytest tests/test_epic04_step_capture.py tests/test_epic04_temporal_step_retry.py`
- [ ] Test mới: step fail lần 1 (có ảnh) → pass lần 2 → artifact của lần 1 còn trong kết quả
- [ ] Test mới: capture trả rỗng → `capture_error` có mặt, step vẫn `ok=True`

**Dependencies:** None
**Files:** `services/execution/step_runner.py`, `services/execution/capture_service.py`, `tests/test_epic04_step_capture.py`
**Scope:** S (3 files)

### ✅ Checkpoint 1
- [ ] `uv run pytest tests/` xanh
- [ ] Chạy thật một campaign có step fail → ảnh hiện trong Campaign Monitor, đúng số step
- [ ] Mở lại execution đó sau >1 giờ → ảnh vẫn hiện
- [ ] `detect_changes({scope: "compare", base_ref: "main"})` — không có flow ngoài dự kiến
- [ ] **Review với người dùng trước khi sang Phase 2**

---

## Phase 2 — Log account đúng và đủ

### Task 4: Ledger lỗi không được làm hỏng hành động đã xảy ra

**Description:** Bug gửi trùng. Ba site gọi ledger **sau khi** hành động đã thực hiện lại
`_fail` step khi ghi ledger lỗi → campaign retry → gửi lại. Site claim-before-act ở
`social_actions.py:2296` thì `_fail` là đúng và **giữ nguyên**.

**Acceptance criteria:**
- [ ] `social_actions.py:1298` (batch), `:1413` (single), `:2223` (already_applied): ghi
      `result["account_action_ledger_error"]`, giữ `ok=True`, không gọi `_fail`
- [ ] `social_actions.py:2320` (pre-action claim) giữ nguyên `_fail`
- [ ] Có counter/log để lỗi ledger vẫn nhìn thấy được, không biến mất

**Verification:**
- [ ] `uv run pytest tests/test_social_action_steps.py tests/test_account_action_ledger.py`
- [ ] Test mới: `sent_count=3` + `prepare_action` raise → step `ok=True`, có `account_action_ledger_error`
- [ ] Test regression: `prepare_action` raise ở path claim-before-act → step vẫn fail

**Dependencies:** None
**Files:** `tasks/scenario/steps/social_actions.py`, `tests/test_social_action_steps.py`
**Scope:** S (2 files)

---

### Task 5: Gắn ảnh lỗi vào bản ghi account action

**Description:** Đây là chỗ nối hai vấn đề. `artifact_refs` tồn tại trên
`account_actions`/`account_action_attempts` nhưng chưa từng được ghi. Ảnh fail được chụp ở
`step_runner.py:391`, **sau** khi handler (và ledger finalize) đã chạy — nên phải gắn ở
bước sau, không gắn trong `_finalize_action`.

**Acceptance criteria:**
- [ ] Hàm mới `attach_action_artifacts(*, org_id, action_id, artifact_refs)` trong
      `services/account_actions/service.py` — cập nhật `AccountAction.artifact_refs` và
      attempt gần nhất; no-op khi không có action_id
- [ ] `step_runner.py` gọi nó ngay sau `capture_fail_step`, đọc action_id từ
      `step_result["account_action_ledger"]`; không raise nếu thiếu
- [ ] `artifact_refs` chỉ chứa `{type, step_index, screenshot_artifact_id, screenshot_object_key}` — không nhét cả payload
- [ ] `_action_out` (`api/routes/account_actions.py`) expose thêm `device_serial`,
      `execution_id`, `step_id`, `platform`, `artifact_refs`

**Verification:**
- [ ] `uv run pytest tests/test_account_action_ledger.py`
- [ ] Test mới: step có ledger action + fail → `AccountAction.artifact_refs` không rỗng
- [ ] Manual: mở tab lịch sử của một account, thấy action lỗi kèm link ảnh mở được

**Dependencies:** Task 1, Task 2 (cần `screenshot_object_key` tồn tại)
**Files:** `services/account_actions/service.py`, `services/account_actions/__init__.py`, `services/execution/step_runner.py`, `api/routes/account_actions.py`, `api/schemas/account_action.py`
**Reuse:** `services/execution/step_store.extract_artifacts_json()`
**Scope:** M (5 files)

---

### Task 6: `stable_action_key` khoá theo danh tính, không theo tên hiển thị

**Description:** Key hiện hash cả `target` đầy đủ, trong đó có `name` — tên hiển thị của
một người đổi giữa hai lần đọc màn hình (truncate, emoji, đổi tên) → sinh **hai row ledger
cho cùng một hành động**. Đúng nguyên tắc "verify by identity, not by position" trong
`CLAUDE.md`.

**Acceptance criteria:**
- [ ] Key dùng `{action, target_type, target_id}` khi có `target_id`
- [ ] Không có `target_id` → giữ nguyên hành vi cũ (hash full target), không sập
- [ ] Shape khớp `stable_account_target_key` (`service.py:65`) đã có
- [ ] Test `test_stable_action_key_unchanged_by_the_device_column` được cập nhật có chủ đích, kèm lý do

**Verification:**
- [ ] `uv run pytest tests/test_account_action_ledger.py`
- [ ] Test mới: cùng `target_id`, khác `name` → cùng key
- [ ] Test mới: khác `target_id` → khác key
- [ ] Manual: deploy khi fleet rảnh — action đang in-flight dùng key cũ sẽ không match key mới

**Dependencies:** None
**Files:** `services/account_actions/service.py`, `tests/test_account_action_ledger.py`
**Scope:** S (2 files)

### ✅ Checkpoint 2
- [ ] `uv run pytest tests/` xanh, gồm cả 3 guard test bắt buộc:
      `test_fb_label_guard.py`, `test_fb_geometry_guard.py`, `test_template_label_guard.py`
- [ ] Chạy thật một campaign kết bạn → log account có đủ device/execution/step + ảnh khi lỗi
- [ ] Xác nhận không còn gửi trùng khi ledger lỗi
- [ ] **Review với người dùng trước khi sang Phase 3**

---

## Phase 3 — Performance

### Task 7: Gom ledger batch vào một session

**Description:** `social_actions.py:1253-1293` gọi `prepare_action` + `finalize_action`
trong vòng lặp trên từng target. Mỗi call đi qua `run_activity_coro_blocking` → dựng engine
+ connection Postgres mới rồi vứt. Batch 20 người = 40 lần dựng connection, ~240 round-trip.
Tất cả các call này đều là bookkeeping **sau khi** tap đã xảy ra → gom được vào một session.

**Acceptance criteria:**
- [ ] Hàm mới `record_actions(*, identity, action_type, platform, records)` trong
      `coordinator.py`: một `activity_session()`, lặp bên trong, trả list kết quả cùng shape
- [ ] Dùng lại `_resolve_tenant`, `create_action`, `transition_action`, `start_attempt`,
      `finish_attempt` — không viết logic ledger mới
- [ ] `_handle_social_connect_visible_people` gọi 1 lần thay cho vòng lặp 2N call
- [ ] Cả `observe` và `enabled` mode đều đi qua đường gom
- [ ] `run_activity_coro_blocking` **không** bị sửa

**Verification:**
- [ ] `uv run pytest tests/test_social_action_steps.py tests/test_account_action_ledger.py`
- [ ] Test mới: batch 5 target → đúng 5 row `account_actions`, và `activity_session` được mở đúng 1 lần
- [ ] Đo: log thời gian ghi ledger cho batch 20 trước/sau

**Dependencies:** Task 4 (cùng đụng vùng code đó — làm sau để tránh conflict)
**Files:** `services/account_actions/coordinator.py`, `services/account_actions/__init__.py`, `tasks/scenario/steps/social_actions.py`, `tests/test_account_action_ledger.py`
**Scope:** M (4 files)

---

### Task 8: Feed activity dùng được index

**Description:** `/api/analytics/activity` `UNION ALL` 3 bảng, sort `updated_at DESC`,
`OFFSET/LIMIT`. Nhánh `account_actions` scope tenancy bằng `JOIN accounts` nên
`account_actions.org_id` không bao giờ nằm trong WHERE — index
`idx_account_actions_device_time` (`device_serial, updated_at, id`) chỉ dùng được khi lọc
theo device, còn view mặc định thì scan toàn bảng. `AccountAction` là `TenantScopedModel`
và đã có sẵn `org_id`.

**Acceptance criteria:**
- [ ] `_account_action_base` thêm predicate `AccountAction.org_id == org_id` khi
      `user.org_id` có giá trị, và bỏ `JOIN accounts` ở keys-query trong trường hợp đó
- [ ] Giữ nguyên join cho nhánh không có org (`Account.user_id == data_owner_user_id`)
- [ ] Giữ nguyên join cho `AccountEvent` — bảng đó **không** có `org_id`
- [ ] Migration `119`: `CREATE INDEX idx_account_actions_org_time ON account_actions (org_id, updated_at, id)`
- [ ] Cập nhật comment ở `db/models/account_action.py:20-24` — lý do cũ ("org không bao giờ
      trong WHERE") không còn đúng sau task này
- [ ] Kết quả feed không đổi: cùng số row, cùng thứ tự

**Verification:**
- [ ] `uv run pytest tests/` (đặc biệt `test_account_action_ledger.py::test_device_filter_no_longer_discards_every_account_action`)
- [ ] Test mới: SQL sinh ra có predicate `org_id` và không có `JOIN accounts` ở nhánh org
- [ ] `EXPLAIN ANALYZE` trên feed trước/sau, xác nhận index scan thay vì seq scan
- [ ] Manual: feed trả đúng dữ liệu cho cả user có org và user không org

**Dependencies:** None (nhưng làm cuối vì cần migration)
**Files:** `api/routes/analytics.py`, `db/models/account_action.py`, `db/migrations/119_account_action_org_time_index.py`, `tests/test_account_action_ledger.py`
**Scope:** M (4 files)

### ✅ Checkpoint 3
- [ ] `uv run pytest tests/` xanh
- [ ] `detect_changes({scope: "compare", base_ref: "main"})` — review toàn bộ blast radius
- [ ] Migration `119` chạy sạch trên staging, `downgrade` cũng chạy được
- [ ] Đo lại: thời gian ghi ledger batch, và thời gian load feed
- [ ] Sẵn sàng review/merge

---

## Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Sửa `run_activity_coro*` (CRITICAL, 503 symbol) | Cao | **Không sửa trong plan này.** Phase 3 giảm số call thay vì đổi transport. |
| Đổi `stable_action_key` sinh row trùng cho action in-flight | Trung bình | Deploy khi fleet rảnh; cửa sổ in-flight ngắn (một step). Người dùng đã chấp nhận. |
| Migration `119` thêm index trên bảng lớn khoá ghi | Trung bình | Dùng `CREATE INDEX CONCURRENTLY` nếu bảng đã lớn; kiểm tra row count trước. |
| Task 1 sửa shape artifact ref, row cũ không có `object_key` | Thấp | Resolve có 3 nấc fallback; test riêng cho row legacy. |
| Task 3 giữ artifact qua retry làm phình `step_result` | Thấp | Chỉ giữ ref (~200 byte/ref), không giữ bytes ảnh. `slim_step_result` đã strip trước khi ghi `passed_steps`. |
| Task 8 đổi tenancy path của feed | Trung bình | Test cả hai nhánh (có org / không org) trước khi merge; kết quả feed phải giống hệt. |

## Deferred (không làm trong plan này)

- **Shared background event loop cho `run_activity_coro`.** Fix gốc cho engine churn ở
  ~15 call site, nhưng CRITICAL: 503 symbol / 24 execution flow. Làm PR riêng, có
  benchmark trước/sau, sau khi Task 7 đã đo được phần còn lại của chi phí.
- **Bỏ `COUNT(*)` chính xác trên union feed** (`analytics.py:337`). Đổi sang
  `has_more` (fetch limit+1) sẽ bỏ được full scan, nhưng là **API contract change** —
  `ActivityLogListOut.total` đang được frontend dùng. Cần quyết định sản phẩm riêng.
- **Time window mặc định cho feed.** Bounded scan là cách duy nhất làm `COUNT` rẻ thật,
  nhưng làm row cũ biến mất khỏi view mặc định → quyết định sản phẩm.
- **`_run_scenario_task_legacy`** (`tasks/scenario_task.py:1161`, ~1700 dòng code chết —
  `run_scenario_task` delegate thẳng sang `ScenarioExecutor` ở dòng 1144). Nó chứa một vòng
  lặp capture song song **không có** `capture_on_fail`, rất dễ gây nhầm khi đọc. Xoá ở PR
  dọn dẹp riêng.
- **`_finalize_action` để action fail-retryable nằm ở `running`** cho tới khi
  `reconcile_stale_actions` quét → status cuối là `stale`/`reconciliation_timeout`, mất
  `error_code` thật. Sửa cần đổi state machine — tách riêng.

## Open questions

- Migration `119`: bảng `account_actions` hiện có bao nhiêu row? Nếu > ~1M thì dùng
  `CREATE INDEX CONCURRENTLY` và tách khỏi transaction migration.
- Có nên xoá `idx_account_actions_device_time` sau Task 8 không? Nó vẫn phục vụ filter theo
  device; giữ lại trừ khi đo thấy không dùng.

## Ghi chú về file kế hoạch

Skill `planning-and-task-breakdown` yêu cầu `tasks/plan.md` + `tasks/todo.md`. Plan mode chỉ
cho ghi file này. Sau khi được duyệt, hành động đầu tiên là copy nội dung sang
`tasks/plan.md` và sinh `tasks/todo.md` (checklist 8 task + 3 checkpoint ở trên). Đã kiểm
tra: `tasks/` chưa tồn tại, không có plan dang dở nào bị ghi đè.
