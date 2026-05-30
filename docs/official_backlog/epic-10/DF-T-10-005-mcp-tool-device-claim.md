# DF-T-10-005 — Tool `df_device_claim` / `df_start_session` — reserve device

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-005 |
| **Title** | Tool `df_device_claim` / `df_start_session` — reserve device theo mô hình L3 (1 agent ↔ 1 device) |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:db`, `type:feature`, `risk:auth`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-10-03, FR-10-06, FR-10-07, FR-10-13, FR-10-20 |
| **Truy vết — UC refs** | UC-10-04, UC-10-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Tool `df_device_claim` (alias semantic của `df_start_session` — claim ám chỉ "đăng ký quyền điều khiển") là tool quan trọng nhất của DF-E-10: nó tạo bản ghi `mcp_sessions`, enforce mô hình L3 (một agent tại một thời điểm sở hữu duy nhất một session/device), và là điểm bắt đầu của mọi vòng đời tool call sau đó. Không có tool này, audit không truy vết được "agent A đã thao tác gì trên device B từ lúc nào tới lúc nào".

Persona chính là **AI Operations Supervisor (Preview)** giám sát reservation; persona phụ là **Fleet Operator** vì họ cần biết device đang bị agent nào reserve để không dispatch campaign chồng (UC-10-13).

> **Cảnh báo Preview:** Mô hình ownership L3 vẫn ở trạng thái Preview. Concurrency lock chặt chưa enforce ở cấp DB (gap được ghi nhận tại module 10 mục 8) — release này dùng lock mềm có retry. Mọi tích hợp dựa vào tool này phải hiểu rủi ro.

Ưu tiên P1 vì là gate cho tất cả tool device-level và campaign sau.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_device_claim` để reserve device trước khi thao tác, và mọi tool call sau đều gắn vào session đã claim
> **Để** mọi hành động của agent có ngữ cảnh phiên rõ ràng và có thể audit được từ đầu tới cuối.

## 4. Yêu cầu chức năng

- Tool PHẢI tạo bản ghi `mcp_sessions` (agent_id, device_serial, started_at, started_by_token_id, organization_id) — trace FR-10-06.
- Tool PHẢI từ chối nếu device đang bị agent khác hoặc người vận hành reserve — trace FR-10-07, FR-10-20.
- Tool PHẢI từ chối nếu agent (định danh qua token id) đang giữ session khác chưa close — trace FR-10-07.
- Tool PHẢI chấp nhận tham số `device_serial` HOẶC một filter chọn device idle theo tiêu chí (group, capability) — trace FR-10-03.
- Tool PHẢI trả về `session_id` để mọi tool call sau dùng — trace FR-10-13.
- Tool PHẢI có tool đồng hành `df_end_session` idempotent (call hai lần không sinh lỗi) — trace FR-10-13.
- Tool PHẢI có tool `df_get_session_info` đọc trạng thái session hiện tại — trace FR-10-13.
- Khi token revoke giữa phiên, session PHẢI tự đóng và mọi tool call sau bị reject — trace FR-10-04, FR-10-20.
- Tool PHẢI ghi audit log đầy đủ (DF-T-10-011).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Claim device idle thành công**

```
Given device A1 đang idle (status online, không reservation)
And agent dùng MCP_AUTH_TOKEN của user thuộc org sở hữu A1
When agent gọi df_device_claim(device_serial="A1")
Then trả về session_id mới
And mcp_sessions có record (agent_id, device A1, started_at)
And device A1 chuyển sang status busy + current_session_id = session_id
And audit log ghi tool call thành công
```

**AC-2: Claim fail khi device đang bị agent khác giữ**

```
Given device A1 đã được agent B claim trước đó (session active)
When agent A gọi df_device_claim(device_serial="A1")
Then trả về mã lỗi df.conflict "device already reserved by another session"
And không sinh bản ghi mcp_sessions mới
And audit log ghi attempt fail
```

**AC-3: Mô hình L3 — agent không giữ 2 session cùng lúc**

```
Given agent đang giữ session S1 trên device A1
When cùng agent gọi df_device_claim(device_serial="A2")
Then trả về df.precondition_failed "agent already owns active session S1, end first"
And mcp_sessions không sinh record mới
```

**AC-4: End session idempotent + token revoke flow**

