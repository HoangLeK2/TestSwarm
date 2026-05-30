# DF-T-10-004 — Tool `df_device_list` — agent enumerate fleet

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-004 |
| **Title** | Tool `df_device_list` — agent enumerate device khả dụng trong org |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-10-02, FR-10-08 |
| **Truy vết — UC refs** | UC-10-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Trước khi reserve device, agent cần biết "fleet đang có device nào, trạng thái thế nào". Hôm nay thông tin này chỉ có ở dashboard hoặc qua HTTP API người vận hành dùng — agent không có cách đọc. Ticket này wrap HTTP route list device đã có sẵn (DF-E-02) thành tool `df_device_list` để agent enumerate fleet trong phạm vi token cho phép.

Persona chính là **AI Operations Supervisor (Preview)** khi giao việc cho agent ("hãy chọn device idle trong group X"). Persona phụ là **Fleet Operator** — họ cần biết device nào agent có thể "nhìn thấy" để không dispatch campaign chồng (UC-10-13).

> **Cảnh báo Preview:** Tool này thuộc phần mở rộng đang được nghiên cứu, **KHÔNG thuộc năng lực cốt lõi**. Output schema có thể thay đổi.

Ưu tiên P2 — không phải block contract mà là tool tiện ích đầu tiên dùng để chứng minh contract DF-E-10 hoạt động end-to-end.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_device_list` để lấy danh sách device khả dụng kèm trạng thái (online, busy, offline)
> **Để** agent quyết định reserve device nào trước khi gọi `df_device_claim` mà không cần tôi đưa serial sẵn.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI expose tool `df_device_list` qua MCP — trace FR-10-02.
- Tool PHẢI wrap đúng HTTP route list device hiện có của DF-E-02 — trace FR-10-08.
- Tool PHẢI nhận filter optional: `group_id`, `status` (online / offline / busy), `platform_capability` — trace FR-10-02.
- Tool PHẢI tôn trọng ownership token: token user-scoped chỉ thấy device trong org của user; token device-scoped chỉ thấy device trong scope của token — trace FR-10-04, FR-10-05.
- Output PHẢI gồm: `device_serial`, `display_name`, `status`, `current_session_id` (nếu busy), `last_heartbeat_at` — trace FR-10-08.
- Tool NÊN hỗ trợ phân trang (cursor + limit, mặc định 50, max 200) — tránh agent lấy quá nhiều dữ liệu một lúc.
- Tool PHẢI ghi audit log mỗi call (DF-T-10-011).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List device thành công với token user-scoped**

```
Given org X có 10 device và agent dùng MCP_AUTH_TOKEN của user thuộc org X
When agent gọi df_device_list không filter
Then trả về 10 device kèm status và last_heartbeat_at
And response time < 2 s
And audit log có entry với tool name + token id
```

**AC-2: Filter theo status và group**

```
Given org có 50 device, 20 online, 30 offline; group A có 15 device
When agent gọi df_device_list(status="online", group_id="A")
Then trả về subset thoả cả 2 điều kiện
And không trả về device ngoài group A
```

**AC-3: Token device-scoped chỉ thấy device trong scope**

```
Given DEVICE_FARM_MCP_TOKEN có scope cho device A1, A2, A3
When agent gọi df_device_list không filter
Then chỉ trả về A1, A2, A3
And không tiết lộ thông tin device khác trong cùng org
```

**AC-4: Phân trang**

```
Given org có 300 device
When agent gọi df_device_list(limit=100)
Then trả về 100 device + next_cursor
When agent gọi df_device_list(limit=100, cursor=next_cursor)
Then trả về 100 device kế tiếp không trùng
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm reserve device — thuộc DF-T-10-005.
- KHÔNG bao gồm device metadata chi tiết (model, OS version) — chỉ shape tối thiểu cho release Preview.
- KHÔNG bao gồm streaming push device status change — agent phải poll.
- KHÔNG bao gồm tool device manipulation (rename, group assign) — thao tác admin thuộc dashboard DF-E-11.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement handler `df_device_list` gọi service device.list của DF-E-02.
- [ ] Apply scope filter dựa trên token.
- [ ] Pagination.
- [ ] Audit log call.

**Contract / API** (`layer:contract`)

- [ ] Đăng ký tool trong registry với schema input/output.
- [ ] Map http_route_ref tới OpenAPI operation list-devices.

**Documentation** (`layer:docs`)

- [ ] Bổ sung tool reference trong `docs/modules/10-mcp-agent-tools.md`.
- [ ] Warning Preview.

**Test** (`layer:test`)

- [ ] Unit test scope filter.
- [ ] Integration test tool call end-to-end.
- [ ] Test pagination boundary.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-004-01 | Positive | 10 device trong org, token user-scoped | Gọi df_device_list | 10 device trả về, có audit log |
| TC-DF-T-10-004-02 | Positive | 20 online + 30 offline, filter status=online | Gọi df_device_list(status=online) | Đúng 20 device |
| TC-DF-T-10-004-03 | Negative | Token thuộc org X, agent set group_id thuộc org Y | Gọi df_device_list | df.permission_denied hoặc empty result + audit log cross-org attempt |
| TC-DF-T-10-004-04 | Negative | Token đã revoke | Gọi tool | df.unauthorized |
| TC-DF-T-10-004-05 | Edge | Org có 0 device | Gọi tool | Empty array + next_cursor null, không lỗi |
| TC-DF-T-10-004-06 | Edge | limit=500 (quá max 200) | Gọi tool | df.invalid_argument với message rõ "limit max=200" |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-001, DF-T-10-002, DF-T-10-003.

**Chặn:** DF-T-10-005 (agent enumerate trước khi claim).

**Phụ thuộc giữa Epic:**

- **DF-E-02 (Devices & Control Plane)** — route list device phải đã sẵn sàng và stable.

**Rủi ro:**

- **Agent gọi list quá thường xuyên gây tải:** rate-limit DF-T-10-012.
- **Leak metadata sensitive (IMEI, IP):** schema output chỉ giới hạn field cần.

**Phụ thuộc bên ngoài:** Service device.list DF-E-02.

## 10. Điều kiện hoàn thành

- [ ] Code merged + pass CI.
- [ ] Test coverage ≥ 80%.
- [ ] Test case TC-DF-T-10-004-* map sang test tự động.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter call + latency histogram.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes ghi tool mới (Preview).
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §6 FR-10-02, FR-10-08](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Fleet Operator.
- **Thuật ngữ:** Device, df_* tool.
