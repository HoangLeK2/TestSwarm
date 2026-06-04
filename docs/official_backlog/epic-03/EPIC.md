# DF-E-03 — Agent Boot & Relay

> **Mã Epic:** DF-E-03
> **Module gốc:** DF-MOD-03 — Agent Boot & Relay
> **Phiên bản:** 1.0
> **Cập nhật lần cuối:** 2026-05-31
> **Trạng thái:** Done
> **Tài liệu liên quan:** [Đặc tả module](../../official_docs/modules/03-agent-boot-and-relay.md), [Devices & Control Plane](../../official_docs/modules/02-devices-and-control-plane.md), [Backlog README](../README.md)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Epic ID** | DF-E-03 |
| **Title** | Agent Boot & Relay |
| **Module** | DF-MOD-03 |
| **Persona chính** | Fleet Operator, Platform Engineer |
| **Persona phụ** | Social Data Operator, Automation Builder, AI Operations Supervisor |
| **Owner (placeholder)** | (sẽ điền khi import vào tracker) |
| **Status** | Done |
| **Business priority** | Medium - technical enabler cho device online/control; chỉ boot, heartbeat và command path tối thiểu là P0. |
| **Story point tổng** | 71 SP |
| **Số ticket** | 14 |
| **Release target** | M1/M2 — Relay runtime hardening |

## 2. Tổng quan Epic

Epic này biến host vật lý gắn thiết bị Android thành một relay đáng tin cậy của Device Farm. Agent chủ động mở kết nối outbound lên backend, bootstrap u2/ATX khi cần, watch thiết bị attach/detach qua ADB, publish FSM state, duy trì heartbeat/reconnect, và route command xuống các kênh ADB/u2/scrcpy/STF.

Trọng tâm product là giảm thao tác thủ công khi mở rộng fleet và giảm downtime do mạng/host/transport. Trọng tâm kỹ thuật là giữ contract giữa cloud và edge đủ rõ để DF-E-02, 4, 6, 10 và 11 tiêu thụ mà không phụ thuộc implementation chi tiết của agent.

## 3. Mapping FR ↔ Ticket

| FR refs | Phạm vi | Ticket primary | UC refs |
|---|---|---|---|
| FR-03-01 | Agent-boot CLI & host registration | DF-T-03-001 | UC-03-01 |
| FR-03-02 | Device bootstrap u2/ATX idempotent | DF-T-03-002 | UC-03-02 |
| FR-03-03 | ADB attach/detach watcher | DF-T-03-003 | UC-03-02, UC-03-06 |
| FR-03-04 | Agent-side device FSM publisher | DF-T-03-004 | UC-03-06 |
| FR-03-07 | WebSocket/gRPC relay transport parity | DF-T-03-005 | UC-03-07 |
| FR-03-05, FR-03-06 | Heartbeat & reconnect backoff | DF-T-03-006 | UC-03-04, UC-03-08 |
| FR-03-08 | USB-first connection policy & WiFi fallback | DF-T-03-007 | UC-03-05 |
| FR-03-10, FR-03-11, FR-03-12, FR-03-13 | Relay command dispatcher & session guard | DF-T-03-008 | UC-03-07 |
| FR-03-05, FR-03-15 | Agent log shipper & operational telemetry | DF-T-03-009 | UC-03-08, UC-03-10 |
| FR-03-10, FR-03-13 | ADB shell command channel | DF-T-03-010 | UC-03-07 |
| FR-03-11 | u2 gesture & hierarchy channel | DF-T-03-011 | UC-03-02 |
| FR-03-12 | scrcpy stream & remote control channel | DF-T-03-012 | UC-03-03 |
| FR-03-07 | Relay security hardening — secure handshake, gRPC TLS, per-agent identity | DF-T-03-013 | UC-03-07, UC-03-08 |
| FR-03-14 | Bulk bootstrap thiết bị mới trên một host | DF-T-03-014 | UC-03-11 |

## 4. Danh sách ticket

