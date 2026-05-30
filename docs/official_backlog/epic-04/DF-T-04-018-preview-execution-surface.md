# DF-T-04-018 — Preview execution surface

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-018 |
| **Title** | Preview execution surface (chạy thử scenario trên 1 device cô lập) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-04-18 |
| **Truy vết — UC refs** | UC-04-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

UC-04-05: Automation Builder muốn chạy thử scenario trên 1 device cô lập trước khi dispatch diện rộng. Đặc tả module mục 8 lưu ý: "Preview chạy trên device thật, dùng artifact thật, ghi vào content store thật. Người dựng cần chú ý nếu scenario có step thao tác social thật".

Ticket này tạo execution surface preview: dùng cùng runtime DF-T-04-010 nhưng đánh dấu marker `preview=true`, không tính vào campaign run history, artifact đính vào "preview collection" riêng để dễ làm sạch.

P2. Tuy là Should priority trong FR (FR-04-18), nhưng quan trọng cho Automation Builder UX.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** chạy thử scenario trên 1 device cô lập với artifact đầy đủ, không bị lẫn vào campaign run history
> **Để** verify scenario trước khi dispatch diện rộng, tránh lỗi trên hàng trăm device

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `POST /scenarios/{id}/preview` body `{ device_id, scenario_version?, vars?, account_id? }` — tạo execution marker preview.
- Hệ thống PHẢI dùng cùng runtime DF-T-04-010 nhưng set `execution.kind="preview"`.
- Preview execution PHẢI có artifact đầy đủ (DF-T-04-014 capture default ON).
- Preview KHÔNG nằm trong campaign — execution.campaign_id=null.
- Preview KHÔNG tính vào "campaign run history" hay aggregator status.
- Artifact preview lưu vào "preview collection" của DF-E-06 (cho dễ purge).
- Hệ thống PHẢI cho phép Automation Builder list preview của mình: `GET /preview?org=&user=&since=`.
- Hệ thống PHẢI auto-purge preview > 7 ngày (default; configurable per org).
- Hệ thống PHẢI cảnh báo trước khi run preview nếu scenario có step social-effect (post, comment, follow) — gợi ý dùng test account.
- Hệ thống PHẢI release device sau preview (qua DF-E-02) — claim ngắn hạn.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Preview luồng thành công**

```
Given scenario S, device D1 online thuộc OrgA
When POST /scenarios/S/preview body { device_id: D1 }
Then execution E created kind="preview", campaign_id=null
And workflow chạy như DF-T-04-010 luồng thành công
And artifact đính kèm preview collection
And không xuất hiện trong GET /campaigns/.../executions
```

**AC-2: Preview xuất hiện trong list preview**

```
Given Automation Builder U chạy 3 preview hôm nay
When GET /preview?user=U&since=today
Then trả về 3 preview với status, link artifact
```

**AC-3: Warning step social-effect**

```
Given scenario S có step "fb.post" (side-effect)
When POST /scenarios/S/preview
Then 200 nhưng response chứa warning "Step social-effect detected; consider test account"
And nếu user pass force=false (default), reject với 400 "PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE"
And force=true cho phép chạy
```

**AC-4: Auto purge sau 7 ngày**

```
Given preview execution E tạo 8 ngày trước
When purger cron chạy
Then artifact của E xoá khỏi preview collection
And execution record giữ lại (audit) nhưng artifact_refs null hoặc archived flag
```

**AC-5: Preview không affect campaign aggregator**

```
Given campaign C đang running
And Automation Builder chạy preview cùng scenario của C
When preview run
Then aggregator campaign C KHÔNG re-evaluate
```

**AC-6: Preview yêu cầu account khi step social-login**

```
Given scenario có step "fb.login"
And user không pass account_id
When POST /preview
Then 400 "ACCOUNT_REQUIRED_FOR_PREVIEW" (cùng FR-04-20 logic, không fallback primary)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm sandbox device giả lập — preview chạy device thật.
- KHÔNG bao gồm parallel preview trên nhiều device — chỉ 1 device.
- KHÔNG bao gồm scheduled preview — không cần thiết.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Endpoint POST /scenarios/{id}/preview.
- [ ] Wire dispatcher với kind="preview" flag.
- [ ] Side-effect step detector (introspect step type).
- [ ] Auto-purge cron job.
- [ ] List preview endpoint.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 2 endpoint.
- [ ] Cập nhật schema execution để có field `kind` (campaign|preview|session).

**Database / Migration** (`layer:db`)

- [ ] Cột `kind` trên execution; default "campaign".
- [ ] Index trên (kind, organization_id, created_by, created_at).

**Documentation** (`layer:docs`)

- [ ] Doc preview vs campaign.
- [ ] Best-practice "khi nào preview".

**Test** (`layer:test`)

- [ ] Test preview chạy đầy đủ.
- [ ] Test warning side-effect.
- [ ] Test purge cron.
- [ ] Test isolation từ campaign aggregator.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-018-01 | Positive | Scenario S valid, device D1 | POST /preview | Execution kind=preview, artifact đầy đủ, không trong campaign list |
| TC-DF-T-04-018-02 | Positive | Preview hôm qua | GET /preview?user=U&since=yesterday | List trả về preview U |
| TC-DF-T-04-018-03 | Negative | Scenario có step fb.post, không force | POST /preview | 400 "PREVIEW_HAS_SIDE_EFFECT_REQUIRES_FORCE" |
| TC-DF-T-04-018-04 | Negative | Scenario có fb.login, không pass account_id | POST /preview | 400 "ACCOUNT_REQUIRED_FOR_PREVIEW" |
| TC-DF-T-04-018-05 | Edge | Preview > 7 ngày | Cron purge | Artifact xoá, execution metadata giữ |
| TC-DF-T-04-018-06 | Edge | Preview chạy cùng lúc campaign C cùng scenario | Run | Aggregator campaign không re-evaluate; preview hoàn toàn độc lập |
| TC-DF-T-04-018-07 | Positive | force=true override warning | POST /preview với force=true | 200, execution chạy |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010 (runtime), DF-T-04-014 (artifact), DF-T-04-009 (account binding).

**Chặn:** DF-E-11 (UI "Run preview" button).

**Rủi ro:**

- **Preview ghi content rác:** DF-E-06 cần có preview collection riêng để purge.
- **Operator quên rằng preview là device thật:** UI warning + doc.
- **Device contention:** preview claim device ngắn nhưng có thể conflict campaign đang dispatch → preview ưu tiên thấp; nếu device đã claim, reject 409.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Auto-purge cron tested trên staging.
- [ ] Doc + best-practice published.
- [ ] Code review ≥ 1 approve.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-18, mục 8 (preview ≠ sandbox).
- **Thuật ngữ:** Execution.