```
Given agent đang giữ session S1
When agent gọi df_end_session(S1)
Then session chuyển terminal state "ended"
When agent gọi df_end_session(S1) lần 2
Then trả về thành công với note "already ended", không lỗi
Given session S2 đang active
When token cấp S2 bị revoke
Then session S2 tự đóng trong < 10 s với terminal state "revoked"
And mọi tool call gắn S2 sau đó bị reject df.unauthorized
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm concurrency lock cứng cấp DB — release Preview dùng lock mềm (gap module 10 mục 8).
- KHÔNG bao gồm handoff session sang người vận hành — thuộc backend hook DF-T-10-011 + lộ trình UX.
- KHÔNG bao gồm bulk claim nhiều device cùng lúc — mô hình L3 là một agent ↔ một device.
- KHÔNG bao gồm session migration giữa các agent — agent phải end và agent khác claim mới.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement handler df_device_claim wrap route reservation DF-E-02.
- [ ] Implement df_end_session idempotent.
- [ ] Implement df_get_session_info.
- [ ] Enforce L3: kiểm tra agent đã có session active chưa.
- [ ] Lắng nghe sự kiện token revoke → close session.

**Database / Migration** (`layer:db`)

- [ ] Bảng `mcp_sessions` (session_id, agent_id, token_id, device_serial, org_id, started_at, ended_at, terminal_reason).
- [ ] Index theo agent_id (active session lookup) và device_serial.

**Contract / API** (`layer:contract`)

- [ ] Schema input/output trong registry.
- [ ] Mapping http_route_ref.
- [ ] Mã lỗi df.conflict, df.precondition_failed (đầu mối với DF-T-10-013).

**Documentation** (`layer:docs`)

- [ ] Doc mô hình L3 + ví dụ flow agent claim → end.
- [ ] Warning Preview + cảnh báo gap concurrency lock.

**Test** (`layer:test`)

- [ ] Unit test L3 guard.
- [ ] Integration test claim/end luồng thành công.
- [ ] Integration test race (2 agent claim cùng device — lock mềm vẫn phải xử lý).
- [ ] Test token revoke giữa phiên.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-005-01 | Positive | Device A1 idle | df_device_claim(A1) | session_id trả về, audit log + mcp_sessions có record |
| TC-DF-T-10-005-02 | Positive | Session S1 active | df_end_session(S1) → df_end_session(S1) | Lần 1 OK; lần 2 OK với note "already ended" |
| TC-DF-T-10-005-03 | Negative | Device A1 đang reserved bởi người vận hành (không phải MCP) | df_device_claim(A1) | df.conflict |
| TC-DF-T-10-005-04 | Negative | Agent đang giữ S1 trên A1 | df_device_claim(A2) | df.precondition_failed |
| TC-DF-T-10-005-05 | Edge | 2 agent đồng thời claim device A1 trong cùng 100 ms | Race | Chỉ 1 thành công; agent còn lại df.conflict; không sinh 2 record mcp_sessions cùng device active |
| TC-DF-T-10-005-06 | Edge | Token cấp S1 bị revoke trong khi agent đang chạy tool call | Quan sát | S1 tự đóng < 10 s; tool call mới df.unauthorized; record mcp_sessions có terminal_reason "token_revoked" |
| TC-DF-T-10-005-07 | Negative | Agent A claim, agent B cố call tool với S1 (cross-session bypass) | df_tap(session_id=S1) từ token B | df.permission_denied + audit log cross-agent attempt (FR-10-20) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-001, DF-T-10-002, DF-T-10-003.

**Chặn:** DF-T-10-006, DF-T-10-007, DF-T-10-008, DF-T-10-011.

**Phụ thuộc giữa Epic:**

- **DF-E-02** — reservation FSM, session lifecycle route.
- **DF-E-01** — token revoke hook.

**Rủi ro:**

- **Race condition 2 agent claim cùng device:** lock mềm + retry; gap đã ghi nhận, theo dõi qua KPI "số sự cố bypass ownership = 0".
- **Session "lơ lửng" khi agent crash không gọi end:** có job dọn session quá hạn (ví dụ idle > 30 phút) đưa về terminal_reason "timeout".
- **Token plaintext trong audit:** chỉ ghi token_id hash (đã giải quyết ở DF-T-10-003).

**Phụ thuộc bên ngoài:** Reservation service DF-E-02.

## 10. Điều kiện hoàn thành

- [ ] Code merged + pass CI.
- [ ] Coverage ≥ 80%.
- [ ] Test case TC-DF-T-10-005-* map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật mô hình L3 + cảnh báo gap concurrency.
- [ ] Telemetry: gauge active sessions, counter claim_attempt by status.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner Epic-02.
- [ ] Release notes ghi tool mới (Preview).
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**
- [ ] Đã test race condition với 10 agent đồng thời.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §5.1, §5.4 + FR-10-06, FR-10-07, FR-10-13, FR-10-20](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — reservation FSM.
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Fleet Operator.
- **Thuật ngữ:** MCP session, Reservation, Device session.
