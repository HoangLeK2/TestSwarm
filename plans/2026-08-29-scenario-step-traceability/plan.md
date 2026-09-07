---
title: "Truy vết node trong loop/branch và nguyên nhân khi fail"
description: "Biết node nào đang chạy ở bất kỳ độ sâu nào, và khi fail thì biết vì sao — kể cả khi lỗi nằm ở tầng điều khiển."
status: pending
priority: P1
effort: 2-3 days
branch: fix/relay-registration-scaling
tags: [backend, observability, temporal, scenario, execution-events]
created: 2026-08-29
---

# Truy Vết Node Trong Loop/Branch Và Nguyên Nhân Khi Fail

## Summary

Hôm nay mọi authored step đều có `id` ổn định, và leaf step sinh đủ
`step.started` / `step.retried` / `step.completed` / `step.failed` kèm
`reason_code`. Hai lỗ hổng còn lại:

1. **Không biết node đang chạy ở đâu trong cây.** Một `connection_request` nằm
   trong `loop → if_variable → then` phát ra event mang đúng `step_id`, nhưng
   không nói nó thuộc vòng lặp thứ mấy, nhánh nào. Cùng một `step_id` xuất hiện
   40 lần trong 40 vòng, phân biệt được với nhau chỉ nhờ `started_at`.
2. **Node điều khiển fail thì im lặng.** `loop`, `if_variable`, `if_element`,
   `random_pick`, `run_scenario` chạy trong workflow và chỉ gọi
   `_mark_step_started()` — state trong bộ nhớ cho query, **không ghi execution
   event**. Nên `loop` dừng vì `stall_after` (`outcome="stalled"`) không để lại
   dấu vết nào trong timeline, dù đó là một trong những kiểu hỏng hay gặp nhất.

Mục tiêu:

- Mọi event của leaf step mang được đường đi đầy đủ tới nó, kể cả qua nhiều tầng
  loop và branch.
- Node điều khiển fail thì có event riêng, có `reason_code` phân loại.
- Biết được node nào đang chạy **theo thời gian thực**, không chỉ khi mổ xẻ sau.
- Đường preview/fleet có cùng dữ liệu trace như đường campaign.
- Không làm phình Temporal history hay bảng `execution_events`.

## Ràng Buộc Quyết Định Thiết Kế

**Không phát event mỗi vòng lặp.** Template gieo mầm đặt `SEED_CYCLES=9999`;
một `step.started` + `step.completed` mỗi vòng là ~20k row cho một execution,
và nếu phát từ workflow thì mỗi lần là một activity call ghi vào Temporal
history. Đây là ràng buộc cứng, không phải sở thích.

Cách đi vòng qua nó: **đường đi được mang trên chính event mà leaf step đã phát
sẵn**, thay vì phát thêm event cho tầng điều khiển. Node điều khiển chỉ phát
event ở **biên** — vào, ra, và khi fail — nên số event tỉ lệ với số node điều
khiển, không tỉ lệ với số vòng lặp.

## Đường Ống Đã Có Sẵn

Ba mảnh đã tồn tại và chưa được nối:

| Mảnh | Ở đâu | Trạng thái |
|---|---|---|
| `_TRACE_KEYS` có `step_path`, `repeat_index`, `repeat_count` | `services/execution/trace_context.py:10` | khai báo rồi, **chưa ai ghi** |
| `trace_from_runtime_context()` đọc `runtime_context["__scenario_trace__"]` | `trace_context.py:69` | hoạt động, **chưa ai đổ vào** |
| `ctx` chảy từ `_handle_loop` → `_execute_child_steps` → activity | `temporal/workflows.py:1897` | đã chảy, mang sẵn `_loop_iter` |

Nên phần lớn Phase 1 là **đổ dữ liệu vào một khe đã mở**, không phải dựng đường
ống mới. Không thêm activity call, không thêm dòng nào vào Temporal history.

## Key Changes

### 1. `step_path` — đường đi tới node

Chuỗi id từ gốc tới node, kèm chỉ số vòng lặp và tên nhánh:

```
seed_friends_group_loop#0/seed_friends_cycle#37/seed_friends_connect_0.then/seed_friends_connection_request_0
```

Quy ước:

- `#N` — chỉ số vòng lặp (0-based), chỉ xuất hiện trên node loop/repeat
- `.then` / `.else` / `.branch2` — nhánh đã chọn
- Phân tách bằng `/`

Đọc được bằng mắt, và grep được: `step_path LIKE '%seed_friends_cycle#37%'` ra
đúng mọi thứ đã chạy trong vòng 37.

Kèm theo các trường rời để query không phải parse chuỗi:

| Trường | Ý nghĩa |
|---|---|
| `step_path` | đường đi đầy đủ như trên |
| `loop_iter` | chỉ số vòng lặp gần nhất |
| `loop_id` | id của node loop gần nhất |
| `branch` | nhánh đã chọn ở node điều khiển gần nhất |
| `depth` | đã có sẵn |

### 2. Event cho node điều khiển — chỉ ở biên

| Event | Khi nào | Số lượng |
|---|---|---|
| `step.started` cho node điều khiển | trước khi vào loop/branch | 1/node |
| `step.completed` | ra khỏi loop/branch, ok | 1/node |
| `step.failed` | loop stall, iteration fail, branch fail, điều kiện lỗi | 1/node |

Payload của `step.completed`/`step.failed` trên node loop mang thêm:
`iterations_run`, `stopped_by` (`count` / `duration` / `break` / `stall` /
`cancel` / `child_failure`), `idle_streak`.

**Không** phát event mỗi vòng. `iterations_run` trả lời "chạy bao nhiêu vòng"
mà không cần 9999 row.

### 3. `reason_code` cho lỗi tầng điều khiển

Hiện `reason_code` chỉ có ở leaf (`handler_exception`, `stuck_screen`,
`stale_frame`, `capture_required_failed`, `incident_recovery_failed` — rải rác
trong `step_runner.py`, `capture_service.py`). Tầng điều khiển không có gì.

Thêm, và gom vào một module có tên:

| reason_code | Nghĩa |
|---|---|
| `loop_stalled` | `stall_after` vòng liên tiếp không hành động — màn hình không phải cái loop chờ |
| `loop_iteration_failed` | một vòng fail; kèm `failed_iteration` và `nested_failure` |
| `loop_no_nested_steps` | loop rỗng — lỗi cấu hình |
| `loop_invalid_count` | `count` không parse được |
| `branch_failed` | nhánh then/else fail |
| `condition_eval_failed` | không đánh giá được điều kiện (device không trả lời) |
| `subscenario_failed` | `run_scenario` con fail |

`loop_stalled` là cái quan trọng nhất: hiện nó chỉ nằm trong `message` dạng
chuỗi, nên không đếm được, không cảnh báo được, không lên dashboard được.

### 4. Live progress — node đang chạy ngay lúc này

`get_live_progress` (`workflows.py:845`) hiện trả `current_step` (số) và
`current_step_type`. Thêm:

- `current_step_id`
- `current_step_path`
- `current_loop_iter`

Đây là cái trả lời "node nào **đang** chạy" khi loop đang ngủ `idle_delay` 30s và
chưa có leaf event nào phát ra.

### 5. Đường local có cùng dữ liệu

`tasks/scenario/steps/control_flow.py:handle_loop` là bản thứ hai của cùng logic,
dùng cho preview và fleet. Nó phải ghi cùng `step_path` vào
`sc.ctx["__scenario_trace__"]`, để trace của preview đọc giống trace của campaign.

Không thêm execution event cho đường local — đường đó không có `execution_id`.

## Implementation Phases

### Phase 1: `step_path` xuyên suốt

File:

- `device_farm/services/execution/trace_context.py`
- `device_farm/temporal/workflows.py` (`_handle_loop`, `_handle_if_branch`, `_handle_random_pick`, `run_scenario`)

Việc:

- Thêm `loop_iter`, `loop_id`, `branch` vào `_TRACE_KEYS`.
- Helper `push_step_path(ctx, *, step_id, loop_iter=None, branch=None)` trả về
  `ctx` mới với `__scenario_trace__` đã nối thêm một chặng. Không mutate — mỗi
  nhánh của cây phải có bản trace riêng, dùng chung dict là cách nhanh nhất để
  vòng 37 báo cáo mình là vòng 36.
- Gọi ở mỗi chỗ workflow đi xuống một tầng: mỗi vòng của `_handle_loop`, mỗi
  nhánh của if/random_pick, mỗi lần vào `run_scenario`.

Acceptance:

- Một leaf event từ trong loop lồng loop mang `step_path` có cả hai chỉ số.
- Không có activity call nào được thêm; Temporal history không đổi kích thước.

### Phase 2: Event cho node điều khiển

File:

- `device_farm/temporal/workflows.py`
- `device_farm/services/execution/activity_events.py`
- `device_farm/temporal/activities.py` (activity mới `emit_control_flow_event`)

Việc:

- Activity `emit_control_flow_event(execution_id, event_type, step_id, step_path, payload)`.
  Node điều khiển chạy trong workflow nên không tự ghi DB được — phải qua
  activity, giống `persist_step_checkpoint` (`workflows.py:1399`).
- Gọi ở biên vào/ra của loop, if, random_pick, run_scenario. **Không** gọi trong
  thân vòng lặp.
- Payload loop mang `iterations_run`, `stopped_by`, `idle_streak`.

