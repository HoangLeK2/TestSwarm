# TODO — Log account + ảnh bằng chứng khi step lỗi

Chi tiết đầy đủ (mô tả, acceptance criteria, verification, files): [`tasks/plan.md`](./plan.md)

Test command: `cd device_farm && uv run pytest tests/...`

> **Trạng thái: code + test viết xong cho cả 8 task. Chạy test 1 lần: 29 failed,
> 135 passed.** Không mục nào được đánh `[x]` cho tới khi có một lần chạy xanh.
>
> ### Triage 29 failure (lần chạy duy nhất)
>
> **2 lỗi do test tôi viết sai setup — ĐÃ SỬA, CHƯA CHẠY LẠI:**
> - `test_capture_failure_is_recorded_even_when_capture_is_not_required` — dùng step
>   `wait` (capture mặc định TẮT → `capture_before_step` return sớm). Đổi sang `extract`.
> - `test_retry_keeps_the_evidence_of_the_attempt_that_failed` — `reason_code:
>   u2_transient` + retry policy explicit thì `auto_retry_u2_transient` bị tắt nên
>   không hề retry. Đổi sang `retryable: True`.
>
> **27 lỗi tôi CHO LÀ có sẵn từ trước — mới suy luận từ code, CHƯA ĐO BASELINE:**
> - 14 lỗi `test_scenario_capture.py`: đều nhắm vào `scenario_task._capture_step_screenshot`
>   và `_run_scenario_task_legacy` (code chết — `run_scenario_task` delegate thẳng sang
>   `ScenarioExecutor`). `patch("tasks.scenario.capture.time.sleep")` fail vì module đó
>   không hề `import time`. Tôi không đụng file nào trong số này.
> - 13 lỗi `test_social_action_steps.py`: `handle_social_select_target`,
>   `handle_social_scan_posts_interact`, các path candidate-lease, và
>   `platform_required`. Trong `social_actions.py` tôi chỉ sửa `_record_ledger_error`
>   (mới), 2 site trong `_handle_social_connect_visible_people`, nhánh
>   `already_applied` của `handle_social_action`, và except của
>   `_finalize_social_action_ledger` — không nhánh nào nằm trên các path này.
>
> **Cần đo baseline để xác nhận (chưa làm được):**
> ```
> git stash push --keep-index -- <các file đã sửa> && uv run pytest ... ; git stash pop
> ```
>
> ### Thay đổi hành vi có chủ đích, đã sửa test cũ (cần review)
> - `test_enabled_finalization_failure_fails_result_after_tap` → đổi tên thành
>   `..._does_not_undo_a_tap_that_happened`, đảo assert `ok` False → True (Task 4).
>   Test này **đã pass** ở lần chạy.
> - `test_stable_action_key_unchanged_by_the_device_column` → đổi probe sanity
>   sang `target_id` vì key không còn hash tên hiển thị (Task 6). **Đã pass.**
>
> ### Self-review vòng 2 — 4 defect trong code của chính tôi, đã sửa
> 1. `step_runner` nhánh **cancel** vẫn dựng dict rỗng → mất artifact. Cùng loại lỗi
>    với 2 nhánh retry tôi đã sửa; giờ dùng `_carry_capture_evidence`.
> 2. `record_applied_actions` gom cả batch vào **một transaction** → một entry lỗi
>    rollback cả 20. Code cũ mỗi target một session nên 14/20 vẫn ghi được. Sửa bằng
>    `db.begin_nested()` per-entry + entry lỗi trả về marker `{"recorded": False}`.
> 3. `capture_error` dùng `setdefault` → lỗi phase `fail` bị che sau lỗi phase `pre`,
>    đúng cái operator cần thì mất. Giờ là dict keyed theo phase.
> 4. DLQ refs: URL và object key có thể đến từ **hai nguồn khác nhau** → read path ký
>    object của capture này rồi hiển thị dưới nhãn của capture kia. Sửa bằng `_set_ref`
>    đặt cả hai cùng lúc hoặc không đặt gì.
>
> Kèm theo: `_carry_capture_evidence` thôi mang `capture_error` qua các attempt
> (lỗi thuộc về attempt gây ra nó; mang sang sẽ để lại lỗi cũ trên attempt đã chụp được).
>
> ### Tìm thấy nhưng KHÔNG sửa (ngoài phạm vi, có sẵn từ trước)
> Path capture không gắn execution (`CAPTURE_STEPS=1` khi debug local): `execution_ctx`
> là None nên cache key thành `(serial, None, "screenshot")` — dùng chung cho **mọi**
> step. Hai step trong 30s nhận cùng một ảnh. Không ảnh hưởng campaign (luôn có
> execution_ctx). Fix cần thêm tham số `kind` vào `capture_screenshot`.
>
> ### Lưu ý về git
> `stash@{0}` ("wip-my-edits-baseline-probe") vẫn còn — `git stash pop` bị conflict ở
> `step_runner.py` nên git giữ lại entry. Conflict đã giải bằng tay, working tree đầy đủ.
> Xoá bằng `git stash drop stash@{0}` khi đã yên tâm.

---

## Phase 1 — Một step lỗi để lại ảnh xem được

- [ ] **Task 1 — Artifact URL không hết hạn** (M, deps: none)
  - [ ] `build_step_capture_payload` trả `screenshot_object_key` / `hierarchy_object_key`
  - [ ] `_artifact_ref` ghi object_key vào artifact ref
  - [ ] `_extract_step_artifacts` resolve: proxy → ký mới từ object_key → url cũ
  - [ ] Row legacy (chỉ có url) vẫn resolve, không 500
  - [ ] `uv run pytest tests/test_epic04_step_capture.py tests/test_epic04_execution_steps.py`

