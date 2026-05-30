# DF-T-11-012 — Account-group manager UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-012 |
| **Title** | Account-group manager UI — `/dashboard/device-farm/account-groups` |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-11-10 |
| **Truy vết — UC refs** | UC-11-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Account-group cho phép gán account vào rotation pool cho scenario (UC-11-13). Trang này quản lý group: tạo, gán account vào group, mô tả mục đích, theo dõi sức khỏe pool.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator hoặc Admin
> **Tôi muốn** quản lý account-group — tạo, gán account, theo dõi pool health
> **Để** scenario reference group thay vì credential cụ thể.

## 4. Yêu cầu chức năng

- Trang PHẢI list group với: name, platform, số account, % healthy — trace FR-11-10.
- Action: Create group, Add accounts to group, Remove accounts.
- Detail group hiển thị account members + health badge per account.
- Filter platform.
- Ownership org.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Create group + add accounts**

```
Given 50 account healthy
When user create group "Pool FB EU" + add 10 account
Then group hiển thị 10 member + 100% healthy
```

**AC-2: Remove account khỏi group**

```
Given group có 10 account
When remove 2 account
Then group còn 8 member
And audit log ghi action
```

**AC-3: Cross-org blocked**

```
Given account thuộc org Y
When user org X cố add vào group org X
Then reject
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm import CSV.
- KHÔNG bao gồm policy rotation cụ thể (cấu hình ở scenario / DF-E-07).

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `account-groups/`.
- [ ] List + detail.
- [ ] Dialog add/remove account.

**Contract / API** (`layer:contract`)

- [ ] Generated client DF-E-07.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] E2E create + add + remove.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-012-01 | Positive | 50 account | Create + add 10 | Group 10 |
| TC-DF-T-11-012-02 | Positive | Group 10 | Remove 2 | Group 8 + audit |
| TC-DF-T-11-012-03 | Negative | Cross-org | Add | Reject |
| TC-DF-T-11-012-04 | Edge | Group 0 account | Detail | Empty state |
| TC-DF-T-11-012-05 | Edge | Add account đã thuộc group khác | Quan sát | Cảnh báo "account already in group X" + cho phép confirm move |
| TC-DF-T-11-012-06 | Negative | Account đang suspended/banned | Add vào rotation group | UI/API từ chối hoặc yêu cầu confirm theo policy, audit ghi lý do |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-011.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-07**.

**Rủi ro:**

- **Account ở nhiều group gây nhầm:** UX cảnh báo.

**Phụ thuộc bên ngoài:** Service DF-E-07.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-10](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator, Admin.
- **Thuật ngữ:** Account group.
