# DF-T-07-003 — Account group CRUD + member binding

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-003 |
| **Title** | Account group CRUD + member binding |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `layer:frontend`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2` |
| **Truy vết — FR refs** | FR-07-05, FR-07-13 |
| **Truy vết — UC refs** | UC-07-05, UC-07-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Account group là cơ chế gom account theo dự án để cấp phát round-robin. Đặc tả module §6 FR-07-05: "Người dùng tạo, đặt tên, mô tả, gắn thành viên cho account group." Quan trọng: FR-07-13 yêu cầu **phân biệt** account group với device group — tên gọi, tài liệu, và UI riêng biệt; không cho gộp logic.

Persona hưởng lợi: Social Data Operator (tổ chức account theo dự án), Automation Builder (reference group trong scenario thay vì account id cứng).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** tạo account group có owner và mô tả, thêm/xóa thành viên (account) qua API/UI, và phân biệt rõ với device group
> **Để** quản lý fleet account theo dự án, sẵn sàng cho round-robin và scenario reference

Persona phụ: Automation Builder.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có bảng `account_groups(id, organization_id, owner_id, name, description, project_tag, metadata, rotation_pointer, created_at, updated_at, deleted_at)` — trace FR-07-05.
- Hệ thống PHẢI có bảng `account_group_members(group_id, account_id, added_at, added_by, PRIMARY KEY(group_id, account_id))`.
- Hệ thống PHẢI có endpoint:
  - `POST /api/account-groups` tạo group.
  - `GET /api/account-groups` list theo org.
  - `GET /api/account-groups/{id}` chi tiết + member count.
  - `PATCH /api/account-groups/{id}` update name/desc/metadata.
  - `DELETE /api/account-groups/{id}` soft-delete; cascade detach member (KHÔNG xóa account gốc).
  - `POST /api/account-groups/{id}/members` add member (account_ids[]).
  - `DELETE /api/account-groups/{id}/members/{account_id}` remove member.
  - `GET /api/account-groups/{id}/members` list member + status.
- Hệ thống PHẢI từ chối tạo account group có tên trùng với device group trong cùng org ở **UI** (không trùng hai tên dễ nhầm); ở DB hai bảng tách rời nên technically có thể trùng — UI check để giảm nhầm — trace FR-07-13.
- Hệ thống PHẢI cho phép 1 account thuộc nhiều group (many-to-many).
- Hệ thống PHẢI cho phép account_id của group được lọc bỏ khi account bị soft-delete (member row vẫn còn, nhưng không xuất hiện trong list active member).
- Hệ thống PHẢI enforce add/remove member idempotent: add lại không tạo duplicate row; remove account không trong group trả 204 (idempotent semantics).
- Hệ thống PHẢI enforce organization filter.
- Hệ thống NÊN cung cấp endpoint `GET /api/account-groups/{id}/stats` trả {total_members, active_members, status_breakdown, last_used_at_max}.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo group + thêm member**

```
Given user U có 5 account trong org X
When U POST /api/account-groups {name:"FB Group Project A", project_tag:"clientA"}
Then trả 201 group_id
When U POST /api/account-groups/{id}/members {account_ids:[a1,a2,a3]}
Then 3 row member tạo
And GET /members trả 3 entry với status
```

**AC-2: Phân biệt với device group ở UI**

```
Given org X đã có device_group tên "FB Project A"
When user mở UI tạo account_group với tên "FB Project A"
Then UI hiện cảnh báo "Đã có device group cùng tên — tránh nhầm lẫn" + gợi ý prefix
And user vẫn có thể tiếp tục (chỉ cảnh báo)
And tài liệu UI link tới đặc tả module FR-07-13
```

**AC-3: Idempotent add member**

```
Given account a1 đã trong group G
When U POST /members {account_ids:[a1]}
Then trả 200 với report "added:0, already_member:1"
And không có duplicate row
```

**AC-4: Cross-tenant**

```
Given group G thuộc org X; account A thuộc org Y
When user POST /api/account-groups/{G.id}/members {account_ids:[A.id]}
Then trả 422 ACCOUNT_CROSS_TENANT
And không có member row tạo
```

**AC-5: Soft-delete group không xóa account**

```
Given group G có 10 member
When DELETE /api/account-groups/{G.id}
Then group bị soft-delete; row member giữ
And 10 account vẫn tồn tại độc lập
And GET /api/accounts/{a.id} trả normal (không cascade)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm round-robin endpoint — đó là DF-T-07-008.
- KHÔNG bao gồm quota per group — đó là DF-T-07-008.
- KHÔNG bao gồm permission granular per group — chỉ owner + organization.
- KHÔNG bao gồm group templates (preset config) — không trong scope.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Model `AccountGroup`, `AccountGroupMember`.
- [ ] Repository CRUD.
- [ ] Service idempotent add/remove member.
- [ ] Stats aggregator.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 8 endpoint.
- [ ] Mã lỗi `GROUP_NOT_FOUND`, `ACCOUNT_CROSS_TENANT`.

**Database / Migration** (`layer:db`)

- [ ] Migration bảng `account_groups`, `account_group_members`.
- [ ] Index (organization_id, owner_id), (project_tag).

**Frontend** (`layer:frontend`)

- [ ] UI list / detail / member management.
- [ ] Cảnh báo trùng tên device group.

**Documentation** (`layer:docs`)

- [ ] "Account group vs Device group" section trong `docs/modules/accounts.md`.

**Test** (`layer:test`)

- [ ] Integration test 8 endpoint.
- [ ] Test idempotent.
- [ ] Test cross-tenant.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-003-01 | Positive | User U có 5 account | Tạo group + add 5 member | Group có 5 member; stats đúng |
| TC-DF-T-07-003-02 | Positive | Account a1 trong group G | Remove a1 từ G | Member row xóa; a1 vẫn tồn tại |
| TC-DF-T-07-003-03 | Negative | Account a thuộc org khác | Add vào group org mình | 422 ACCOUNT_CROSS_TENANT |
| TC-DF-T-07-003-04 | Negative | Group đã soft-delete | Add member | 404 GROUP_NOT_FOUND |
| TC-DF-T-07-003-05 | Edge | Add lại a1 đã là member | POST /members {a1} | 200 report "already_member:1" |
| TC-DF-T-07-003-06 | Edge | Account soft-delete sau khi đã add vào group | GET /members | Member không xuất hiện trong active list; vẫn xuất hiện trong "all_members" filter |
| TC-DF-T-07-003-07 | Edge | Tạo group cùng tên device group | UI test | Cảnh báo hiện; vẫn cho continue |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001 (account model).

**Chặn:** DF-T-07-007, DF-T-07-008, DF-T-07-014.

**Phụ thuộc giữa Epic:** DF-E-02 (device group) — chỉ cần biết tên để cảnh báo trùng; không trực tiếp phụ thuộc.

**Rủi ro:**

- **Nhầm device group ↔ account group:** giảm thiểu: tài liệu, UI cảnh báo, tên field rõ.
- **Member list lớn (1000 account / group):** giảm thiểu: pagination, query optimization.

**Phụ thuộc bên ngoài:** DF-E-01 (org scope).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 8 endpoint integration test pass.
- [ ] UI test pass.
- [ ] `docs/modules/accounts.md` viết section phân biệt.
- [ ] Telemetry: `account_group_total{org}`, `account_group_member_total`.
- [ ] Code review ≥ 1 approve owner module.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §6 FR-07-05, FR-07-13](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator (§3.1).
- **Thuật ngữ:** [Account group](../../official_docs/00-glossary.md).
