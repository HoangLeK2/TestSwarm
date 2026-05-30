# DF-T-04-009 — Campaign-account binding

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-009 |
| **Title** | Campaign-account binding & no-implicit-account guard |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator`, `risk:auth` |
| **Truy vết — FR refs** | FR-04-09 (account variable tầng resolve), FR-04-20 (no implicit account) |
| **Truy vết — UC refs** | UC-04-06, UC-04-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 (SPG-007) ghi nhận **legacy primary-account fallback** vẫn còn trong một số đường dispatch — nếu scenario không khai báo account, hệ thống tự suy diễn primary account của device. Đây là contract violation theo FR-04-20 ("không tự suy diễn recovery") nhưng vẫn dưới flag tương thích.

Ticket này thiết lập **account binding tường minh** ở cấp campaign: campaign có thể chỉ định account_group hoặc per-device account map. Khi scenario có step yêu cầu account (vd login, post), executor (DF-T-04-010) dùng account đã bind. Nếu scenario yêu cầu account mà campaign không bind → fail rõ ràng, KHÔNG dùng primary account.

P0 vì là vấn đề ToS rủi ro cao: chạy nhầm account ToS-sensitive (vd farm khác) có thể gây ban hàng loạt. Cần test guard cứng.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** bind account hoặc account_group rõ ràng vào campaign và per-device map
> **Để** scenario chạy với đúng account tôi chỉ định, không có account "đoán" từ device

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép campaign bind account theo 3 cách: (a) `account_group_id` (DF-E-07 owns) — fan-out account theo strategy của group, (b) `per_device_accounts: {device_id: account_id}`, (c) `scenario_account_id` (1 account dùng chung — phù hợp single-account test).
- Hệ thống PHẢI resolve account tại dispatch time: cho mỗi (device, scenario) tuple, xác định 1 account effective.
- Hệ thống PHẢI lưu account_id vào execution record để audit.
- Hệ thống PHẢI tích hợp với VariableResolver tầng "account vars" (DF-T-04-002).
- Hệ thống PHẢI cấm fallback ngầm tới "primary account of device" khi scenario yêu cầu account và campaign không bind → execution `failed` với reason `account_not_bound` — trace FR-04-20.
- Hệ thống PHẢI validate ở dispatch: account tồn tại, thuộc cùng org, ở trạng thái available (DF-E-07 owns).
- Hệ thống PHẢI ghi audit log "account X bound to campaign Y by user Z at T".
- Hệ thống PHẢI cấm reveal credential — account_id là tham chiếu opaque, không log token.
- Hệ thống NÊN cảnh báo (warning) khi scenario có step `verification.assert_logged_in` mà campaign không bind account.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Bind account_group — fan-out**

```
Given campaign C target devices [D1,D2,D3], bind account_group AG ={A1,A2,A3} strategy=one_to_one
When dispatch
Then E1 dùng A1, E2 dùng A2, E3 dùng A3
And execution record lưu account_id rõ ràng
```

**AC-2: Per-device account map override**

```
Given campaign C có per_device_accounts {D1:A99}, bind account_group AG khác
When dispatch
Then E1 trên D1 dùng A99 (override), E2/E3 dùng theo group
```

**AC-3: Scenario yêu cầu account mà campaign không bind — FAIL không fallback**

```
Given scenario S có step type "fb.login" (yêu cầu account)
And campaign C không bind account
When dispatch
Then dispatch fail trước khi tạo execution: 400 "ACCOUNT_NOT_BOUND" với hint "khai báo account_group hoặc scenario_account_id"
And KHÔNG có execution nào dùng primary account của device
And test guard FR-04-20 pass
```

**AC-4: Cross-org account reject**

```
Given account A5 thuộc OrgB
When OrgA campaign bind A5
Then 400 "ACCOUNT_NOT_FOUND"
```

**AC-5: Account không available**

```
Given account A1 đang trong trạng thái "suspended" (DF-E-07)
When dispatch campaign bind A1
Then execution của D dùng A1 fail với reason "account_unavailable"; campaign vẫn tiếp tục với device khác có account available
```

**AC-6: Scenario không yêu cầu account — không cần bind**

```
Given scenario S chỉ có step Extraction OCR (không cần login)
And campaign C không bind account
When dispatch
Then dispatch thành công, execution.account_id=null
And không cảnh báo gì
```

**AC-7: Audit log account binding**

```
Given user U bind account A1 vào campaign C lúc T
When query audit log /campaigns/C/audit
Then có entry { action: "account.bound", actor: U, target_account: A1, at: T }
And response không lộ credential của A1
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm account entity CRUD — DF-E-07.
- KHÔNG bao gồm account group strategy (rotation, locking) — DF-E-07.
- KHÔNG bao gồm credential vault — DF-E-07 + DF-E-01.
- KHÔNG bao gồm migrate legacy campaigns sang explicit binding — ticket riêng SPG-007.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `CampaignAccountResolver` với 3 mode bind.
- [ ] Pre-dispatch check: scenario nào yêu cầu account (introspect step type via DF-E-08 registry metadata).
- [ ] Integration với DF-E-07 account service.
- [ ] Audit log emit.
- [ ] **Test guard FR-04-20**: unit test sạch không cho phép path "infer primary account".

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho `POST /campaigns/{id}/accounts` (bind), `DELETE /campaigns/{id}/accounts`.
- [ ] Schema campaign body có 3 trường account bind option.
- [ ] Mã lỗi: `ACCOUNT_NOT_BOUND`, `ACCOUNT_NOT_FOUND`, `ACCOUNT_UNAVAILABLE`.