| Ticket ID | Title | Type | Priority | SP | Status | Trace FR |
|---|---|---|---|---|---|---|
| DF-T-03-001 | Agent-boot CLI & host registration | feature | P0 | 5 | Done | FR-03-01 |
| DF-T-03-002 | Device bootstrap u2/ATX idempotent | feature | P0 | 5 | Done | FR-03-02 |
| DF-T-03-003 | ADB attach/detach watcher | feature | P0 | 3 | Done | FR-03-03 |
| DF-T-03-004 | Agent-side device FSM publisher | feature | P0 | 5 | Done | FR-03-04 |
| DF-T-03-005 | WebSocket/gRPC relay transport parity | feature | P1 | 8 | Done | FR-03-07 |
| DF-T-03-006 | Heartbeat & reconnect backoff | feature | P0 | 5 | Done | FR-03-05, FR-03-06 |
| DF-T-03-007 | USB-first connection policy & WiFi fallback | feature | P2 | 3 | Done | FR-03-08 |
| DF-T-03-008 | Relay command dispatcher & session guard | feature | P0 | 5 | Done | FR-03-10, FR-03-11, FR-03-12, FR-03-13 |
| DF-T-03-009 | Agent log shipper & operational telemetry | feature | P2 | 3 | Done | FR-03-05, FR-03-15 |
| DF-T-03-010 | ADB shell command channel | feature | P2 | 5 | Done | FR-03-10, FR-03-13 |
| DF-T-03-011 | u2 gesture & hierarchy channel | feature | P0 | 8 | Done | FR-03-11 |
| DF-T-03-012 | scrcpy stream & remote control channel | feature | P1 | 5 | Done | FR-03-12 |
| DF-T-03-013 | Relay security hardening — secure handshake, gRPC TLS, per-agent identity | feature | P2 | 8 | Done | FR-03-07 |
| DF-T-03-014 | Bulk bootstrap thiết bị mới trên một host | feature | P3 | 3 | Done | FR-03-14 |

**Tổng:** 14 ticket, 71 SP. Phân bổ priority nghiệp vụ: 7 ticket P0 (36 SP), 2 ticket P1 (13 SP), 4 ticket P2 (19 SP), 1 ticket P3 (3 SP).

## 5. Dependency Graph

```mermaid
flowchart TB
    T001[DF-T-03-001 CLI + host registration]
    T002[DF-T-03-002 Device bootstrap]
    T003[DF-T-03-003 Attach/detach watcher]
    T004[DF-T-03-004 FSM publisher]
    T005[DF-T-03-005 Dual transport parity]
    T006[DF-T-03-006 Heartbeat + reconnect]
    T007[DF-T-03-007 USB-first policy]
    T008[DF-T-03-008 Command dispatcher]
    T009[DF-T-03-009 Log shipper]
    T010[DF-T-03-010 ADB channel]
    T011[DF-T-03-011 u2 channel]
    T012[DF-T-03-012 scrcpy channel]
    T013[DF-T-03-013 Relay security]
    T014[DF-T-03-014 Bulk bootstrap]

    T001 --> T002 --> T003 --> T004 --> T006
    T001 --> T005 --> T008
    T003 --> T007 --> T010
    T007 --> T011
    T007 --> T012
    T008 --> T010
    T008 --> T011
    T008 --> T012
    T006 --> T009
    T005 --> T013
    T002 --> T014

    E01[DF-E-01 Platform/Auth/Secret] -.-> T001
    E01 -.-> T013
    E02[DF-E-02 Devices FSM/session] -.-> T004
    T004 -.-> E02
    T006 -.-> E02
    T010 -.-> E02
    T011 -.-> E04[DF-E-04 Scenario Execution]
    T012 -.-> E11[DF-E-11 Frontend live view]
    T009 -.-> E09[DF-E-09 Notifications/Analytics]
```

## 6. Điều kiện hoàn thành riêng cho Epic

- [x] Agent khởi động trên host sạch và xuất hiện trong relay registry trong < 60 giây.
- [x] Thiết bị mới cắm vào được bootstrap idempotent, chuyển ONLINE trong KPI module.
- [x] Heartbeat/reconnect pass test mất mạng ngắn 2-5 giây và mất mạng dài.
- [x] WebSocket và gRPC parity test pass cho mọi command envelope được ship.
- [x] ADB/u2/scrcpy channel có timeout, session guard và structured error.
- [x] gRPC TLS/per-agent identity hardening có runbook rotate/revoke.
- [x] Không log secret, device key, credential hoặc payload nhạy cảm.
- [x] DF-E-02 nhận đủ device state event để fleet view không drift.

## 7. KPI Epic

| KPI | Mục tiêu | Đo từ ticket |
|---|---|---|
| Agent uptime trong giờ vận hành | >= 99% | DF-T-03-006, DF-T-03-009 |
| Bootstrap thiết bị thành công lần đầu | >= 95% | DF-T-03-002, DF-T-03-014 |
| Thời gian từ cắm device tới ONLINE | < 90 s | DF-T-03-002/003/004 |
| DEAD ratio toàn fleet | < 1% tại mọi thời điểm | DF-T-03-004/006 |
| Parity WebSocket/gRPC | 100% command mới | DF-T-03-005 |
| Tỷ lệ command không có structured error khi fail | 0 | DF-T-03-008/010/011/012 |

## 8. Risks Epic-level

- **TLS/revoke rollout:** gRPC TLS và per-agent enrollment đã có path cấu hình; production rollout vẫn cần cert provisioning và revoke drill trên staging.
- **Một host một agent là single point of failure:** mitigate bằng supervisor restart và chia tải thiết bị qua nhiều host; hot standby là lộ trình.
- **WiFi flapping gây mass failure:** DF-T-03-006 backoff + DF-T-03-007 USB-first + retry cấp DF-E-04.
- **Transport parity drift:** CI parity test bắt buộc trước khi merge command mới.

