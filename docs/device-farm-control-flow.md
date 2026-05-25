# Device Farm — Luồng điều khiển & scenario (tổng quan)

Tài liệu này mô tả **toàn bộ luồng** từ Cursor/MCP → device-farm → thiết bị thật, gồm **hai kênh song song** (agent-boot relay vs APK WebSocket) và PA B `extra_data`.

> **Review (2026-05-24):** Đối chiếu với `device_client.py`, `device_manager.py`, `mcp/server.py`, `adb_relay_server.py`, `agent-boot/relay/agent.py`, `collector.py`.

---

## 1. Kiến trúc tổng quan

```mermaid
flowchart TB
  subgraph clients["Clients"]
    CURSOR["Cursor / LLM"]
    FE["Frontend browser"]
    MCP["device_farm MCP server<br/>(stdio)"]
  end

  subgraph cloud["device-farm (server)"]
    API["FastAPI REST<br/>:8081"]
    WS_UI["WebSocket /ws<br/>UI live state"]
    WS_APK["WebSocket /device-agent<br/>MODE A"]
    RELAY["Relay manager<br/>gRPC hoặc WS /relay-agent<br/>MODE B"]
    DM["DeviceManager<br/>registry DeviceClient"]
    SCN["scenario_task<br/>run_scenario_task"]
  end

  subgraph local["Máy LAN (local)"]
    AB["agent-boot relay"]
    PHONE["Android device"]
    APK["Agent APK<br/>(tuỳ cài)"]
  end

  CURSOR -->|stdio MCP| MCP
  MCP -->|HTTP JSON| API
  FE -->|HTTP + WS| API
  FE --> WS_UI

  API --> DM
  API --> SCN
  SCN --> DM

  WS_APK <-->|JSON control + tunnels| APK
  APK <-->|USB/WiFi| PHONE

  RELAY <-->|control + scrcpy H.264| AB
  AB <-->|ADB + uiautomator2| PHONE

  DM --> WS_APK
  DM --> RELAY
```

**Không gửi XML từ cloud xuống agent-boot.** Farm chỉ gửi **lệnh/metadata**; XML sinh trên máy qua u2.

---

## 2. Hai mode kết nối thiết bị

| | **MODE A — APK Agent** | **MODE B — agent-boot relay** |
|---|------------------------|-------------------------------|
| Kết nối | APK → `WS /device-agent` | agent-boot → gRPC hoặc `WS /relay-agent` |
| Đăng ký | `DeviceManager.ensure_device(serial)` khi hello | `register_relay_device` + heartbeat serials |
| Mirror | JPEG/H.264 từ APK (MediaProjection) | scrcpy qua relay |
| Touch ưu tiên | u2 tunnel :9008, WS tap/shell | u2 qua relay, `a11y_mutate` gRPC |
| Edge extract PA B | **Không** (cần relay) | **Có** (`extra_data`) |
| Tắt agent-boot | MODE A vẫn có thể chạy scenario cơ bản | Mất scrcpy relay, extra_data, a11y gRPC |

```mermaid
flowchart LR
  subgraph modeA["MODE A — APK WS"]
    A1["APK hello"] --> A2["attach_agent_sender"]
    A2 --> A3["DeviceClient READY"]
    A3 --> A4["tap / shell / WS u2 tunnel"]
  end

  subgraph modeB["MODE B — agent-boot"]
    B1["relay register + heartbeat"] --> B2["register_relay_device"]
    B2 --> B3["on_agent_status READY"]
    B3 --> B4["scrcpy + u2 batch + extra_data"]
  end

  modeA --> PHONE(("Phone"))
  modeB --> PHONE
```

**Lưu ý:** Tắt agent-boot **không** xóa `DeviceClient` khỏi registry. Nếu APK WS còn sống, thiết bị vẫn **READY** → scenario API vẫn chấp nhận chạy.

---

## 3. MCP chạy scenario (không dùng WS)

```mermaid
sequenceDiagram
  participant C as Cursor
  participant M as MCP server<br/>mcp/server.py
  participant API as device-farm<br/>POST /api/.../scenario/run
  participant ST as scenario_task
  participant DC as DeviceClient

  C->>M: tool df_run_scenario (stdio)
  Note over M,API: Giao thức MCP = stdio<br/>Không phải WebSocket
  M->>API: HTTP POST steps + serial/session_id
  API->>ST: run_scenario_on_device()
  loop mỗi step
    ST->>DC: tap / wait / extract / ...
  end
  API-->>M: JSON kết quả
  M-->>C: tool result
```

**Session MCP** (`df_start_session`) chỉ khóa thiết bị trong DB — vẫn là HTTP, không mở WS riêng cho MCP.

---

