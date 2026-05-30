# DF-T-11-004 — Device detail UI — metadata, live view scrcpy, session control

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-004 |
| **Title** | Device detail UI — metadata, live view scrcpy stream, reservation, session control |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `risk:performance`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-11-05, FR-11-06 |
| **Truy vết — UC refs** | UC-11-03, UC-11-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Khi cần can thiệp thủ công, Fleet Operator phải xem màn hình device realtime — đó là live view qua scrcpy stream (FR-11-06). Trang detail còn hiển thị metadata device, lịch sử session, action reserve/release. KPI module 11: live view mở < 3 s trung vị, < 8 s p99; reconnect WebSocket ≥ 95%.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** mở device detail thấy metadata + live view scrcpy + lịch sử session + action reserve/release
> **Để** can thiệp thủ công khi device kẹt mà không cần ADB tay.

## 4. Yêu cầu chức năng

- Trang `/dashboard/devices/[serial]` PHẢI hiển thị: metadata (model, OS, IP), status, current session, lịch sử session gần — trace FR-11-05.
- Trang PHẢI hỗ trợ mở live view scrcpy qua WebSocket — trace FR-11-06.
- Live view PHẢI mở < 3 s với kết nối tốt — trace KPI module 11.
- Live view mất kết nối PHẢI hiển thị status rõ và tự reconnect — trace FR-11-06.
- Action PHẢI có: reserve device (mở session), release session, run scenario (link DF-E-04).
- Trang PHẢI cảnh báo khi user mở 2 tab live view của cùng device (tránh nhầm).
- Stream PHẢI một chiều (observability), không bao gồm điều khiển touch qua stream — gesture phải qua API.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Mở live view nhanh**

```
Given device A1 online + relay agent up
When user click "Open live view"
Then khung hình đầu hiển thị trong < 3 s (kết nối tốt)
And status indicator "live"
```

**AC-2: Mất kết nối reconnect**

```
Given live view đang chạy
When WebSocket drop
Then UI hiển thị "Stream lost, reconnecting..."
And tự reconnect (exponential backoff)
And reconnect ≥ 95% trong điều kiện mạng tốt
```

**AC-3: Reserve device**

```
Given user có quyền reserve
When click "Reserve" → confirm
Then session mới được tạo
And status badge chuyển sang "in your session"
```

**AC-4: Cảnh báo 2 tab live view**

```
Given user mở live view A1 ở tab 1
When user mở tab 2 cũng cho A1
Then tab 2 hiển thị cảnh báo "Live view of A1 already open in another tab"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm gesture qua stream — gesture phải qua API reserve.
- KHÔNG bao gồm recording session video — lộ trình.
- KHÔNG bao gồm bulk live view nhiều device cùng lúc — backlog.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Trang detail layout.
- [ ] WebSocket hook scrcpy.
- [ ] Reconnect backoff.
- [ ] Action reserve/release.
- [ ] Cảnh báo cross-tab (BroadcastChannel).

**Contract / API** (`layer:contract`)

- [ ] Endpoint `/ws/scrcpy/{serial}` của backend (DF-E-03).
- [ ] Endpoint reservation DF-E-02.

**Documentation** (`layer:docs`)

- [ ] Doc UX live view.

**Test** (`layer:test`)

- [ ] E2E mở live view < 3 s.
- [ ] Test reconnect.
- [ ] Test cross-tab warning.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-004-01 | Positive | Device online | Mở live view | First frame < 3 s |
| TC-DF-T-11-004-02 | Positive | Reserve sẵn sàng | Click reserve | Session tạo |
| TC-DF-T-11-004-03 | Negative | Device offline | Mở live view | Error "device offline", không spinner vô tận |
| TC-DF-T-11-004-04 | Negative | User không có quyền reserve | Click reserve | Reject với message rõ |
| TC-DF-T-11-004-05 | Edge | WebSocket drop giữa stream | Quan sát | Auto reconnect, status hiển thị rõ |
| TC-DF-T-11-004-06 | Edge | Mở 2 tab live view cùng device | Tab 2 | Cảnh báo cross-tab |
| TC-DF-T-11-004-07 | Edge | Mạng yếu (loss 10%) | Quan sát | Stream lag nhưng không freeze; bitrate giảm |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-003.

**Chặn:** Không.

**Phụ thuộc giữa Epic:**

- **DF-E-02** — reservation API.
- **DF-E-03** — scrcpy stream qua relay.

**Rủi ro:**

- **Stream tốn băng thông:** chia bitrate config; nếu cần thì backlog adaptive bitrate.
- **WebSocket idle bị middleware ngắt:** heartbeat ping-pong.

**Phụ thuộc bên ngoài:** Backend WebSocket, scrcpy on host.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: histogram first_frame_latency, counter reconnect_success/fail.
- [ ] Code review ≥ 1 approve.
- [ ] Đạt KPI live view < 3 s trung vị.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-05, FR-11-06 + §5.4](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [03-agent-boot-and-relay.md](../../official_docs/modules/03-agent-boot-and-relay.md).
- **Nhóm người dùng:** Fleet Operator.
- **Thuật ngữ:** Device, scrcpy, WebSocket, Reservation.
