# DF-T-11-017 — First-run onboarding & empty-state CTA

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-017 |
| **Title** | First-run onboarding & empty-state CTA cho luồng core |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:fleet-operator`, `persona:automation-builder`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-11-05, FR-11-09, FR-11-10, FR-11-11 |
| **Truy vết — UC refs** | UC-02-01, UC-04-01, UC-06-01, UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Release đầu không chỉ cần API và màn hình riêng lẻ; end-user mới phải biết bước tiếp theo khi hệ thống chưa có dữ liệu. Các màn fleet, account, campaign và content đều có trạng thái rỗng rất phổ biến trong lần dùng đầu tiên. Nếu empty state chỉ là bảng trống, người dùng không biết nên pair device, tạo account, tạo campaign hay xem content ở đâu.

Ticket này bổ sung onboarding mỏng cho core workflow: hướng người dùng từ trạng thái chưa có device/account/campaign/content sang hành động tiếp theo. Đây không phải landing page hay tour dài; chỉ là empty state, CTA và deep link đúng ngữ cảnh trên các màn core.

## 3. Câu chuyện người dùng

> **Là** Operator mới  
> **Tôi muốn** thấy hành động tiếp theo khi một màn chưa có dữ liệu  
> **Để** có thể tự đi qua luồng pair device, thêm account, tạo campaign và xem content mà không cần hỏi team kỹ thuật

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có empty state cho fleet khi organization chưa có device, với CTA tới luồng pair device hoặc hướng dẫn agent tối thiểu.
- Hệ thống PHẢI có empty state cho accounts khi chưa có account, với CTA tới account console.
- Hệ thống PHẢI có empty state cho campaigns khi chưa có campaign, với CTA tạo campaign mới.
- Hệ thống PHẢI có empty state cho content khi chưa có collection hoặc chưa có kết quả, với CTA quay về campaign/execution liên quan.
- CTA PHẢI tôn trọng RBAC; user không có quyền chỉ thấy trạng thái đọc và hướng dẫn liên hệ admin.
- Empty state PHẢI dùng thuật ngữ thống nhất: device, account, campaign, execution, content item, artifact.
- Empty state NÊN có tracking event để đo tỉ lệ user đi tiếp từ trạng thái rỗng sang hành động core.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Organization mới chưa có device**

```gherkin
Given tôi đăng nhập vào organization mới
And tôi có quyền quản lý device
When tôi mở fleet view
Then tôi thấy empty state có CTA pair device
And CTA đưa tôi tới đúng luồng device onboarding
```

**AC-2: User không có quyền tạo tài nguyên**

```gherkin
Given tôi chỉ có quyền xem
When tôi mở campaign list đang rỗng
Then tôi thấy empty state chỉ đọc
And không thấy CTA tạo campaign
```

**AC-3: Campaign đã chạy nhưng chưa có content**

```gherkin
Given một campaign đã hoàn tất nhưng chưa sinh content item
When tôi mở content browser
Then tôi thấy trạng thái chưa có content
And có deep link quay lại execution monitor liên quan nếu hệ thống biết execution source
```

**AC-4: Không làm vỡ layout mobile**

```gherkin
Given tôi mở dashboard trên viewport mobile
When một màn core ở trạng thái rỗng
Then title, mô tả ngắn và CTA không chồng lấn
And CTA vẫn bấm được
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm guided tour nhiều bước hoặc checklist onboarding dạng wizard.
- KHÔNG bao gồm tạo dữ liệu mẫu tự động.
- KHÔNG bao gồm thay đổi backend onboarding state; nếu cần tracking nâng cao sẽ tách ticket sau.
- KHÔNG bao gồm nội dung marketing hoặc landing page.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Tạo component empty state dùng chung trong app shell.
- [ ] Gắn empty state vào fleet view, account console, campaign list và content browser.
- [ ] Thêm RBAC-aware CTA theo quyền user.
- [ ] Thêm responsive state cho mobile/desktop.
- [ ] Đồng bộ i18n vi/en cho label và CTA.

**Test** (`layer:test`)

- [ ] Viết component test cho quyền có CTA và không có CTA.
- [ ] Viết e2e cho organization mới đi từ fleet empty state sang pair device.
- [ ] Chụp screenshot responsive cho các màn core ở trạng thái rỗng.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-017-01 | Positive | Organization mới, user có quyền device | Mở fleet view | Empty state có CTA pair device đúng quyền |
| TC-DF-T-11-017-02 | Positive | Chưa có campaign, user có quyền tạo | Mở campaign list | CTA tạo campaign hiển thị và dẫn tới campaign editor |
| TC-DF-T-11-017-03 | Negative | User không có quyền tạo account | Mở account console rỗng | Không có CTA tạo account, có thông báo quyền phù hợp |
| TC-DF-T-11-017-04 | Negative | Route đích của CTA bị feature flag tắt | Bấm CTA | Hệ thống không crash và hiển thị trạng thái chưa khả dụng |
| TC-DF-T-11-017-05 | Edge | Content browser không có dữ liệu do filter quá hẹp | Mở content browser với filter | Empty state phân biệt “không có kết quả theo filter” với “chưa từng có content” |
| TC-DF-T-11-017-06 | Edge | Viewport mobile hẹp | Mở các màn empty state | Text và CTA không tràn layout |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002, DF-T-11-003, DF-T-11-005, DF-T-11-009, DF-T-11-011.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** DF-E-01 cung cấp quyền user; DF-E-02, DF-E-04, DF-E-06, DF-E-07 cung cấp dữ liệu trạng thái cho từng màn.

**Rủi ro:**

- **CTA sai quyền:** dùng RBAC guard chung từ DF-T-11-002 thay vì hardcode theo route.
- **Thông điệp quá dài:** giới hạn copy ngắn, dùng terminology chuẩn và kiểm tra responsive.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Empty state có trên fleet, accounts, campaigns và content.
- [ ] CTA tôn trọng RBAC và feature flag.
- [ ] i18n vi/en có đủ cho copy mới.
- [ ] Test case TC-DF-T-11-017-* được map sang test tự động hoặc manual evidence.
- [ ] Không có layout shift hoặc overflow ở mobile/desktop.
- [ ] Release notes ghi rõ onboarding mỏng cho first-run.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** `docs/official_docs/modules/11-frontend-dashboard.md`.
- **Nhóm người dùng:** `docs/official_docs/02-personas-and-journeys.md` — Fleet Operator, Automation Builder, Social Data Operator.
- **Thuật ngữ:** `docs/official_docs/00-glossary.md` — device, account, campaign, execution, content item, artifact.