## 9. Local completion evidence

Trạng thái `Done` phản ánh implementation và regression evidence trong repo tại 2026-05-31. Các gate ngoài repo như merge vào nhánh chính, CI remote và owner code review vẫn cần chạy theo quy trình release.

| Ticket | Evidence chính |
|---|---|
| DF-T-03-001 | `agent-boot/main.py`, `agent-boot/relay/agent.py`, `agent-boot/relay/control_client.py`, `device_farm/runtime/transports/agent_control_servicer.py`, `device_farm/web/server.py`, `device_farm/tests/test_agent_control_servicer.py` |
| DF-T-03-002 | `agent-boot/bootstrap.py`, `agent-boot/relay/adb.py`, `device_farm/api/routes/relay_agents.py`, `agent-boot/relay/tests/test_bootstrap_u2_install.py`, `device_farm/tests/test_relay_agents_routes.py` |
| DF-T-03-003 | `agent-boot/relay/device_watcher.py`, `agent-boot/relay/adb.py`, `agent-boot/relay/tests/test_adb_usb_preference.py` |
| DF-T-03-004 | `agent-boot/relay/device_state.py`, `device_farm/services/device_state/relay_bridge.py`, `device_farm/tests/test_device_state_relay_bridge.py`, `device_farm/tests/test_device_state_fsm.py` |
| DF-T-03-005 | `agent-boot/relay/grpc_client.py`, `agent-boot/relay/agent.py`, `device_farm/runtime/transports/grpc_relay_server.py`, `device_farm/runtime/transports/adb_relay_server.py`, `device_farm/tests/test_grpc_relay_n2n.py`, `agent-boot/relay/tests/test_fair_send_queue.py` |
| DF-T-03-006 | `agent-boot/relay/agent.py`, `agent-boot/relay/control_client.py`, `device_farm/runtime/transports/agent_control_servicer.py`, `device_farm/services/reconnect_policy/service.py`, `device_farm/tests/test_agent_reconnect.py`, `device_farm/tests/test_agent_control_servicer.py` |
| DF-T-03-007 | `agent-boot/relay/adb.py`, `agent-boot/relay/agent.py`, `agent-boot/relay/tests/test_adb_usb_preference.py` |
| DF-T-03-008 | `device_farm/runtime/transports/adb_relay_server.py`, `device_farm/api/routes/relay_agents.py`, `device_farm/tests/test_device_relay_dispatch.py`, `device_farm/tests/test_dispatcher_n2n.py`, `device_farm/tests/test_agent_control_servicer.py` |
| DF-T-03-009 | `agent-boot/relay/runtime.py`, `agent-boot/relay/agent.py`, `device_farm/web/metrics.py`, `device_farm/api/routes/relay_agents.py` |
| DF-T-03-010 | `device_farm/runtime/transports/agent_control_servicer.py`, `agent-boot/relay/control_client.py`, `agent-boot/relay/adb.py`, `device_farm/api/routes/relay_agents.py`, `device_farm/tests/test_agent_control_servicer.py` |
| DF-T-03-011 | `agent-boot/relay/u2_executor.py`, `agent-boot/relay/u2_session_pool.py`, `agent-boot/relay/agent.py`, `device_farm/runtime/transports/u2_jsonrpc.py`, `agent-boot/relay/tests/test_u2_executor.py`, `agent-boot/relay/tests/test_u2_session_pool.py`, `device_farm/tests/test_u2_jsonrpc.py` |
| DF-T-03-012 | `agent-boot/relay/scrcpy_relay.py`, `agent-boot/relay/session_manager.py`, `device_farm/runtime/transports/scrcpy_receiver.py`, `device_farm/runtime/transports/scrcpy_control.py`, `agent-boot/relay/tests/test_scrcpy_relay_on_fatal.py`, `device_farm/tests/test_scrcpy_control.py` |
| DF-T-03-013 | `agent-boot/relay/grpc_client.py`, `agent-boot/relay/agent.py`, `agent-boot/main.py`, `device_farm/runtime/transports/grpc_relay_server.py`, `device_farm/config.yaml`, `agent-boot/relay/tests/test_grpc_client_tls.py`, `device_farm/tests/test_hardening_regressions.py` |
| DF-T-03-014 | `device_farm/api/routes/relay_agents.py`, `device_farm/services/relay_onboarding.py`, `device_farm/tests/test_relay_agents_routes.py` |

## 10. Truy vết & tài liệu tham chiếu

- Đặc tả module: [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md)
- Devices & Control Plane: [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md)
- Backlog README: [../README.md](../README.md)