## 4. Scenario step → thiết bị (ưu tiên touch)

```mermaid
flowchart TD
  START["Step: tap_ratio / swipe / input_text / extract / wait ..."] --> TYPE{Loại step?}

  TYPE -->|wait, assert, ...| LOCAL["Xử lý trong farm<br/>không cần relay"]
  TYPE -->|extract edge_extra_data| EXT{"relay_for_serial?"}
  EXT -->|có| RELAY_EXT["relay.extra_data → agent-boot<br/>PA B"]
  EXT -->|không| FAIL_EXT["Lỗi no_relay / skip"]

  TYPE -->|tap, swipe, key, ...| TAP["DeviceClient.tap/swipe/..."]

  TAP --> U2{"self._u2 OK?"}
  U2 -->|có| U2PATH["uiautomator2<br/>relay _RelaySession<br/>hoặc tunnel APK :9008"]
  U2 -->|không| A11Y{"a11y_mutate gRPC?"}
  A11Y -->|có relay| GRPC["agent-boot a11y"]
  A11Y -->|không| SHELL{"shell input OK?"}
  SHELL -->|có| WS_SHELL["WS → APK shell"]
  SHELL -->|không| WS_TAP["WS → APK tap/swipe"]

  U2PATH --> PHONE(("Android"))
  GRPC --> PHONE
  WS_SHELL --> PHONE
  WS_TAP --> PHONE
  RELAY_EXT --> PHONE
```

---

## 5. PA B — `extra_data` (edge extract, relay-only)

Farm **không** có XML. Chỉ gửi `strategy` + `context` (expand flags, execution_id, …).

```mermaid
sequenceDiagram
  participant ST as extraction.py<br/>request_edge_extra_data
  participant DC as DeviceClient
  participant RM as RelayManager
  participant AB as agent-boot<br/>_handle_extra_data
  participant COL as collector.py
  participant U2 as uiautomator2<br/>trên máy
  participant ING as ingest + PostgreSQL

  ST->>DC: request_extra_data_xml()
  DC->>RM: extra_data (gRPC/WS control)
  RM->>AB: JSON type=extra_data
  Note over AB: create_task ngay<br/>không chờ queue lâu
  AB->>COL: collect_xml_snapshots

  alt expand_see_more_fast (mặc định)
    COL->>U2: click_selector Xem thêm / See more<br/>không dump
  else xml_fallback / fast=false
    COL->>U2: dump_hierarchy → parse bounds → click
  end

  COL->>U2: dump_hierarchy (1 lần snapshot cuối)
  COL->>ING: build_ingest_payload + process_payload
  ING-->>AB: parsed_count, items, ...
  AB-->>RM: extra_data_result
  RM-->>DC: ok + ingest summary
  DC-->>ST: scenario step done
```

**Thời gian chủ yếu:** `dump_hierarchy` trên máy (~10s/lần trên một số OEM). Spinner UI = farm **block** chờ `extra_data_result` (một response cuối).

---

## 6. agent-boot nhận lệnh relay

```mermaid
flowchart TD
  DF["device-farm RelayManager"] -->|send_json_request| CH{"Kênh relay?"}
  CH -->|RELAY_MODE=grpc| GRPC["gRPC AgentControlClient<br/>ctrl_q"]
  CH -->|WS mode| RWS["WebSocket /relay-agent"]

  GRPC --> H["_handle_server_msg"]
  RWS --> H

  H --> T{type?}
  T -->|extra_data| ED["create_task _handle_extra_data"]
  T -->|u2_batch| UB["create_task _handle_u2_batch"]
  T -->|a11y_action| AA["await _handle_a11y_action"]
  T -->|command| CMD["await ADB shell<br/>blocking consumer"]
  T -->|scrcpy_start/stop| SC["await scrcpy session"]

  ED --> POOL["U2SessionPool<br/>u2.connect"]
  POOL --> EXEC["U2Executor.run_batch"]
  EXEC --> DEV["dev.dump_hierarchy / click / click_selector"]
```

`extra_data` dùng `create_task` → không block consumer cho tới khi dump xong; farm vẫn **đợi** reply qua `send_json_request`.

---

## 7. Vì sao tắt agent-boot scenario vẫn chạy?

```mermaid
flowchart TD
  OFF["Tắt agent-boot"] --> LOST["Mất MODE B<br/>relay index, scrcpy, extra_data, a11y gRPC"]
  OFF --> APKQ{"APK WS<br/>/device-agent<br/>còn nối?"}
  APKQ -->|Có| KEEP["DeviceClient vẫn READY<br/>tap/shell/WS"]
  APKQ -->|Không| DEAD["Chỉ còn entry registry<br/>lệnh touch fail"]

  KEEP --> SCN_OK["scenario tap/wait/scroll<br/>có thể OK"]
  LOST --> SCN_EXT["step extract edge_extra_data<br/>FAIL no_relay"]
```

