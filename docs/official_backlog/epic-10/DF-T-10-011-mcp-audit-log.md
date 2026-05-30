# DF-T-10-011 — MCP audit log (mọi tool call persist)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-011 |
| **Title** | MCP audit log — persist mọi tool call, supervisor review, evidence chain |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:db`, `type:feature`, `risk:data-loss`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-10-09, FR-10-11, FR-10-12, FR-10-20 |
| **Truy vết — UC refs** | UC-10-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Audit log là rào chắn quan trọng nhất khi đưa AI agent vào vận hành thực. Nếu không ghi mọi tool call, không có cách review hành vi agent sau session, không có cách giải thích "agent đã làm gì lúc 2h sáng" — và agent về bản chất trở thành hộp đen. Module 10 đặt KPI tỷ lệ MCP action ghi audit = 100% (loại trừ tool đọc thuần được khai báo).

Persona chính: **AI Operations Supervisor (Preview)** review log để hiểu chuỗi quyết định agent (UC-10-08). Đây cũng là dữ liệu nguồn cho handoff flow (FR-10-12) — supervisor cần biết tool call gần nhất khi takeover.

> **Cảnh báo Preview:** Audit log đi kèm phần mở rộng nghiên cứu. Schema log có thể mở rộng giữa các release. Tuy nhiên cam kết: KHÔNG xóa bản ghi log đã ghi, chỉ thêm field mới.

Ưu tiên P1 — bắt buộc cho mọi tool call.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** truy vấn audit log theo session_id, agent_id, time_range, tool_name
> **Để** review chuỗi quyết định của agent sau session và có evidence trả lời câu hỏi "ai đã làm gì lúc nào".

## 4. Yêu cầu chức năng

- Hệ thống PHẢI persist mọi tool call vào bảng `mcp_audit_log` với schema: `id`, `session_id`, `agent_id`, `token_id_hash`, `org_id`, `tool_name`, `input` (redacted nếu có credential), `output_summary`, `result_code` (`success`/`error_code`), `started_at`, `ended_at`, `latency_ms` — trace FR-10-09.
- Audit log PHẢI capture cả attempt fail (vi phạm ownership, scope mismatch, rate limit) — trace FR-10-20.
- Audit log PHẢI append-only — không cho update / delete sau khi ghi — trace FR-10-09.
- Hệ thống PHẢI cung cấp API query log theo filter (session/agent/time/tool) — trace UC-10-08.
- Hệ thống PHẢI emit metric: tổng tool call, error rate, latency p50/p95/p99 — trace FR-10-09.
- Hệ thống PHẢI có retention policy cấu hình được (mặc định 90 ngày, archive cold storage sau đó) — trace risk module 10 "activity log có thể rất lớn".
- Hệ thống PHẢI gắn evidence chain: với tool có require_evidence (FR-10-11), audit entry phải link tới artifact ref — trace FR-10-11.
- Hệ thống PHẢI emit event "handoff requested" khi tool df_request_handoff được gọi (đặt hook cho UX handoff sau) — trace FR-10-12.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Mọi tool call thành công đều có audit entry**

```
Given agent thực hiện 100 tool call thành công trong 1 session
When supervisor query mcp_audit_log theo session_id
Then trả về đủ 100 entry kèm input, output_summary, latency_ms
And ≥ 99% có ghi (cho phép skip với read-only tool đã khai báo)
```

**AC-2: Tool call fail cũng được ghi**

```
Given agent gọi df_campaign_create với token device-scoped (fail scope)
When supervisor query log filter agent_id + result_code != success
Then có entry với result_code="df.permission_denied"
And input bị redact các field nhạy cảm
```

**AC-3: Append-only enforce**

```
Given audit log entry e1 đã ghi
When supervisor (hoặc bất kỳ ai) cố UPDATE/DELETE entry e1
Then thao tác bị reject ở DB-level (constraint trigger / role permission)
And log security warning
```

**AC-4: Evidence chain cho tool require_evidence**

```
Given tool df_save_extraction có evidence_required=true
When agent gọi và pass artifact_refs=["art-1","art-2"]
Then audit entry có link tới art-1, art-2
When supervisor mở entry trong dashboard
Then có thể click thẳng tới artifact preview
```

**AC-5: Retention archive**

```
Given retention policy 90 ngày
When job retention chạy hằng ngày
Then entry > 90 ngày được archive sang cold storage (hoặc xóa nếu cấu hình rõ)
And query log theo time_range cũ trả kết quả từ cold storage (có thể chậm hơn)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI dashboard audit chuyên dụng — DF-E-11 ticket admin/audit dashboard.
- KHÔNG bao gồm SIEM integration — lộ trình.
- KHÔNG bao gồm tamper-proof crypto chain (vd Merkle tree) — append-only cấp DB là đủ ở Preview; tamper-proof là open question.
- KHÔNG bao gồm export PDF báo cáo — manual export CSV ở phase này.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Middleware audit log mọi tool call (success + fail).
- [ ] Redact field nhạy cảm (token, password, cookie nếu lỡ payload chứa).
- [ ] API query log với filter.
- [ ] Emit metric prometheus.
- [ ] Hook event "handoff requested".

