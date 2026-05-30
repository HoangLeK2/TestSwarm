# DF-T-11-007 — Scenario library browser UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-007 |
| **Title** | Scenario library browser UI — `/dashboard/scenario-templates` |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P2 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-11-09 |
| **Truy vết — UC refs** | UC-11-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Automation Builder không muốn vẽ lại scenario phổ biến từ đầu — họ cần thư viện template để reuse. KPI: tỷ lệ scenario tái sử dụng giữa campaign khác nhau ≥ 50% (persona JTBD 3.2). Trang scenario-templates là entry point reuse.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** browse `/dashboard/scenario-templates` xem các template (FB Group Crawl, IG Feed Crawl, TikTok Follow, ...) kèm preview
> **Để** clone template làm scenario mới thay vì vẽ lại.

## 4. Yêu cầu chức năng

- Trang PHẢI list scenario template với: name, platform, mô tả ngắn, số step, last_updated — trace FR-11-09.
- Filter: platform, tag — trace FR-11-09.
- Action: View detail (mở scenario flow editor read-only), Clone (tạo scenario mới copy từ template).
- Clone PHẢI mở editor (DF-T-11-006) với scenario mới chưa save.
- Trang hiển thị badge "official" cho template do platform team duy trì.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List template**

```
Given có 12 template
When user mở /dashboard/scenario-templates
Then 12 entry với badge platform + last_updated
```

**AC-2: Filter platform**

```
Given filter platform=tiktok
When apply
Then chỉ TikTok templates
```

**AC-3: Clone**

```
Given template T1
When user click Clone → đặt name S2
Then S2 tạo + chuyển sang editor
And graph mở từ copy của T1
```

**AC-4: View detail read-only**

```
Given click View detail
Then editor mở ở chế độ read-only
And không cho save
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm upload template bên ngoài.
- KHÔNG bao gồm version diff template.
- KHÔNG bao gồm marketplace.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `scenario-templates/`.
- [ ] Bảng + filter.
- [ ] Action clone + view.

**Contract / API** (`layer:contract`)

- [ ] Generated client cho template endpoints.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] E2E clone luồng thành công.
- [ ] Test read-only mode.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-007-01 | Positive | 12 template | Mở trang | 12 entry |
| TC-DF-T-11-007-02 | Positive | Clone T1 | Click + đặt name | S2 tạo + editor mở |
| TC-DF-T-11-007-03 | Positive | View detail | Open | Read-only |
| TC-DF-T-11-007-04 | Negative | Clone với name trùng | Submit | Validation rõ |
| TC-DF-T-11-007-05 | Edge | 0 template | Mở | Empty state + hướng dẫn |
| TC-DF-T-11-007-06 | Negative | Template thuộc organization khác | Mở detail bằng URL trực tiếp | Bị chặn 403/404, không lộ nội dung template |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-006.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-04** — scenario template service.

**Rủi ro:**

- **Clone copy thiếu field:** test schema.

**Phụ thuộc bên ngoài:** Service template DF-E-04.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: counter clone_template.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-09](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Nhóm người dùng:** Automation Builder.
- **Thuật ngữ:** Scenario.
