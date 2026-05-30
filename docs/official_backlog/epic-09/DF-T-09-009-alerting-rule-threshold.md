# DF-T-09-009 — Alerting rule engine (threshold-based) + escalation policy + routing per persona

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-09-009 |
| **Title** | Alerting rule engine — threshold-based rule, escalation policy, alert routing per persona, on-call schedule integration (read-only) |
| **Type** | `type:feature` |
| **Epic** | DF-E-09 — Notifications & Analytics |
| **Module** | DF-MOD-09 — Notifications & Analytics |
| **Priority** | P3 |
| **Story Points** | 8 |
| **Status** | Ready |
| **Labels** | `module:notif-analytics`, `layer:backend`, `layer:contract`, `type:feature`, `risk:performance`, `persona:fleet-operator`, `persona:ai-ops`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-09-03, FR-09-07 (Lộ trình → Active alerting) |
| **Truy vết — UC refs** | UC-09-06, UC-09-07, UC-09-08, UC-09-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 ghi rõ: "Chưa có alerting proactive theo pattern. Module này phản ứng theo từng event riêng lẻ; sản phẩm chưa có rule engine để định nghĩa cảnh báo kiểu 'khi tỷ lệ DLQ trên một scenario vượt 20% trong 1 giờ, gửi alert'." Đây là hạng mục Lộ trình mà DF-E-09 đẩy lên **Active P0** vì là điều kiện vận hành critical — không có nó, sự cố pattern (DLQ burst, device chết hàng loạt, account ban dồn dập) chỉ được phát hiện khi operator F5 dashboard hoặc khi khách hàng kêu.

Ticket này dựng **rule engine threshold-based**: admin định nghĩa rule với điều kiện (metric, comparator, threshold, window), khi điều kiện đáp ứng thì raise alert qua channel cấu hình, route đúng persona, có escalation nếu không ack trong N phút. Đồng thời ticket dựng **on-call schedule integration (read-only)** — đọc lịch on-call từ một nguồn (manifest file, PagerDuty API, hoặc bảng nội bộ) để route alert đến đúng người trực.

Persona hưởng lợi: **Fleet Operator** (alert device fail burst), **AI Ops Supervisor** (alert MCP action vượt ngưỡng), **Platform Engineer** (alert relay agent rớt heartbeat), **Operator vận hành đêm** (escalation khi ngủ).

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** định nghĩa rule "khi > 5 device offline trong 10 phút thì alert" và alert route đến người on-call hiện tại
> **Để** sự cố cụm thiết bị được phát hiện trong 10 phút thay vì sáng hôm sau

Persona phụ: **AI Ops Supervisor** (rule "MCP agent vượt 100 action/giờ alert ngay"), **Platform Engineer** (rule "relay heartbeat miss > 30s alert").

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép admin định nghĩa alert rule với: name, metric (rollup metric name), comparator (gt/lt/eq/ne), threshold, window (5min / 1h / 24h), severity (info/warning/critical) — trace FR-09-03 mở rộng.
- Hệ thống PHẢI evaluate rule mỗi phút trên rollup mới nhất (hoặc query window từ activity_log nếu rollup chưa có) — Lộ trình → Active.
- Khi rule fire, hệ thống PHẢI tạo alert record + emit qua `notification_service` với severity prefix trong title.
- Hệ thống PHẢI hỗ trợ alert routing per persona: rule khai báo `target_personas` (vd `["fleet-operator"]`); chỉ user có persona đó nhận in-app + qua channel cá nhân.
- Hệ thống PHẢI có escalation policy: nếu alert critical không ack trong N phút (default 15), escalate lên user level cao hơn theo on-call schedule.
- Hệ thống PHẢI đọc on-call schedule read-only từ một trong các nguồn: bảng nội bộ `on_call_schedule` (default), manifest file YAML, hoặc external API (PagerDuty placeholder).
- Hệ thống PHẢI có endpoint ack alert: `POST /api/alerts/{id}/ack`; alert đã ack không escalate.
- Hệ thống PHẢI có timeout query rule eval: hard cap 30s/rule; rule chậm bị skip + log warning.
- Hệ thống NÊN cho phép rule kết hợp 2-3 metric với AND/OR (tùy chọn v1; có thể defer v2).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Rule fire khi threshold vượt**