Acceptance:

- Một scenario 2 loop lồng nhau × 100 vòng sinh **4** event điều khiển, không
  phải 400.
- Loop dừng vì stall để lại đúng một `step.failed` với `stopped_by="stall"`.

### Phase 3: `reason_code` tầng điều khiển

File:

- `device_farm/services/execution/reason_codes.py` (mới)
- `device_farm/temporal/workflows.py`
- `device_farm/tasks/scenario/steps/control_flow.py`

Việc:

- Module hằng số cho reason code tầng step, gom cả những chuỗi đang rải rác ở
  `step_runner.py` và `capture_service.py` để chúng có một chỗ để đọc.
- Gán `reason_code` vào result của loop/branch khi fail, ở **cả hai** executor.
  Hai bản logic loop đã lệch nhau một lần rồi (`stall_after` chỉ có ở một bên,
  204 vòng vô ích trong 8.5 phút) — nên phần này sửa song song, có test bắt
  lệch.
- `attach_nested_failure_details` đã bơm `nested_failure` vào result; đảm bảo nó
  tới được payload của event.

Acceptance:

- `loop_stalled` đếm được bằng query, không phải grep `message`.
- Test đối chiếu: cùng một kịch bản hỏng cho ra cùng `reason_code` ở cả hai
  executor.

### Phase 4: Live progress

File:

- `device_farm/temporal/workflows.py` (`WorkflowProgress`, `_mark_step_started`, `get_live_progress`)
- `device_farm/api/routes/device_control/campaign_fleet.py:886`

Việc:

- `_mark_step_started` nhận thêm `step_id` và `step_path`.
- `get_live_progress` trả thêm ba trường mới.

Acceptance:

- Trong lúc loop đang ngủ `idle_delay_seconds`, query trả về đúng node và đúng
  vòng hiện tại.

### Phase 5: Đường local

File:

- `device_farm/tasks/scenario/steps/control_flow.py`
- `device_farm/tasks/scenario_task.py`

Việc:

- Dùng cùng `push_step_path` để ghi vào `sc.ctx`.
- Trace của preview đọc được giống trace campaign.

Acceptance:

- Preview một scenario có loop → step result mang `step_path` đúng định dạng.

### Phase 6: Docs + test

File:

- `docs/execution-event-catalogue.md`
- `docs/modules/campaigns-scenarios-executions.md`
- `docs/modules/social-node-contract.md`

Việc:

- Ghi các trường trace mới và bảng reason code vào catalogue.
- Ghi rõ quy ước: **không phát event mỗi vòng lặp**, và vì sao.

## Test Plan

```bash
cd device_farm
uv run pytest tests/test_temporal_workflows.py tests/test_execution_integration.py -q
uv run pytest tests/ -q -k "trace or execution_event or step_event or loop"
```

Test mới:

- `step_path` đúng qua loop lồng loop và qua nhánh else
- mỗi vòng lặp có `loop_iter` riêng (không rò rỉ giữa các nhánh)
- số event điều khiển tỉ lệ với số node, **không** với số vòng lặp
- `loop_stalled` xuất hiện với `stopped_by="stall"` và `idle_streak`
- `loop_iteration_failed` mang `failed_iteration` và `nested_failure`
- hai executor cho cùng `reason_code` trên cùng kịch bản hỏng
- `get_live_progress` trả đúng node khi loop đang ngủ

Runtime proof riêng:

- Chỉ claim live-pass khi có campaign execution trace thật có loop chạy nhiều
  vòng. Preview không chứng minh được đường Temporal.

## Assumptions

- Không đổi ngữ nghĩa điều khiển: loop dừng khi nào, nhánh nào chạy — giữ nguyên.
- Không đổi shape của event đã có; chỉ thêm trường vào `trace` và `payload`.
- `schema_version` của event giữ nguyên `1` vì thay đổi là thêm, không phá.
- Không thêm bảng mới; `execution_events` và `execution_steps` đủ chỗ.

## Risks

- **Phình dữ liệu** là rủi ro chính. `step_path` dài ra theo độ sâu; cần giới hạn
  độ dài và cắt ở giữa thay vì cắt đuôi (đuôi là chính node đang chạy).
- **Hai executor lệch nhau lần nữa.** Đã xảy ra với `stall_after`. Phase 3 phải
  có test đối chiếu, không chỉ sửa song song rồi tin.
- **Activity mới ở Phase 2 nằm trên đường campaign.** Lỗi ghi event không được
  làm hỏng execution — phải nuốt lỗi và log, giống `_emit_step_events_for_activity`.
- Nếu sau này cần chi tiết từng vòng, quyết định "không phát event mỗi vòng" sẽ
  phải xem lại — nhưng khi đó lối ra là sampling có kiểm soát, không phải bỏ trần.
