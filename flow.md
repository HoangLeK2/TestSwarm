Tổng quan hệ thống Device Farm Automation

  ---
  1. Cấu trúc dữ liệu (3 tầng)

  Campaign
    └── Scenario[]          (nhiều kịch bản, chạy theo thứ tự)
          └── Step[]        (danh sách hành động)

  DB:
  campaigns     → id, name, status, user_id
  scenarios     → id, campaign_id, name, instructions, steps (JSON), order
  devices       → id, serial, screen_width, screen_height
  campaign_devices → campaign_id, device_id

  ---
  2. Record Flow (Frontend)

  User bấm "Ghi kịch bản"
    │
    ▼
  fetchHierarchy(serial)          → cache XML vào recordXmlRef
    │
    ▼
  [User tap màn hình device]
    │
    ▼
  sendAndRecord({ type:'tap', x, y })   ← pixel từ canvas click
    │
    ├── rx = x / screen_width           ← convert → ratio (0.0–1.0)
    ├── ry = y / screen_height
    │
    ▼
  normalizeXml(xml)               ← strip: index, bounds, focused, selected
    │
    ▼
  findSelectorInXml(xml, rx, ry)  ← parse DOM browser, tìm element nhỏ nhất chứa điểm
    │
    │  Priority: resource-id > content-desc > text > class name
    │
    ├── Tìm thấy →
    │     { type:'tap',
    │       selector: { by:'resource-id', value:'com.app:id/btn' },
    │       fallback: { rx:0.52, ry:0.88 },
    │       screen:   { package:'com.app', hash:'a3f1', texts:['Login','Email'] }
    │     }
    │
    └── Không tìm thấy (flat XML) →
          { type:'tap', fallback:{rx, ry}, screen:{...} }
    │
    ▼
  pollUntilUiChange(serial, oldHash, poll=300ms, timeout=3s)
    │                                    ← dùng normalized hash → tránh false positive
    ├── hash changed → update recordXmlRef (màn mới)
    └── timeout     → giữ XML cũ (không navigate)
    │
    ▼
  Step lưu vào steps[] (local state)

  ---
  3. Save Flow

  User bấm "Lưu vào campaign"
    │
    ▼
  [Dialog bước 1] Chọn Campaign
    │
    ▼
  [Dialog bước 2] Chọn Scenario có sẵn  →  scenariosApi.update(campaignId, scenarioId, { steps })
                 hoặc Tạo mới            →  scenariosApi.create(campaignId, { name, steps })
    │
    ▼
  DB: scenarios.steps = [{ type:'tap', selector, fallback, screen }, ...]

  ---
  4. Run Campaign Flow

  POST /api/campaigns/{id}/run
    │
    ▼
  load scenarios ORDER BY order     ← tất cả scenarios của campaign
  load devices (campaign_devices)
    │
    ▼
  for each device:
    for each scenario (theo thứ tự):
      Task(fn=make_scenario_task(scenario.steps), target=device.serial)
      → enqueue vào TaskQueue
    │
    ▼
  Dispatcher → Worker → DeviceClient

  ---
  5. Executor Pipeline (mỗi Step)

  Step { type:'tap', selector, fallback, screen, wait_after:true }
    │
    ▼
  pre_hash = _hash_hierarchy(device)        ← snapshot UI trước tap
    │
    ▼
  _execute_tap(retries=2, timeout=8s)
    │
    ├── _wait_for_element(by, value, poll=300ms, timeout=8s)
    │     └── found
    │           └── _tap_random_in_bounds(bounds, margin=5px)   ← tránh center/edge fail
    │     └── not found → retry × 2
    │           └── fallback ratio tap (rx*width, ry*height)
    │
    ▼
  _wait_ui_change(pre_hash, poll=300ms, timeout=6s)
    ├── hash changed → next step ngay       ← animation 300ms → không chờ thừa
    └── timeout 6s  → next step anyway     ← tap text, không navigate → ok
    │
    ▼
  step_result { ok, message, ui_changed }
    │
    ▼
  next step

  3 loại Smart Wait:

  ┌──────────────────────┬──────────────────────┬──────────────────┐
  │       Function       │       Trigger        │ Timeout mặc định │
  ├──────────────────────┼──────────────────────┼──────────────────┤
  │ _wait_for_element()  │ Trước khi tap        │ 8s               │
  ├──────────────────────┼──────────────────────┼──────────────────┤
  │ _wait_element_gone() │ Chờ spinner biến mất │ 8s               │
  ├──────────────────────┼──────────────────────┼──────────────────┤
  │ _wait_ui_change()    │ Sau mỗi tap          │ 6s               │
  └──────────────────────┴──────────────────────┴──────────────────┘

  ---
  6. Step Types

  ┌───────────────────┬──────────────────────────────────────────────────────┐
  │       Type        │                        Mô tả                         │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ tap               │ Unified — selector + fallback ratio + screen context │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ tap_selector      │ Legacy — flat by/value, vẫn dùng pipeline mới        │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ tap_ratio         │ Coordinate-only, không có selector                   │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ launch_app        │ Mở app theo package, wait_after=2.5s                 │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ wait_element      │ Poll đến khi element xuất hiện                       │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ assert_element    │ Verify đúng màn hình, fail ngay nếu sai              │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ input_selector    │ Tìm input field → clear → send_keys                  │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ wait_element_gone │ Chờ element (spinner) biến mất                       │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ scroll_to         │ Swipe đến khi element xuất hiện                      │
  ├───────────────────┼──────────────────────────────────────────────────────┤
  │ key               │ enter / back / home                                  │
  └───────────────────┴──────────────────────────────────────────────────────┘

  ---
  7. Toàn bộ Data Flow

  [Device màn hình]
        ↑ stream MJPEG
        ↓ tap/swipe WS

  [Browser — control-record-view]
    record steps[]
        ↓ save
  [Backend DB — scenarios table]
        ↓ run
  [TaskQueue → Worker]
        ↓
  [DeviceClient — scenario_task.py]
    _wait_for_element → _tap_random → _wait_ui_change
        ↓ result
  [Campaign status + task results]

  ---
  8. Bảo đảm stability trên nhiều device

  ┌───────────────────────────┬─────────────────────────────────────────────────┐
  │          Vấn đề           │                    Giải pháp                    │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ Animation speed khác nhau │ _wait_ui_change poll hash thay vì sleep cố định │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ Network load chậm         │ _wait_for_element poll 300ms đến 8s             │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ Element bị overlay        │ _tap_random_in_bounds tránh tap đúng center     │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ XML false positive        │ normalizeXml strip volatile attrs trước hash    │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ Selector sai màn hình     │ screen.hash + fallback.rx/ry luôn có sẵn        │
  ├───────────────────────────┼─────────────────────────────────────────────────┤
  │ Selector fail             │ Retry × 2, sau đó fallback ratio                │
  └───────────────────────────┴─────────────────────────────────────────────────┘