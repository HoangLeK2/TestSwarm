# DF-T-11-005 — Campaign list + filter UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-005 |
| **Title** | Campaign list UI — `/dashboard/campaigns` với filter, dispatch action |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-11-09 |
| **Truy vết — UC refs** | UC-11-08 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Social Data Operator dispatch campaign từ trang này (giai đoạn 4 hành trình 4.1). Họ cần filter theo platform, scenario, status để định vị nhanh; click campaign mở editor (DF-T-11-006) hoặc execution monitor (DF-T-11-008).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mở `/dashboard/campaigns` thấy danh sách campaign + filter + dispatch action
> **Để** vào việc nhanh và quản lý hàng chục campaign mỗi ngày không nhầm.

## 4. Yêu cầu chức năng

- Trang PHẢI list campaign với: name, scenario, device group, platform, status (draft/running/completed/failed), created_at, last_run — trace FR-11-09.
- Filter PHẢI hỗ trợ: status, platform, scenario, time range, search name — trace FR-11-09.
- Action PHẢI có: Create new, Dispatch (run), Open editor, Open execution monitor — trace FR-11-09.
- Dispatch PHẢI yêu cầu chọn device hoặc device group (modal confirm) — trace FR-11-09.
- Theo dõi tiến độ campaign đang running PHẢI hiển thị progress aggregate (số device done / total) — trace FR-11-09.
- DLQ entry mở trực tiếp được từ campaign view — trace FR-11-09.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List campaign**

```
Given org có 30 campaign mix status
When user mở /dashboard/campaigns
Then bảng hiển thị 30 entry kèm status badge
And sort mặc định theo last_run desc
```

**AC-2: Filter + search**

```
Given filter status=running + platform=facebook
When apply
Then chỉ campaign Facebook đang running
And count tổng đúng
```

**AC-3: Dispatch flow**

```
Given campaign draft C1
When user click "Dispatch" → modal chọn device group G1 → confirm
Then campaign chuyển running
And toast success + chuyển sang execution monitor (DF-T-11-008)
```

**AC-4: Progress aggregate**

```
Given campaign C1 đang chạy trên 10 device, 4 done, 1 failed, 5 running
When user xem row
Then progress bar 50% và badge "1 failed"
And click failed mở DLQ
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm campaign editor — DF-T-11-006.
- KHÔNG bao gồm execution monitor chi tiết — DF-T-11-008.
- KHÔNG bao gồm scenario template browse — DF-T-11-007.
- KHÔNG bao gồm schedule — DF-T-11-013.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `campaigns/`.
- [ ] Bảng + filter + search.
- [ ] Modal dispatch chọn device/group.
- [ ] Progress aggregate component.
- [ ] Link DLQ.

**Contract / API** (`layer:contract`)

- [ ] Tiêu thụ generated client cho campaign endpoints.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] E2E luồng thành công dispatch.
- [ ] Test filter combo.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-005-01 | Positive | 30 campaign | Mở trang | List + sort đúng |
| TC-DF-T-11-005-02 | Positive | Filter running + facebook | Apply | Subset chính xác |
| TC-DF-T-11-005-03 | Positive | Dispatch campaign draft | Confirm | Running + chuyển monitor |
| TC-DF-T-11-005-04 | Negative | User không có quyền dispatch | Click dispatch | Reject + message rõ |
| TC-DF-T-11-005-05 | Negative | Campaign đã running, click Dispatch lần 2 | Click | Reject "already running" |
| TC-DF-T-11-005-06 | Edge | 0 campaign | Mở | Empty state + CTA "Create new" |
| TC-DF-T-11-005-07 | Edge | Campaign progress 100% nhưng có 1 device fail | Inspect | Badge fail + DLQ link |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** DF-T-11-006, DF-T-11-008.

**Phụ thuộc giữa Epic:** **DF-E-04** — campaign endpoints.

**Rủi ro:**

- **Aggregate progress slow with many devices:** server side aggregate.
- **Filter combo gây cardinality lớn:** lazy load + debounce.

**Phụ thuộc bên ngoài:** Service campaign DF-E-04.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: counter dispatch_from_ui.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-09](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Nhóm người dùng:** Social Data Operator, Automation Builder.
- **Thuật ngữ:** Campaign.
