# DF-T-10-012 — Rate-limit & quota cho AI agent

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-012 |
| **Title** | Rate-limit & quota cho MCP tool call — bảo vệ fleet khỏi agent loop |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `type:feature`, `risk:performance`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-10-02, FR-10-04, FR-10-05 |
| **Truy vết — UC refs** | UC-10-02, UC-10-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

AI agent có khả năng vô tình loop: gọi cùng tool nghìn lần trong vài giây (do prompt sai, do tự retry vô hạn). Không có rate-limit, agent có thể làm sập HTTP API hoặc tốn cost provider AI. Đây là rủi ro vận hành đặc thù khi đưa agent vào fleet (khác với rate-limit cho người vận hành — người không loop nhanh như vậy).

Persona chính: **AI Operations Supervisor (Preview)** muốn rào chắn để không phải lo agent "cháy" hệ thống. KPI module 10: tool call vi phạm rate-limit / tổng tool call < 1%.

> **Cảnh báo Preview:** Rate-limit baseline có thể chưa tối ưu trong release Preview. Ngưỡng có thể chỉnh giữa các release dựa trên dữ liệu thực.

Ưu tiên P2.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** rate-limit + quota áp lên mỗi token MCP để khi agent loop sai, hệ thống tự throttle thay vì sập
> **Để** tôi yên tâm cấp token cho agent thử nghiệm mà không phải canh từng giây.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI áp rate-limit per-token per-tool theo bucket time window (vd 60 call/phút mỗi tool gesture, 10 call/phút tool campaign) — trace FR-10-04, FR-10-05.
- Hệ thống PHẢI áp quota daily / monthly per-org để bảo vệ tài nguyên tổng — trace `risk:performance` module 10.
- Khi vi phạm, trả error `df.rate_limited` với `retry_after_ms` — trace contract DF-T-10-013.
- Cấu hình rate-limit PHẢI cấu hình được per-tool và per-token-type (không hard-code) — trace FR-10-02.
- Hệ thống PHẢI emit metric `mcp_rate_limit_block_total` theo tool + token + tool_name — trace FR-10-09.
- Hệ thống NÊN có cảnh báo proactive cho supervisor khi 1 token chạm 80% quota.
- Hệ thống PHẢI có circuit breaker: nếu 1 token gây > 50 lỗi df.* trong 1 phút → tạm suspend token 5 phút.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Rate-limit per tool**

```
Given giới hạn 60 call/phút cho df_tap với token T
When agent gọi df_tap 61 lần trong 60 giây
Then call thứ 61 trả df.rate_limited với retry_after_ms
And metric block_total tăng
And audit log có entry block (DF-T-10-011)
```

**AC-2: Quota daily per org**

```
Given org X có quota 10000 tool call/ngày
When org tổng đã chạm 10000 trong ngày
Then call mới trả df.quota_exceeded với reset_at
And supervisor đã được cảnh báo khi chạm 80% (8000)
```

**AC-3: Circuit breaker khi nhiều lỗi**

```
Given token T sinh 60 lỗi df.invalid_argument trong 60 giây
When agent gọi tool tiếp theo
Then trả df.token_suspended trong 5 phút
And metric circuit_breaker_trip tăng
And alert supervisor
```

**AC-4: Cấu hình rate-limit không cần redeploy**

```
Given admin cập nhật config rate-limit df_tap = 120/phút qua admin endpoint
When MCP server reload config (hoặc TTL hết)
Then giới hạn mới được áp trong < 60 s
And không cần restart MCP server
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm rate-limit phía AI provider (Claude, GPT) — đó là vấn đề provider, doc khuyến nghị supervisor monitor cả hai phía.
- KHÔNG bao gồm distributed rate-limit chính xác tuyệt đối (cluster nhiều node MCP) — ở Preview dùng counter Redis-based, chấp nhận small skew.
- KHÔNG bao gồm chargeback / billing.
- KHÔNG bao gồm UI cấu hình quota — admin endpoint API là đủ ở Preview.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Middleware rate-limit dùng Redis token bucket.
- [ ] Quota counter daily/monthly.
- [ ] Circuit breaker per-token.
- [ ] Admin endpoint cấu hình.
- [ ] Reload config TTL.

**Contract / API** (`layer:contract`)

- [ ] Mã lỗi df.rate_limited, df.quota_exceeded, df.token_suspended.
- [ ] Header retry_after_ms.

**Documentation** (`layer:docs`)

- [ ] Doc default rate-limit + cách điều chỉnh.
- [ ] Warning Preview.

**Test** (`layer:test`)

- [ ] Unit + integration test bucket.
- [ ] Test circuit breaker trip.
- [ ] Test reload config.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-012-01 | Positive | Limit 60/phút | Gọi 60 lần trong 50 s | Tất cả OK |
| TC-DF-T-10-012-02 | Positive | Limit 60/phút | Gọi 61 lần trong 50 s | Call 61 trả df.rate_limited |
| TC-DF-T-10-012-03 | Negative | Quota daily đạt 100% | Gọi tool | df.quota_exceeded với reset_at |
| TC-DF-T-10-012-04 | Negative | 60 lỗi invalid_argument | Gọi tiếp | df.token_suspended 5 phút |
| TC-DF-T-10-012-05 | Edge | Hết suspension 5 phút sau | Gọi tool | OK trở lại |
| TC-DF-T-10-012-06 | Positive | Admin update limit từ 60 → 120 | Reload | Trong < 60 s, gọi 120/phút OK |
| TC-DF-T-10-012-07 | Edge | Redis tạm thời down | Gọi tool | Fail-open hoặc fail-closed theo policy (mặc định fail-open với log warning) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-003 (token id để key bucket).

**Chặn:** DF-T-10-014 (banner đề cập quota).

**Phụ thuộc giữa Epic:** **DF-E-01** (Redis hạ tầng).

**Rủi ro:**

- **Limit quá chặt làm agent không chạy được:** baseline rộng + tinh chỉnh qua dữ liệu thật.
- **Limit quá lỏng làm agent loop sập hệ thống:** circuit breaker là rào chắn cuối.
- **Redis down:** fail-open có rủi ro overload; doc khuyến nghị deploy Redis HA.

**Phụ thuộc bên ngoài:** Redis.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map sang automation.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: counter rate_limit_block, gauge quota_used_percent.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes Preview.
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §8 risk + KPI rate-limit](../../official_docs/modules/10-mcp-agent-tools.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview).
- **Thuật ngữ:** MCP, Activity log.
