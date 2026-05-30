# DF-T-10-007 — Tool `df_campaign_run` / `df_run_scenario` — dispatch & status

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-007 |
| **Title** | Tool `df_campaign_run` + `df_run_scenario` — dispatch campaign / scenario và đọc status |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `persona:ai-ops`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-10-02, FR-10-05, FR-10-08, FR-10-16, FR-10-17, FR-10-18 |
| **Truy vết — UC refs** | UC-10-06 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

`df_campaign_create` chỉ tạo draft; muốn chạy thật cần `df_campaign_run`. Đồng thời nhiều use case agent (UC-10-06) chỉ cần chạy một scenario trên device đã claim, không cần campaign — đó là tool `df_run_scenario`. Ticket gom hai tool này lại vì cả hai cùng wrap luồng dispatch + status, chia sẻ contract output (execution id, status poll, terminal state).

Persona chính là **AI Operations Supervisor (Preview)**; persona phụ là **Automation Builder** dùng tool để preview scenario qua agent.

> **Cảnh báo Preview:** Tool này dispatch lệnh chạy thật trên fleet — có khả năng tác động lớn (đăng bài, follow, ...). Khuyến nghị: prompt agent phải kèm guardrail rõ ràng và supervisor monitor live trong release Preview.

Ưu tiên P2 — quan trọng cho demo Preview nhưng không block foundation.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** agent gọi `df_campaign_run(campaign_id)` để dispatch campaign đã review, và gọi `df_run_scenario(scenario_id, session_id)` để chạy nhanh scenario trên session đang giữ
> **Để** agent vừa có thể vận hành campaign quy mô vừa có thể nhảy nhanh test trên một session đơn lẻ.

## 4. Yêu cầu chức năng

- Tool PHẢI yêu cầu MCP_AUTH_TOKEN — trace FR-10-05, FR-10-17, FR-10-18.
- `df_campaign_run` PHẢI accept `campaign_id` (đã tồn tại trạng thái draft); transition sang running; trả về `campaign_run_id` — trace FR-10-18.
- `df_run_scenario` PHẢI accept `scenario_id` + `session_id` (đã claim ở DF-T-10-005); trả `execution_id` — trace FR-10-17.
- Tool kèm `df_get_campaign_status` / `df_get_execution_status` để agent poll trạng thái — trace FR-10-16.
- Tool PHẢI tôn trọng ownership: chỉ run campaign / scenario thuộc org của token; chỉ run scenario trên session do chính agent giữ — trace FR-10-20.
- Tool PHẢI ghi audit log đầu vào, output, terminal state — trace FR-10-09.
- Tool NÊN hỗ trợ `dry_run = true` cho `df_run_scenario` để chạy preview không commit content/artifact — trace FR-10-17.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Dispatch campaign draft thành công**

```
Given campaign C1 ở trạng thái draft thuộc org của token
When agent gọi df_campaign_run(campaign_id=C1)
Then trả về campaign_run_id, status = running
And audit log có entry tool call
And campaign DF-E-04 chuyển sang running
```

**AC-2: Run scenario trên session đang giữ**

```
Given agent giữ session S1 trên device A1
And scenario SC1 thuộc org của token
When agent gọi df_run_scenario(scenario_id=SC1, session_id=S1)
Then trả về execution_id
And execution gắn với session S1 và device A1
```

**AC-3: Run scenario trên session do agent khác giữ bị chặn**

```
Given session S2 do agent B giữ
When agent A gọi df_run_scenario(scenario_id=SC1, session_id=S2)
Then df.permission_denied "session not owned by caller"
And audit log cross-agent attempt
```

**AC-4: Poll status**

```
Given execution E1 đang chạy
When agent gọi df_get_execution_status(E1) mỗi 3 s
Then trả về status từng giai đoạn (queued → running → completed/failed) chính xác
And khi terminal, response chứa terminal_reason và time spent
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm sửa scenario / campaign — read & dispatch only.
- KHÔNG bao gồm streaming status realtime — agent phải poll.
- KHÔNG bao gồm cancel campaign / execution qua MCP ở release này — open question.
- KHÔNG bao gồm schedule — DF-E-05.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Handler df_campaign_run wrap campaign-dispatch.
- [ ] Handler df_run_scenario wrap scenario-run.
- [ ] Handler df_get_campaign_status / df_get_execution_status.
- [ ] Ownership check session/campaign/scenario.
- [ ] dry_run mode forward tới scenario engine.

**Contract / API** (`layer:contract`)

- [ ] Registry entries + schema.
- [ ] http_route_ref tới DF-E-04.

**Documentation** (`layer:docs`)

- [ ] Doc + warning Preview + ví dụ flow.

**Test** (`layer:test`)

- [ ] Unit + integration test.
- [ ] Ownership negative test.
- [ ] dry_run test.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-007-01 | Positive | Campaign draft + token user-scoped | df_campaign_run | running, audit log |
| TC-DF-T-10-007-02 | Positive | Session S1 đang giữ + scenario SC1 | df_run_scenario(SC1, S1) | execution_id, audit log |
| TC-DF-T-10-007-03 | Negative | Session S2 do agent khác | df_run_scenario(SC1, S2) | df.permission_denied |
| TC-DF-T-10-007-04 | Negative | Campaign đã running, run lần 2 | df_campaign_run | df.conflict "campaign already running" |
| TC-DF-T-10-007-05 | Edge | Execution đang chạy nhưng device drop network | Poll status | Status reflect "running" → terminal "failed_device_disconnect" |
| TC-DF-T-10-007-06 | Positive | dry_run=true | df_run_scenario dry | Execution chạy nhưng không commit content/artifact |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-005, DF-T-10-006.

**Chặn:** Không trực tiếp; gián tiếp cho DF-T-10-014 (banner đề cập tool tạo tài nguyên).

**Phụ thuộc giữa Epic:** DF-E-04 (campaign + scenario dispatch).

**Rủi ro:**

- **Agent dispatch campaign lớn bất ngờ:** rate-limit DF-T-10-012 + quota.
- **Race: agent run scenario trong khi campaign đang chạy trên cùng device:** ownership session enforce + DF-E-04 đã có lock device-level.
- **Polling thưa làm agent loop không kết thúc:** doc khuyến nghị tần suất poll + supervisor timeout.

**Phụ thuộc bên ngoài:** Scenario engine DF-E-04.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter dispatch_by_mcp, latency dispatch→running.
- [ ] Code review ≥ 1 approve + owner Epic-04 approve.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-16, FR-10-17, FR-10-18](../../official_docs/modules/10-mcp-agent-tools.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview), Automation Builder.
- **Thuật ngữ:** Campaign, Scenario, Execution, MCP session.