---

## 8. Frontend & relay panel

```mermaid
flowchart LR
  FE["Frontend"] -->|REST| API["device-farm API"]
  FE -->|WS /ws| LIVE["Trạng thái device,<br/>scenario_active, mirror"]
  API --> RELAY_API["GET /api/relay-agents"]
  RELAY_API --> RM["RelayManager<br/>connected relays + serials"]
```

UI mirror có thể từ **APK stream** hoặc **relay scrcpy** — độc lập với MCP.

---

## 9. Bảng giao thức theo từng đoạn

| Đoạn | Giao thức | Ghi chú |
|------|-----------|---------|
| Cursor ↔ MCP | **stdio** (MCP) | Không WS |
| MCP ↔ device-farm | **HTTP REST** | `DEVICE_FARM_URL` |
| Frontend ↔ farm | HTTP + **WS `/ws`** | Live UI |
| APK ↔ farm | **WS `/device-agent`** | MODE A |
| agent-boot ↔ farm | **gRPC** (hoặc WS `/relay-agent`) | MODE B, log `GRPC mode` |
| farm ↔ phone (extract) | Relay JSON `extra_data` → u2 | Không đẩy XML từ cloud |
| u2 trên máy | **uiautomator2** Python → atx-agent :7912 | Qua `U2SessionPool` |

---

## 10. Scenario selector (uiautomator2)

Các bước `tap_selector`, `wait_element`, `assert_element`, `input_selector`, `long_tap_selector`, `scroll_to`, `if_element` và `tap` hỗ trợ **selector nested**:

```json
{
  "type": "tap_selector",
  "selector": {
    "by": "text",
    "value": "Wi‑Fi",
    "conditions": { "className": "android.widget.TextView" },
    "instance": 0,
    "chain": {
      "op": "relative",
      "direction": "right",
      "target": { "className": "android.widget.Switch" }
    }
  },
  "fallback": { "rx": 0.5, "ry": 0.8 },
  "timeout": 8
}
```

| Thành phần | Mô tả |
|------------|--------|
| `by` + `value` | Điều kiện chính (text, resource-id, xpath, …) |
| `conditions` | AND thêm (className, clickable, textContains, …) |
| `instance` / `index` | Phần tử thứ N trùng điều kiện |
| `chain` | `child`, `sibling`, `relative`, `child_by_text`, `child_by_description` |

**Legacy:** top-level `by`/`value` vẫn được đọc. UI ghi `selector` nested khi ghi kịch bản.

**Runtime:** selector đơn / multi-field → JSON-RPC (`u2_jsonrpc.find_element_spec`). Chain → **agent-boot** `wait_and_click_spec` / `exists_spec` (Python u2). Không có relay → fallback xpath (`compile_chain_to_xpath`).

| File | Vai trò |
|------|---------|
| `device_farm/services/scenario_selector.py` | Normalize, RPC dict, xpath compile |
| `device_farm/runtime/transports/u2_jsonrpc.py` | `find_element_spec` |
| `agent-boot/relay/u2_executor.py` | `_resolve_spec`, chain ops |
| `device_farm/tasks/scenario/utils.py` | `_retry_find_element`, `_execute_tap` |

---

## 11. File code tham chiếu

| Thành phần | File |
|------------|------|
| Hai mode, tap priority | `device_farm/runtime/core/device_client.py` |
| Registry | `device_farm/runtime/core/device_manager.py` |
| MCP → HTTP | `device_farm/mcp/server.py` |
| Scenario API | `device_farm/api/routes/device_control/scenarios.py` |
| Edge extract | `device_farm/tasks/scenario/steps/extraction.py` |
| Relay RPC | `device_farm/runtime/transports/adb_relay_server.py` |
| Relay handler | `agent-boot/relay/agent.py` |
| Collect + expand | `agent-boot/relay/extra_data/collector.py` |
| u2 ops | `agent-boot/relay/u2_executor.py`, `u2_session_pool.py` |
| PA B runbook | `docs/plans/agent-boot-direct-content-writer/reports/edge-extra-runbook.md` |

---

## Sơ đồ một trang (quick reference)

```mermaid
flowchart TB
  MCP["MCP stdio"] -->|HTTP| RUN["scenario/run"]
  RUN --> ST["scenario_task"]
  ST --> DC["DeviceClient"]

  DC -->|MODE B| AB["agent-boot"]
  AB --> U2["u2 dump/tap/selector"]
  U2 --> P(("Phone"))

  DC -->|MODE A| APK["APK WS"]
  APK --> P

  ST -->|extract only| AB
```
