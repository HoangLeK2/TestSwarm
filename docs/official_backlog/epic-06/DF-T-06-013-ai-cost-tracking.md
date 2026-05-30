# DF-T-06-013 — AI vision cost tracking & budget guardrail

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-013 |
| **Title** | AI vision cost tracking & budget guardrail |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2`, `risk:performance` |
| **Truy vết — FR refs** | FR-06-15, FR-06-03 |
| **Truy vết — UC refs** | UC-06-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module §8: "Chi phí AI vision có thể tăng nhanh nếu không có guardrail ngân sách. Một campaign chạy diện rộng dùng AI vision cho mọi step extraction có thể đốt ngân sách nhanh chóng." Tài liệu yêu cầu báo cáo chi phí theo ngày/tuần/tháng và cảnh báo khi vượt ngưỡng (FR-06-15). Đây là điểm khác biệt giữa AI vision dùng "tỉnh táo" và "không kiểm soát".

Ticket này dựng:
1. Cost tracker — tiêu thụ event `ai_vision_call_completed` (DF-T-06-005), tổng hợp theo (org, user, scenario, day/week/month).
2. Budget guardrail — config ngưỡng per org (USD/tháng), soft warning ở 80%, hard block ở 100%.
3. API truy vấn cost.
4. Tích hợp DF-E-09 (Notification) để gửi cảnh báo.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** thấy chi phí AI vision đang dùng theo ngày/tuần/tháng và nhận cảnh báo trước khi vượt budget
> **Để** chủ động chuyển engine khi gần ngưỡng thay vì bị bill bất ngờ

Persona phụ: Automation Builder (theo dõi cost cho từng scenario), Platform Engineer (quản lý cost ở mức tổ chức).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI tiêu thụ event `ai_vision_call_completed` và tổng hợp vào bảng `ai_cost_records(id, organization_id, user_id, scenario_id, execution_id, provider, model, est_tokens_in, est_tokens_out, est_cost_usd, created_at)` — trace FR-06-15.
- Hệ thống PHẢI cung cấp endpoint:
  - `GET /api/organizations/{id}/ai-cost?from=&to=&group_by=day|week|month|scenario|user` trả tổng cost.
  - `GET /api/organizations/{id}/ai-cost/budget` trả config budget hiện tại + usage hiện tại.
  - `PUT /api/organizations/{id}/ai-cost/budget` set ngưỡng (USD/tháng, soft %, hard %, action).
- Hệ thống PHẢI có 2 ngưỡng:
  - **Soft (mặc định 80%)**: emit alert "ai_budget_soft" tới DF-E-09 Notification.
  - **Hard (mặc định 100%)**: emit alert "ai_budget_hard" + behavior tùy `action` ("block" — từ chối AI vision call mới với 402 Payment Required; "warn" — chỉ cảnh báo).
- Hệ thống PHẢI cập nhật pricing model định kỳ (cron weekly từ provider docs hoặc hard-coded với release note khi đổi).
- Hệ thống PHẢI có dashboard view "cost timeline" (cho DF-E-11).
- Hệ thống PHẢI cho phép user query top N scenario tốn nhất.
- Hệ thống NÊN cảnh báo theo platform: ví dụ ngưỡng riêng cho `fb_post` extraction.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Cost record được ghi sau AI vision call**

```
Given AI vision call hoàn tất với est_cost_usd=0.05
When event ai_vision_call_completed emit
Then bảng ai_cost_records có row mới với est_cost_usd=0.05
And group_by query month tăng 0.05
```

**AC-2: Soft alert ở 80%**

```
Given org X có budget 100 USD/tháng; đã dùng 80.5 USD
When AI vision call thành công và cost được ghi
Then alert "ai_budget_soft" được emit (qua DF-E-09)
And user nhận notification "AI budget tháng này: 80%"
And vẫn cho phép call tiếp
```

**AC-3: Hard block ở 100%**

```
Given org X budget 100 USD/tháng action="block"; đã dùng 100.01 USD
When user gọi AI vision call mới
Then call bị từ chối với 402 BUDGET_EXCEEDED
And response gợi ý "switch to hierarchy/ocr engine" và liên hệ admin
And metric `ai_budget_block_total` tăng
```

**AC-4: Top scenario tốn nhất**

```
Given org X có 50 scenario; scenario S1 đã tốn 30 USD trong tháng
When GET /api/organizations/{id}/ai-cost?group_by=scenario&limit=10
Then trả top 10 scenario theo cost desc; S1 ở top
And mỗi entry có scenario_id, name, cost, call_count
```

**AC-5: Budget reset đầu tháng**

```
Given budget tháng trước đã đạt hard limit
When sang tháng mới (1 day UTC)
Then usage reset = 0
And AI vision call resume bình thường
And event "ai_budget_reset" emit
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm dashboard UI (đó là DF-E-11).
- KHÔNG bao gồm chargeback per user (chỉ tracking, không bill user).
- KHÔNG bao gồm cost cho OCR (OCR là internal, ước lượng chi phí CPU không đáng kể).
- KHÔNG bao gồm cost cho hierarchy.
- KHÔNG bao gồm prepaid credit / topup (chỉ ngưỡng cảnh báo + block).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Service `AICostTracker` listen event và insert row.
- [ ] Service `AIBudgetGuard.check(organization_id)` trả `{within_soft, within_hard}`; gọi trước mỗi AI vision call.
- [ ] Aggregator query group_by (SQL với date_trunc).
- [ ] Pricing model module (hard-coded với version, có note khi update).
- [ ] Cron monthly reset.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 3 endpoint.
- [ ] Mã lỗi `BUDGET_EXCEEDED` (402).
- [ ] Event schema `ai_budget_soft`, `ai_budget_hard`, `ai_budget_reset`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `ai_cost_records`.
- [ ] Index (organization_id, created_at), (scenario_id, created_at).
- [ ] Bảng `ai_budget_config(organization_id PK, monthly_usd_limit, soft_pct, hard_pct, action, current_usage, last_reset_at)`.