**Database / Migration** (`layer:db`)

- [ ] Bảng `mcp_audit_log` với constraint append-only (role permission + trigger).
- [ ] Index: (session_id), (agent_id, started_at), (org_id, started_at), (tool_name, result_code).
- [ ] Bảng cold storage / archive policy.

**Contract / API** (`layer:contract`)

- [ ] Endpoint query audit log (admin-only).
- [ ] Schema entry.

**Infra / DevOps** (`layer:infra`)

- [ ] Cron retention job.
- [ ] Storage capacity monitoring.

**Documentation** (`layer:docs`)

- [ ] Doc schema + retention.
- [ ] Doc warning Preview + cam kết append-only.

**Test** (`layer:test`)

- [ ] Test ghi đủ cho 100 tool call mix success/fail.
- [ ] Test append-only enforce (UPDATE/DELETE fail).
- [ ] Test redaction.
- [ ] Test retention job.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-011-01 | Positive | 100 tool call mix | Query log session_id | 100 entry đầy đủ |
| TC-DF-T-10-011-02 | Positive | Tool save_extraction với artifact_refs | Query entry | Có link artifact_ref |
| TC-DF-T-10-011-03 | Negative | Cố UPDATE entry trực tiếp qua SQL admin | Run UPDATE | Reject + log security warning |
| TC-DF-T-10-011-04 | Negative | Payload chứa "password":"xxx" lọt qua | Query entry | Field bị redact thành "[REDACTED]" |
| TC-DF-T-10-011-05 | Edge | 10,000 tool call trong 1 phút | Stress | Không drop entry; latency p95 < 200 ms ghi log |
| TC-DF-T-10-011-06 | Positive | Entry > 90 ngày | Query | Trả về từ cold storage, có flag "from_archive" |
| TC-DF-T-10-011-07 | Negative | Tool gọi từ token revoke | Quan sát | Vẫn ghi audit entry với result_code df.unauthorized |
| TC-DF-T-10-011-08 | Positive | Tool df_request_handoff được gọi | Quan sát event bus | Event "handoff_requested" emit kèm session_id |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-003 (token id để gắn log), DF-T-10-005 (session id).

**Chặn:** DF-T-10-014 (banner / dashboard cần đọc log).

**Phụ thuộc giữa Epic:**

- **DF-E-09 (Notifications & Analytics)** — pattern activity log; reuse infrastructure.
- **DF-E-06** — link artifact_ref.

**Rủi ro:**

- **Log mất do crash backend giữa tool call:** ghi audit ngay khi nhận tool call (start) + cập nhật khi kết thúc; nếu crash giữa chừng có entry với result_code "incomplete".
- **Log quá lớn:** retention + archive + storage monitoring; alert khi bảng > ngưỡng.
- **Leak credential vào log:** redaction + grep test CI.
- **Tamper:** append-only DB-level + role permission chặt.

**Phụ thuộc bên ngoài:** Postgres role permission + trigger.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case TC-DF-T-10-011-* map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter audit_writes, gauge audit_table_size, latency histogram.
- [ ] Code review ≥ 1 approve + security reviewer.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**
- [ ] Đã test stress 10k tool call / phút giữ entry không mất.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md FR-10-09, FR-10-11, FR-10-12, FR-10-20 + §8](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview).
- **Thuật ngữ:** Activity log, MCP session, Artifact.