**Database / Migration** (`layer:db`)

- [ ] Cột `account_group_id`, `scenario_account_id`, `per_device_accounts` (JSONB) trên `campaigns`.
- [ ] Cột `account_id` trên `executions`.

**Documentation** (`layer:docs`)

- [ ] Doc 3 bind mode + ví dụ chọn mode.
- [ ] Warning: "no implicit primary account" trong best-practice guide.

**Test** (`layer:test`)

- [ ] Test guard FR-04-20 — case "scenario yêu cầu account, không bind → fail" phải pass.
- [ ] Test 3 bind mode.
- [ ] Test cross-org isolation.
- [ ] Test step không yêu cầu account vẫn run được.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-009-01 | Positive | C bind AG={A1,A2}, target [D1,D2] | Dispatch | E1 dùng A1, E2 dùng A2 |
| TC-DF-T-04-009-02 | Positive | C per_device_accounts {D1:A99} + AG fallback | Dispatch | D1→A99 (override), D2→theo AG |
| TC-DF-T-04-009-03 | Negative | Scenario S "fb.login" cần account, C không bind | Dispatch | 400 "ACCOUNT_NOT_BOUND", không execution |
| TC-DF-T-04-009-04 | Negative | A5 thuộc OrgB | OrgA bind A5 | 400 "ACCOUNT_NOT_FOUND" |
| TC-DF-T-04-009-05 | Edge | A1 status="suspended" | Dispatch campaign bind A1 | Execution của device dùng A1 fail "account_unavailable"; device khác (nếu có account khác) tiếp tục |
| TC-DF-T-04-009-06 | Positive | Scenario chỉ OCR, không cần account | Dispatch không bind account | Success, execution.account_id=null |
| TC-DF-T-04-009-07 | Edge | Test guard: chạy unit test với mock scenario yêu cầu account, mock device có primary_account=A_primary, không bind | Test FR-04-20 | Hệ thống KHÔNG dùng A_primary, fail rõ ràng |
| TC-DF-T-04-009-08 | Positive | Bind account log audit | Query audit | Entry tồn tại, không chứa credential |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-006, DF-T-04-007, DF-T-04-008, DF-E-07 (account entity + account_group strategy).

**Chặn:** DF-T-04-010 (execution runtime đọc account).

**Phụ thuộc giữa Epic:** DF-E-07 phải cung cấp:
- `account.get(account_id)` API.
- `account_group.resolve_for_device(group_id, device_id, strategy)` API.
- Account availability check.

**Rủi ro:**

- **Legacy fallback path còn sót:** đặc tả module SPG-007 đã cảnh báo → ticket này KHÔNG remove legacy ngay mà thêm guard logging "implicit fallback triggered" để track; remove ở ticket migration sau khi data clean.
- **Account leak across campaigns:** DF-E-07 chịu trách nhiệm concurrency; ticket này chỉ propagate.
- **Strategy account_group khó test:** dùng mock service DF-E-07.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 85% (high vì rủi ro auth).
- [ ] Test guard FR-04-20 có ≥ 2 case riêng pass.
- [ ] Doc 3 bind mode published.
- [ ] Telemetry: metric `campaign.account.fallback_triggered.count` (sẽ luôn = 0 sau migration; tạm dùng để track legacy path).
- [ ] Audit log không leak credential (test by code review).
- [ ] Code review ≥ 2 approve (owner Campaigns + owner Accounts).
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-09, FR-04-20, mục 8 (gap SPG-007).
- **Module 07 spec:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md).
- **Thuật ngữ:** Account variable, Authored scenario flow.
- **Nhóm người dùng:** Social Data Operator, Automation Builder.
