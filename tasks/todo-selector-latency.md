# TODO — Giảm độ trễ chạy kịch bản

## Phase 1 — Selector không còn chết vì khoảng trắng

### Task 1: Fallback so khớp chuẩn hoá whitespace
- [x] `normalize_match_text(s)` — NFC → space → gộp `\s+` → strip; không casefold, không bỏ dấu
- [x] `phase_text_normalized` — dump 1 lần, quét `text` + `content-desc`, trả bounds khi đúng 1 node
- [x] >1 node khớp → trả None + log rõ
- [x] Lắp sau `phase_selector`, trước `phase_healing`
- [x] Chỉ chạy cho selector `text`/`description` (gate theo `by`, không theo whitespace — xem plan)
- [x] Test: NBSP hai chiều, hai node → từ chối, wrapper+child → một node, node trùng khít → nhường phase trước
- [ ] `pytest tests/test_phase_text_normalized.py` xanh
- [ ] Chạy thật: `tap_selector` p50 rời mốc 8s

### Task 2: Sửa dữ liệu + chặn đầu vào
- [x] `normalize_variable_spaces()` trong `db/models/utils.py`
- [x] `@validates("variables")` trên `Campaign` + `Scenario`
- [x] Migration `121_normalize_variable_spaces.py`, in before/after, `downgrade` no-op
- [ ] Chạy migration; query lại `campaigns.variables` không còn NBSP
- [ ] Ghi campaign mới có NBSP → bị chuẩn hoá

### Checkpoint 1
- [ ] `cd device_farm && uv run pytest tests/ -q` xanh
- [ ] `detect_changes({scope:"compare", base_ref:"main"})`

## Phase 2 — Recovery không được đốt 103 giây

### Task 3: Trần recovery playbook
- [x] Xác định nguồn 103s: `_try_recovery_playbooks` chạy mọi rule khớp, không giới hạn thời gian
- [x] `RecoveryPolicy.max_step_recovery_ms` (mặc định 30 000, `0` = tắt)
- [x] Kiểm tra deadline trước mỗi playbook, `break` khi hết giờ
- [x] Test: 3 playbook × 20s, trần 30s → chỉ 2 cái chạy; trần 0 → cả 3 chạy
- [ ] `pytest tests/test_incident_recovery_policy.py` xanh
- [ ] (bỏ) bỏ cuộc sớm theo trạng thái màn hình — heuristic, xem plan

## Phase 3 — Chẩn đoán không còn mù

### Task 4: `failure_class` / `reason_code` tới DB
- [x] Truy vết 3 đường dựng entry bằng tay không gọi `annotate_step_failure`
- [x] Gọi `annotate_step_failure` trong `build_execution_step_payload` (choke point duy nhất)
- [x] `reason_code='ok'` — nguồn `extraction.py:1174`; classifier bỏ qua, annotate xoá
- [x] Marker `"no control channel"` → `_DEVICE_LOST_MARKERS`
- [x] Test trong `tests/test_epic04_execution_steps.py`
- [ ] `pytest tests/test_epic04_execution_steps.py tests/test_campaign_failure_classification.py` xanh
- [ ] Chạy thật: `SELECT error_json FROM execution_steps WHERE status='failed'` có `failure_class`

## Phase 4 — Bớt phân mảnh batching

### Task 5: Thu hẹp `_CONTROL_FLOW_TYPES`
- [x] Kết luận: **không thu hẹp**. `extract` cần `break_requested` + `_LONG_TIMEOUT`;
      `save_extraction` cần offsets ngược; sửa set cần patch id cho replay.
- [x] Ghi kết luận thành comment tại `temporal/workflows.py`
- [x] `run_scenario` — ghi nhận, không sửa (đổi mô hình thực thi)

## Checkpoint cuối
- [ ] `uv run pytest tests/ -q` xanh
- [ ] 3 guard test của `CLAUDE.md`: `test_fb_label_guard.py`, `test_fb_geometry_guard.py`,
      `test_template_label_guard.py`
- [ ] Đo lại bảng chi phí leaf-step, so với bảng trong plan
- [ ] `detect_changes({scope:"compare", base_ref:"main"})`

```bash
cd device_farm && uv run pytest tests/ -q

docker compose exec -T postgres psql -U postgres -d device_farm -c "
SELECT step_type, count(*) n,
       round(percentile_cont(0.5) within group (order by duration_ms)) p50,
       round(avg(duration_ms)) avg_ms
FROM execution_steps WHERE duration_ms IS NOT NULL
GROUP BY 1 ORDER BY avg(duration_ms)*count(*) DESC LIMIT 15;"
```