```
Given admin tạo rule "device_offline_burst": metric=device.offline.count, comparator=gt, threshold=5, window=10min, severity=critical, target_personas=["fleet-operator"]
And trong 10 phút qua, 7 device đi offline
When rule engine eval mỗi phút
Then alert record tạo với severity=critical
And notification_service emit cho mọi user có persona fleet-operator trong org
And in-app, channel email/Slack nhận alert có prefix [CRITICAL]
And activity_log entry "alert.fired" append
```

**AC-2: Escalation khi không ack**

```
Given alert critical đã fire 15 phút trước, chưa user nào ack
And on-call schedule cho biết user U1 đang trực, U2 là backup
When escalation policy chạy
Then notification thứ 2 emit cho U2 với prefix [ESCALATED]
And alert record cập nhật `escalated_at`, `escalated_to=U2`
And nếu vẫn không ack thêm 15 phút → escalate lên level cao hơn (nếu có)
```

**AC-3: Ack dừng escalation**

```
Given alert critical fire, đang đợi escalation
When user U gọi POST /api/alerts/{id}/ack với reason "đang điều tra"
Then alert.status = "acked"; ack_by=U, ack_at=now, ack_reason="đang điều tra"
And escalation policy dừng cho alert này
And activity_log "alert.acked" append
```

**AC-4: Routing chỉ tới persona target**

```
Given rule "mcp_action_burst" target_personas=["ai-ops"]
And org có user A (fleet-operator) và user B (ai-ops)
When rule fire
Then user B nhận notification + channel
And user A KHÔNG nhận
And nếu org không có user nào có persona ai-ops → alert vẫn tạo, log warning "no_recipient_for_persona", fallback gửi cho admin org
```

**AC-5: Rule eval chậm bị skip**