- [ ] **Task 2 — Ảnh lỗi đúng step, đúng thời điểm** (M, deps: Task 1)
  - [ ] `_build_activity_mini_scenario` set `_step_index_offset` = index thật
  - [ ] `build_step_capture_payload` cộng offset (cache key, object key, prefix, `step_index`)
  - [ ] `_record_capture_result` dùng `payload["step_index"]` khi có
  - [ ] `capture_screenshot` bỏ qua cache khi `kind` kết thúc bằng `_fail`
  - [ ] `uv run pytest tests/test_epic04_step_capture.py tests/test_scenario_capture.py`

- [ ] **Task 3 — Không mất ảnh khi retry, không thất bại im lặng** (S, deps: none)
  - [ ] Retry giữ `artifacts` / `artifacts_json` thay vì reset trắng (`step_runner.py:298`, `:353`)
  - [ ] `_handle_capture_failure` luôn ghi `step_result["capture_error"]`
  - [ ] `require_capture=True` giữ nguyên hành vi
  - [ ] `uv run pytest tests/test_epic04_step_capture.py tests/test_epic04_temporal_step_retry.py`

### Checkpoint 1
- [ ] `uv run pytest tests/` xanh
- [ ] Campaign thật có step fail → ảnh hiện trong Campaign Monitor, đúng số step
- [ ] Mở lại execution đó sau >1 giờ → ảnh vẫn hiện
- [ ] `detect_changes({scope: "compare", base_ref: "main"})`
- [ ] Review với người dùng trước khi sang Phase 2

---

## Phase 2 — Log account đúng và đủ

- [ ] **Task 4 — Ledger lỗi không làm hỏng hành động đã xảy ra** (S, deps: none)
  - [ ] `social_actions.py:1298`, `:1413`, `:2223` → `account_action_ledger_error`, giữ `ok=True`
  - [ ] `social_actions.py:2320` (claim-before-act) giữ nguyên `_fail`
  - [ ] Counter/log để lỗi ledger vẫn nhìn thấy được
  - [ ] `uv run pytest tests/test_social_action_steps.py tests/test_account_action_ledger.py`

- [ ] **Task 5 — Gắn ảnh lỗi vào bản ghi account action** (M, deps: Task 1, Task 2)
  - [ ] `attach_action_artifacts()` mới trong `services/account_actions/service.py`
  - [ ] `step_runner.py` gọi ngay sau `capture_fail_step`, không raise khi thiếu
  - [ ] `artifact_refs` chỉ chứa ref, không nhét cả payload
  - [ ] `_action_out` expose `device_serial`, `execution_id`, `step_id`, `platform`, `artifact_refs`
  - [ ] `uv run pytest tests/test_account_action_ledger.py`

- [ ] **Task 6 — `stable_action_key` khoá theo target_id** (S, deps: none)
  - [ ] Key dùng `{action, target_type, target_id}` khi có `target_id`
  - [ ] Không có `target_id` → fallback hành vi cũ
  - [ ] Cập nhật `test_stable_action_key_unchanged_by_the_device_column` kèm lý do
  - [ ] `uv run pytest tests/test_account_action_ledger.py`

### Checkpoint 2
- [ ] `uv run pytest tests/` xanh, gồm `test_fb_label_guard.py`, `test_fb_geometry_guard.py`, `test_template_label_guard.py`
- [ ] Campaign kết bạn thật → log account đủ device/execution/step + ảnh khi lỗi
- [ ] Xác nhận không còn gửi trùng khi ledger lỗi
- [ ] Review với người dùng trước khi sang Phase 3

---

## Phase 3 — Performance

- [ ] **Task 7 — Gom ledger batch vào một session** (M, deps: Task 4)
  - [ ] `record_actions()` mới trong `coordinator.py`, một `activity_session()`
  - [ ] Dùng lại `_resolve_tenant` / `create_action` / `transition_action` / `start_attempt` / `finish_attempt`
  - [ ] `_handle_social_connect_visible_people` gọi 1 lần thay vòng lặp 2N call
  - [ ] Cả `observe` và `enabled` mode đi qua đường gom
  - [ ] **KHÔNG** sửa `run_activity_coro_blocking`
  - [ ] Đo thời gian ghi ledger batch 20 trước/sau

- [ ] **Task 8 — Feed activity dùng được index** (M, deps: none, làm cuối vì có migration)
  - [ ] `_account_action_base` thêm predicate `org_id`, bỏ `JOIN accounts` ở nhánh có org
  - [ ] Giữ join cho nhánh không org và cho `AccountEvent` (bảng đó không có `org_id`)
  - [ ] Migration `119_account_action_org_time_index.py`
  - [ ] Cập nhật comment `db/models/account_action.py:20-24`
  - [ ] `EXPLAIN ANALYZE` xác nhận index scan
  - [ ] Kết quả feed không đổi (cùng số row, cùng thứ tự)

### Checkpoint 3
- [ ] `uv run pytest tests/` xanh
- [ ] `detect_changes({scope: "compare", base_ref: "main"})` — review blast radius
- [ ] Migration `119` upgrade + downgrade chạy sạch trên staging
- [ ] Đo lại thời gian ghi ledger và load feed
- [ ] Sẵn sàng review/merge

---

## Không làm trong plan này (xem `plan.md` § Deferred)

- Shared background event loop cho `run_activity_coro` — **CRITICAL**, 503 symbol / 24 flow
- Bỏ `COUNT(*)` chính xác trên union feed — API contract change
- Time window mặc định cho feed — quyết định sản phẩm
- Xoá `_run_scenario_task_legacy` (~1700 dòng code chết)
- `_finalize_action` để fail-retryable nằm ở `running` → kết thúc là `stale`
