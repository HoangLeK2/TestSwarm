# DF-T-07-002 — Account registration flow (UI + API)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-002 |
| **Title** | Account registration flow (UI + API) |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:frontend`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-07-01 |
| **Truy vết — UC refs** | UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Hành trình điển hình của Social Data Operator (xem §4.1) bắt đầu bằng "import danh sách account social vào hệ thống nếu chưa có". Bulk import là 1 đường (DF-T-07-010); ticket này là đường "tạo từng account" qua wizard UI + API. Đây là use case khi Operator chuẩn bị 1 account mới mua từ vendor và cần đưa vào hệ thống. Wizard hướng dẫn step-by-step: chọn platform → nhập username → tag/project → optional metadata → confirm.

Ticket này tập trung vào UX của registration flow — gồm cả validation realtime, lỗi rõ ràng, không cho commit nếu thiếu field bắt buộc.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** có một wizard tạo account từng bước rõ ràng, với validation realtime và preview trước khi save
> **Để** tạo account nhanh, không sai sót, không phải dùng curl

Persona phụ: Automation Builder (test scenario với account mới).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp UI wizard 4 step:
  1. Chọn platform (facebook/tiktok/threads/instagram/other).
  2. Nhập username + external_id (optional).
  3. Cấu hình tag, project assignment, proxy gán.
  4. Preview + confirm.
- Hệ thống PHẢI validate realtime ở step 2: gọi `GET /api/accounts/check-duplicate?platform=&username=` báo nếu trùng trong org.
- Hệ thống PHẢI hỗ trợ tạo nhanh "from clipboard" — user paste username vào, parse format (`user:pass:cookie`) thành các field hoặc reject với hướng dẫn.
- Hệ thống PHẢI hỗ trợ thêm account vào group trực tiếp ở step 3 (chọn 1 hoặc nhiều group đã có; có nút tạo group mới inline).
- Hệ thống PHẢI hiện preview đầy đủ ở step 4 trước khi POST.
- Hệ thống PHẢI hiện lỗi rõ ràng nếu API trả error (duplicate, validation, ...).
- Hệ thống PHẢI emit event `account_created` sau khi tạo thành công để DF-E-11 (Frontend) update list real-time.
- Hệ thống NÊN cho phép "Save as draft" để hoàn tất sau (lưu vào localStorage).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Luồng thành công tạo account**

```
Given user U mở /accounts/new
When U chọn Facebook → nhập "user_a" → tag "project-A" → confirm
Then API POST /api/accounts trả 201
And UI redirect tới /accounts/{id} với toast "Account created"
And account list refresh có entry mới
```

**AC-2: Duplicate cảnh báo realtime**

```
Given org X có account (facebook, "user_a")
When U nhập "user_a" ở step 2
Then API check-duplicate trả {duplicate:true, existing_account_id}
And UI hiện cảnh báo inline "Đã có account này trong org" + link tới account cũ
And nút Next bị disable cho tới khi user đổi username hoặc explicitly chọn "Edit existing"
```

**AC-3: Validation thiếu field**

```
Given user click Confirm ở step 4 với username rỗng
When click
Then UI báo "Username là bắt buộc" inline
And không gọi API POST
```

**AC-4: Tạo group inline**

```
Given U ở step 3 muốn gán vào group mới
When U click "+ Tạo group" inline → nhập tên group → confirm
Then group được tạo qua API (DF-T-07-003)
And account mới sau khi tạo cũng được add vào group đó (qua API member binding)
And nếu group fail tạo → account vẫn được tạo riêng (không bị block)
```

**AC-5: Save as draft**

```
Given U đang ở step 3 thì đóng tab
When U mở lại /accounts/new
Then wizard hiện hỏi "Tiếp tục draft trước?" với state đã nhập (trừ password / sensitive field)
And U có thể tiếp tục từ step 3
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm bulk import — DF-T-07-010.
- KHÔNG bao gồm OAuth flow tự kết nối platform — không trong scope module (login orchestration là trách nhiệm scenario).
- KHÔNG bao gồm 2FA setup — không trong scope.
- KHÔNG bao gồm cookie/session upload UI — đó là DF-T-07-004.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Endpoint `GET /api/accounts/check-duplicate` (idempotent, light query).
- [ ] Endpoint tích hợp với account create + group member binding atomic.

**Frontend** (`layer:frontend`)

- [ ] React wizard component 4 step với state machine.
- [ ] Realtime check-duplicate (debounce 300ms).
- [ ] Inline create group dialog.
- [ ] Draft save vào localStorage.
- [ ] Toast notification.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho check-duplicate.

**Documentation** (`layer:docs`)

- [ ] Screenshot wizard.
- [ ] Hướng dẫn Social Data Operator.

**Test** (`layer:test`)

- [ ] E2E test wizard với Playwright.
- [ ] Test realtime duplicate.
- [ ] Test draft restore.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-002-01 | Positive | User U mở wizard | Hoàn thành 4 step với data hợp lệ | Account tạo; redirect; toast |
| TC-DF-T-07-002-02 | Positive | Org X chưa có "user_b" | Step 2 nhập "user_b" | Check-duplicate trả ok; Next enabled |
| TC-DF-T-07-002-03 | Negative | Step 4 username rỗng | Click Confirm | Inline error; không POST |
| TC-DF-T-07-002-04 | Negative | Org X đã có "user_a" | Step 2 nhập "user_a" | Cảnh báo inline; Next disabled |
| TC-DF-T-07-002-05 | Edge | User mở 2 tab cùng wizard | Tạo step 3 ở tab 1, đóng tab 2 | Draft của tab 1 vẫn restore; tab 2 không ghi đè |
| TC-DF-T-07-002-06 | Edge | Network lag 5s khi check-duplicate | Nhập username | Loading indicator; không spam request; chỉ check sau debounce |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001 (account API), DF-T-07-003 (group API).

**Chặn:** Không.

**Phụ thuộc giữa Epic:** DF-E-11 (Frontend dashboard) host wizard này.

**Rủi ro:**

- **Wizard phức tạp gây dev cost cao:** giảm thiểu: dùng library form wizard có sẵn (Formik/RHF).
- **Realtime check spam API:** giảm thiểu: debounce 300ms; chỉ check khi field hợp lệ format.

**Phụ thuộc bên ngoài:** Frontend framework DF-E-11.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] E2E test pass.
- [ ] Wizard accessibility (WCAG AA cơ bản) pass.
- [ ] Telemetry: `account_wizard_step_total{step, action}`, `account_wizard_complete_total`.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner frontend.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §4.2 UC-07-01](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** [Social Data Operator (§3.1)](../../official_docs/02-personas-and-journeys.md).
- **Thuật ngữ:** [Account](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-11.