```
Given rule R có query metric phức tạp, eval mất 40s
When rule engine eval R (timeout 30s)
Then R bị skip lần này; log warning "rule_eval_timeout rule=R duration=30s"
And không block các rule khác eval
And metric `rule_eval_timeout_total` tăng
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm suppression / digest khi alert burst — sẽ ở DF-T-09-010.
- KHÔNG bao gồm UI quản trị rule — DF-E-11 frontend (API ready trong Epic này).
- KHÔNG bao gồm anomaly detection ML-based — backlog tương lai.
- KHÔNG bao gồm write on-call schedule (chỉ read trong v1) — backlog tương lai.
- KHÔNG bao gồm integration deep với PagerDuty (chỉ stub interface).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Implement rule data model: alert_rules (id, org_id, name, metric, comparator, threshold, window, severity, target_personas, escalation_minutes, enabled)
- [ ] Implement `rule_evaluator` chạy mỗi phút, query rollup hoặc activity_log
- [ ] Implement `alert_dispatcher` tạo alert record + emit notification
- [ ] Implement `escalation_worker` chạy mỗi phút check alert chưa ack
- [ ] Implement `on_call_schedule_reader` (3 source: db / yaml / external API stub)
- [ ] Implement endpoint CRUD alert_rules, GET/POST alerts, POST ack
- [ ] Timeout guard 30s/rule

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho rule CRUD, alert query, ack
- [ ] Schema on_call_schedule entry

**Database / Migration** (`layer:db`)

- [ ] Bảng `alert_rules`, `alerts`, `on_call_schedule`
- [ ] Index (org_id, enabled, severity), (alert_id, escalated_at)

**Documentation** (`layer:docs`)

- [ ] Catalog rule pattern khuyến nghị: DLQ rate, device offline burst, MCP action burst, account ban burst, schedule run fail rate
- [ ] Hướng dẫn admin tạo rule và set escalation

**Test** (`layer:test`)

- [ ] Unit test rule_evaluator, threshold compare
- [ ] Integration test full flow: insert metric → rule fire → notification emit → ack
- [ ] Test escalation timer
- [ ] Test rule eval timeout 30s
- [ ] Test routing per persona, fallback admin

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-09-009-01 | Positive | Rule device_offline > 5 in 10min, 7 device offline | Eval rule | Alert critical fire; notification gửi đúng persona; activity_log append |
| TC-DF-T-09-009-02 | Positive | Alert critical 15min chưa ack, U1 on-call, U2 backup | Escalation chạy | U2 nhận notification ESCALATED; alert.escalated_to=U2 |
| TC-DF-T-09-009-03 | Positive | User U ack alert | POST /alerts/{id}/ack | Status=acked; escalation dừng; activity_log "alert.acked" |
| TC-DF-T-09-009-04 | Negative | Rule với metric không tồn tại | Eval | Rule skip, log error METRIC_NOT_FOUND; rule auto-disable nếu lặp 5 lần |
| TC-DF-T-09-009-05 | Negative | Org không có user persona target | Rule fire | Alert tạo; log warning no_recipient_for_persona; fallback admin org |
| TC-DF-T-09-009-06 | Edge | Rule eval mất 40s | Eval | Skip; log warning timeout; metric tăng |
| TC-DF-T-09-009-07 | Edge | Alert đã ack rồi nhưng escalation chạy lại | Escalation eval | Không gửi escalated notification (idempotent) |
| TC-DF-T-09-009-08 | Edge | 100 rule cùng eval mỗi phút | Stress test | Tổng eval < 60s; không miss cycle; không OOM |
| TC-DF-T-09-009-09 | Edge | On-call schedule rỗng (không ai trực) | Rule fire | Alert tạo; log warning no_on_call; fallback gửi cho admin org |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-09-001 (notification_service), DF-T-09-002 (rule engine cho channel routing), DF-T-09-007 (rollup table).

**Chặn:** DF-T-09-010 (suppression cần rule fire làm input).

**Phụ thuộc giữa Epic:**

- **DF-E-01** — persona attribute trên user model, on-call schedule có thể tích hợp role.
- **DF-E-02 (Devices), DF-E-04 (Campaign), DF-E-10 (MCP)** — nguồn metric để rule eval.

**Rủi ro:**

- **Rule fire dồn dập gây ngợp notification** → giảm thiểu: DF-T-09-010 suppression làm sau; trong ticket này có rate limit per rule (max 1 alert/rule/5min).
- **Escalation sai người (on-call schedule lỗi thời)** → giảm thiểu: validate schedule khi load; alert admin nếu schedule cũ > 24h.
- **Rule definition phức tạp khiến eval chậm** → giảm thiểu: timeout 30s, auto-disable rule lỗi liên tiếp.
- **Race condition khi 2 instance rule engine cùng chạy** → giảm thiểu: leader election (Redis lock); chỉ 1 instance eval mỗi cycle.

**Phụ thuộc bên ngoài:** Redis lock, scheduler infra.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit test coverage ≥ 80%.
- [ ] Integration test full flow (rule fire → notification → ack → escalation) pass.
- [ ] Stress test 100 rule pass.
- [ ] Migration tạo 3 bảng chạy trên staging.
- [ ] Catalog rule khuyến nghị committed (≥ 8 rule cho 5 module).
- [ ] Telemetry: `alert_fired_total{rule, severity}`, `alert_escalated_total`, `rule_eval_duration_seconds`, `rule_eval_timeout_total`.
- [ ] Code review ≥ 2 approve (owner module + 1 senior).
- [ ] Đã chạy trên staging 7 ngày, ≥ 1 alert fire thực + ack thành công.
- [ ] Changelog "Alert rule engine v1 — threshold + escalation + on-call routing".

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [09-notifications-and-analytics.md §7 Lộ trình "Alerting proactive theo pattern"](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Fleet Operator (§3.3), AI Operations Supervisor (§3.5), Platform Engineer (§3.4).
- **Thuật ngữ:** [Alert](../../official_docs/00-glossary.md), [DLQ](../../official_docs/00-glossary.md), [Domain event](../../official_docs/00-glossary.md).
- **Ticket liên quan:** DF-T-09-001, DF-T-09-002, DF-T-09-007, DF-T-09-010.
