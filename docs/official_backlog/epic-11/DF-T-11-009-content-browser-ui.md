# DF-T-11-009 — Content browser UI — collection, filter, phân trang

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-009 |
| **Title** | Content browser UI — `/dashboard/content` collection + filter + phân trang |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-11-11 |
| **Truy vết — UC refs** | UC-11-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Social Data Operator export báo cáo từ content collection (hành trình giai đoạn 6). Họ cần browse content theo collection, filter platform / content_type / campaign / time range, phân trang khi dataset hàng chục nghìn item.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mở `/dashboard/content` browse content theo collection + filter kết hợp
> **Để** lọc đúng phân khúc cho khách hàng và export.

## 4. Yêu cầu chức năng

- Trang PHẢI list content item theo collection chọn — trace FR-11-11.
- Filter PHẢI kết hợp: platform, content_type, campaign, time range — trace FR-11-11.
- Phân trang PHẢI hỗ trợ với dataset > 10k — trace FR-11-11.
- Click item PHẢI mở content detail (DF-T-11-010) — trace FR-11-11.
- Breadcrumb truy vết về execution gốc — trace FR-11-11.
- Hỗ trợ multi-select + bulk export CSV (trong phạm vi browser, không phải BI).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List + filter**

```
Given collection C1 có 5000 content_item mix fb_post + tiktok_video
When filter platform=tiktok + content_type=tiktok_video
Then chỉ TikTok video
And count chính xác
```

**AC-2: Phân trang**

```
Given 5000 item
When user duyệt trang 1 → trang 50
Then mỗi trang load < 2 s
And không duplicate item giữa các trang
```

**AC-3: Breadcrumb truy vết**

```
Given content_item I1 phát sinh từ execution E1 của campaign C1
When user click breadcrumb
Then chuyển sang execution monitor E1
```

**AC-4: Bulk export CSV**

```
Given user multi-select 100 item
When click Export CSV
Then file CSV download với metadata truy vết (campaign id, device serial, account, time)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm content edit/delete — admin only API.
- KHÔNG bao gồm BI dashboard — lộ trình.
- KHÔNG bao gồm export định dạng khác CSV ở release này.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `content/`.
- [ ] Bảng virtual list + filter kết hợp.
- [ ] Bulk select + export.
- [ ] Breadcrumb truy vết.

**Contract / API** (`layer:contract`)

- [ ] Generated client cho content endpoints.
- [ ] Endpoint export CSV (server side).

**Documentation** (`layer:docs`)

- [ ] UX doc + format CSV.

**Test** (`layer:test`)

- [ ] E2E filter combo.
- [ ] Test bulk export.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-009-01 | Positive | 5000 item | List + filter | Subset đúng |
| TC-DF-T-11-009-02 | Positive | Page 1 → 50 | Duyệt | Không duplicate; mỗi trang < 2 s |
| TC-DF-T-11-009-03 | Positive | Bulk select 100 | Export | CSV chứa 100 row + metadata |
| TC-DF-T-11-009-04 | Negative | Collection org khác | Mở | Reject + audit cross-org |
| TC-DF-T-11-009-05 | Edge | Bulk select 10k | Export | Server stream CSV; không OOM client |
| TC-DF-T-11-009-06 | Edge | Filter trả 0 item | Apply | Empty state + suggestion |
| TC-DF-T-11-009-07 | Negative | Export API trả lỗi quyền hoặc retention expired | Export selected items | UI hiển thị lỗi rõ, không tải file rỗng hoặc file sai dữ liệu |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** DF-T-11-010.

**Phụ thuộc giữa Epic:** **DF-E-06**, **DF-E-04** (link execution).

**Rủi ro:**

- **Bulk export OOM:** server stream chunked.
- **Pagination với cursor không stable nếu data update:** cursor based + timestamp pin.

**Phụ thuộc bên ngoài:** Service content DF-E-06.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: histogram page_load_ms, counter export_csv.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-11](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator.
- **Thuật ngữ:** Content item, Collection.
