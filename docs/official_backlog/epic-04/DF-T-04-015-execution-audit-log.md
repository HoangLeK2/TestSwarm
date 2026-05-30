# DF-T-04-015 — Execution audit log

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-015 |
| **Title** | Execution audit log (immutable trail of admin actions + state changes) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:db`, `type:feature`, `risk:legal-compliance` |
| **Truy vết — FR refs** | FR-04-09 (log effective_config), FR-04-19 |
| **Truy vết — UC refs** | UC-04-08, UC-04-12, UC-04-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module KPI mục 9: "Tỷ lệ campaign có effective config được log đầy đủ cho mỗi step = 100%" — "yêu cầu nghiệp vụ để audit và debug". Đây là requirement compliance B2B: khách hàng B2B sau khi nhận báo cáo có thể yêu cầu "show me effective config bạn đã dùng".

Ticket này tạo bảng audit immutable: mọi mutation campaign (create/update/cancel/archive), mọi transition execution (running/completed/failed/dlq), mọi tác động admin (force-transition, DLQ retry/close), và effective_config snapshot per step.

P1 vì compliance, không block core dispatch nhưng phải có trước khi go-to-market B2B.

## 3. Câu chuyện người dùng

> **Là** owner module (compliance check) / Social Data Operator (báo cáo khách hàng)
> **Tôi muốn** mọi tác động lên campaign và execution được ghi lại immutable với timestamp, actor, before/after
> **Để** trả lời được "ai đã làm gì lúc nào với scenario nào và config gì"

## 4. Yêu cầu chức năng

- Hệ thống PHẢI ghi audit entry cho mọi mutation: campaign created/updated/status_changed/cancelled/archived; execution state transition; DLQ retry/close; account binding; force-transition.
- Audit entry PHẢI có: `id`, `organization_id`, `entity_type` (campaign/execution/dlq), `entity_id`, `action`, `actor` (user_id or system), `actor_ip` (nếu user), `before_state` (JSON), `after_state` (JSON), `reason`, `occurred_at`, `event_id` (link tới DF-T-04-013 event).
- Hệ thống PHẢI ghi `effective_config` snapshot mỗi step thành công (KPI 100%) vào audit (hoặc reference từ execution_steps là đủ — chọn 1).
- Audit log PHẢI immutable: không UPDATE, không DELETE (trừ retention policy với super-admin justification).
- Hệ thống PHẢI cho phép query: `GET /audit?entity_type=campaign&entity_id=C1`, `GET /audit?actor=U1&from=&to=`.
- Hệ thống PHẢI redact sensitive data: account credentials không vào audit, IP của user phải qua org policy (mask).
- Hệ thống PHẢI có retention policy ≥ 365 ngày (default), config per org.
- Hệ thống NÊN export audit log dạng CSV/JSON cho compliance request.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Audit khi campaign created**

```
Given user U1 OrgA tạo campaign C
When POST /campaigns
Then audit entry { action: "campaign.created", actor: U1, entity: campaign:C, after_state: {...} } được insert
And entry không thể UPDATE/DELETE
```

**AC-2: Audit cancel với reason**

```
Given user U2 cancel campaign C
When POST /campaigns/C/cancel reason="emergency"
Then audit entry action="campaign.cancelled", reason="emergency", before_state.status="running", after_state.status="cancelled"
```

**AC-3: Effective config log per step (KPI 100%)**

```
Given execution E 5 step
When run
Then mỗi step success có effective_config logged (trong execution_steps hoặc audit)
And query /audit?entity_id=E trả về 5 entry step có effective_config field
```

**AC-4: Immutable**

```
Given audit entry A1
When admin cố UPDATE A1 via direct SQL
Then trigger / app guard reject; nếu pass → CI alert
```

**AC-5: Redact credential**

```
Given account A có credential
When audit log binding action
Then entry không chứa credential, chỉ account_id
```

**AC-6: Cross-org isolation**

```
Given audit entry thuộc OrgA
When OrgB user GET /audit
Then chỉ thấy entry OrgB, không leak OrgA
```

**AC-7: Export compliance**

```
Given org muốn export audit 30 ngày
When POST /audit/export body { entity_type: "campaign", from, to, format: "csv" }
Then trả file CSV với tất cả entry trong range
And action logged (export là audit-able)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm SIEM integration — DF-E-09.
- KHÔNG bao gồm AI summarization audit — out of scope.
- KHÔNG bao gồm compliance report template — operator viết manual.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] AuditLogger service với typed action enum.
- [ ] Wire vào mọi mutation point (campaign service, execution FSM, DLQ service).
- [ ] Subscribe DF-T-04-013 event để auto-log state change (alt to direct wire).
- [ ] Export endpoint.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho query + export.
- [ ] Schema audit entry.

**Database / Migration** (`layer:db`)

- [ ] Bảng `audit_log` với partition by month (Postgres declarative partition).
- [ ] Trigger chống UPDATE/DELETE (chỉ super-admin via direct).
- [ ] Index `(organization_id, entity_type, entity_id, occurred_at DESC)`.

**Documentation** (`layer:docs`)

- [ ] Catalogue audit action types.
- [ ] Doc retention policy.

**Test** (`layer:test`)

- [ ] Unit test logger per action type.
- [ ] Test immutability.
- [ ] Test redaction.
- [ ] Test cross-org isolation.
- [ ] Test KPI 100% effective_config log.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-015-01 | Positive | User U1 tạo campaign | POST /campaigns | Audit entry created, immutable |
| TC-DF-T-04-015-02 | Positive | Execution E 5 step thành công | Run | 5 effective_config log entry truy được |
| TC-DF-T-04-015-03 | Negative | Cố direct SQL UPDATE audit_log | UPDATE | Trigger reject hoặc app guard reject |
| TC-DF-T-04-015-04 | Negative | OrgB user GET audit của OrgA | Query | Không leak, return empty |
| TC-DF-T-04-015-05 | Edge | Cancel campaign với reason | Cancel | before/after state lưu đầy đủ, reason không trống |
| TC-DF-T-04-015-06 | Edge | Audit entry chứa account credential? | Inspect | Credential không có, chỉ account_id |
| TC-DF-T-04-015-07 | Positive | Export 30 ngày audit CSV | POST /audit/export | File CSV trả về, export action cũng log |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-007, DF-T-04-010, DF-T-04-012, DF-T-04-013 (event source).

**Chặn:** Compliance audit B2B.

**Rủi ro:**

- **Audit bảng phình to:** partition + retention; cold storage cho > 1 năm.
- **Effective_config log quá lớn:** chỉ log những key thay đổi so với scenario default; full snapshot first step.
- **Performance overhead:** logger async, không block hot path.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Immutability + redaction test pass.
- [ ] KPI test 100% effective_config log pass.
- [ ] Doc retention + audit action catalogue published.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-09 (log requirement), FR-04-19, mục 9 KPI.
- **Thuật ngữ:** Effective config.
