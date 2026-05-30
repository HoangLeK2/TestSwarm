# DF-T-11-011 — Account console UI — CRUD + filter + bulk action

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-011 |
| **Title** | Account console UI — `/dashboard/accounts` CRUD + filter + bulk action |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `risk:auth`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-11-10 |
| **Truy vết — UC refs** | UC-11-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Social Data Operator quản lý hàng trăm account social trên dashboard (UC-11-13). Trang account console là entry point CRUD account, gán device, gán account-group, theo dõi health (healthy / warning / checkpointed / disabled).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator hoặc Admin
> **Tôi muốn** CRUD account + filter + bulk action gán device/group
> **Để** quản lý hiệu quả account social với quy mô lớn.

## 4. Yêu cầu chức năng

- Trang `/dashboard/accounts` PHẢI list account với: handle, platform, group, health_status, last_used_device — trace FR-11-10.
- Filter: platform, group, health_status, search handle — trace FR-11-10.
- Action: Create, Edit (handle/group), Bulk assign to group, Bulk disable.
- Credential PHẢI không hiển thị trong list (chỉ ở dialog edit, masked) — trace `risk:auth` + DF-E-07.
- Gắn account vào device PHẢI không kéo theo lưu password vào content — trace FR-11-10.
- Ownership theo organization được tôn trọng — trace FR-11-10.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List + filter**

```
Given 200 account
When user filter platform=facebook + group=A + health=healthy
Then subset chính xác
```

**AC-2: Edit account masked credential**

```
Given account ACC1
When user mở dialog edit
Then password field masked, không cho copy plaintext
And update không yêu cầu nhập lại password (chỉ khi rotate)
```

**AC-3: Bulk assign group**

```
Given 20 account selected
When user bulk assign to group G2
Then 20 account chuyển nhóm
And audit log ghi action
```

**AC-4: Credential không xuất hiện trong content / log**

```
Given gắn account ACC1 vào device A1
When inspect content/audit log
Then không có password plaintext
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm account recovery flow.
- KHÔNG bao gồm import bulk CSV (backlog).
- KHÔNG bao gồm vault credential — lộ trình.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `accounts/`.
- [ ] Bảng + filter + bulk.
- [ ] Dialog edit masked.
- [ ] Health badge.

**Contract / API** (`layer:contract`)

- [ ] Generated client DF-E-07.

**Documentation** (`layer:docs`)

- [ ] UX doc + security note (masked).

**Test** (`layer:test`)

- [ ] Test masked credential.
- [ ] Test bulk.
- [ ] Test grep credential leak.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-011-01 | Positive | 200 account | Filter combo | Subset đúng |
| TC-DF-T-11-011-02 | Positive | 20 select | Bulk assign | OK + audit log |
| TC-DF-T-11-011-03 | Negative | Cross-org account | Edit | 403 |
| TC-DF-T-11-011-04 | Negative | Grep DOM cho "password=..." | Inspect | Không tìm thấy plaintext |
| TC-DF-T-11-011-05 | Edge | Bulk 0 account | Click bulk | Action disabled |
| TC-DF-T-11-011-06 | Edge | Account health checkpointed | Badge | Hiển thị đỏ + tooltip |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** DF-T-11-012.

**Phụ thuộc giữa Epic:** **DF-E-07**.

**Rủi ro:**

- **Credential leak qua DOM:** masked + grep test.
- **Bulk lớn gây timeout:** server side batch.

**Phụ thuộc bên ngoài:** Service account DF-E-07.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật + security note.
- [ ] Telemetry: counter bulk_action.
- [ ] Code review ≥ 1 approve + security reviewer.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-10](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [07-accounts-and-groups.md](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator, Admin.
- **Thuật ngữ:** Account.