**Documentation** (`layer:docs`)

- [ ] "AI budget management" runbook.
- [ ] Bảng pricing model hiện tại của OpenAI / Gemini.

**Test** (`layer:test`)

- [ ] Test ghi cost record sau AI call.
- [ ] Test soft alert trigger.
- [ ] Test hard block.
- [ ] Test reset đầu tháng.
- [ ] Test group_by query với dataset 10k record.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-013-01 | Positive | AI vision call thành công cost=0.05 | Event consumed | Row mới trong ai_cost_records; group_by month tăng 0.05 |
| TC-DF-T-06-013-02 | Positive | Budget 100 USD, usage 79 USD; call cost 1.5 USD | Trigger alert pipeline | Soft alert emit (80.5% > 80%); call cho phép |
| TC-DF-T-06-013-03 | Negative | Budget 100 USD action=block, usage 99.99 USD; call cost 1 USD | Gọi AI vision | Call bị block 402; cost không được ghi (call không thực hiện) |
| TC-DF-T-06-013-04 | Negative | Set budget với monthly_usd_limit=-10 | PUT settings | 422 INVALID_BUDGET |
| TC-DF-T-06-013-05 | Edge | Đầu tháng mới; usage tháng trước 200 USD | Cron reset | Usage reset 0; bảng config update last_reset_at; event emit |
| TC-DF-T-06-013-06 | Edge | 100k AI call trong 1 tháng | Query group_by day | Query trả 30 entry; latency < 2s |
| TC-DF-T-06-013-07 | Edge | Pricing model update (OpenAI tăng giá 20%) | Update lookup table | Cost record mới dùng giá mới; cost record cũ giữ giá cũ |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-005 (cần event `ai_vision_call_completed`).

**Chặn:** Không (nhưng là điều kiện trước khi enable AI vision diện rộng).

**Phụ thuộc giữa Epic:** DF-E-09 (Notification) tiêu thụ event soft/hard alert.

**Rủi ro:**

- **est_cost_usd sai do pricing update muộn:** giảm thiểu: cron sync pricing weekly; tài liệu warning "ước lượng".
- **Soft block không đủ — user vẫn vượt:** giảm thiểu: hard block là phòng tuyến cuối; tài liệu khuyến nghị config hard_pct = 110% để có buffer.

**Phụ thuộc bên ngoài:** DF-E-09 Notification (DF-E-09).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Cost tracking chính xác trong 5% với actual provider bill (đo thử 1 tháng).
- [ ] Soft + hard alert chạy thử trên staging.
- [ ] Runbook published.
- [ ] Telemetry: `ai_cost_usd_total{org}`, `ai_budget_block_total{org}`, `ai_budget_alert_total{org, severity}`.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner Epic-09.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-15, §8 "Chi phí AI vision có thể tăng nhanh"](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Automation Builder (§3.2).
- **Thuật ngữ:** [AI vision](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-09.
