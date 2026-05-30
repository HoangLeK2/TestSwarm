# DF-T-11-010 — Content detail + artifact preview UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-010 |
| **Title** | Content detail UI — payload view + artifact preview (screenshot, hierarchy) |
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

Khi khách hàng hỏi "bài này lấy từ đâu", Social Data Operator phải mở được evidence: payload content + screenshot + hierarchy capture lúc thu thập. Trang content detail là entry point cho câu hỏi này (pain point persona 3.1).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mở content item thấy payload đầy đủ + artifact preview (screenshot, hierarchy)
> **Để** trả lời khách hàng truy vết nguồn dữ liệu chính xác.

## 4. Yêu cầu chức năng

- Trang `/dashboard/content/{id}` PHẢI hiển thị: payload JSON formatted, metadata (campaign, execution, account, device, time), artifact list — trace FR-11-11.
- Artifact preview PHẢI hỗ trợ: image (screenshot), XML/JSON (hierarchy), text — trace FR-11-11.
- Download artifact gốc PHẢI khả dụng.
- Breadcrumb truy vết về campaign + execution + device.
- Hiển thị badge content_type platform-qualified.
- Hỗ trợ copy permalink content cho khách hàng (token-protected link, không public).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Hiển thị payload + artifact**

```
Given content I1 có payload + 2 artifact (1 screenshot, 1 hierarchy)
When user mở /dashboard/content/I1
Then payload JSON pretty-printed
And 2 artifact preview render
And metadata đầy đủ
```

**AC-2: Download artifact gốc**

```
Given artifact A1 screenshot
When user click Download
Then file PNG download với tên có content_id + timestamp
```

**AC-3: Breadcrumb truy vết**

```
Given content I1 từ execution E1 của campaign C1
When user click breadcrumb campaign
Then chuyển sang campaign C1
```

**AC-4: Permalink token-protected**

```
Given user click "Copy permalink"
When permalink mở ở browser khác chưa login
Then bounce login + sau login mở đúng content
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm edit payload (read-only).
- KHÔNG bao gồm annotation / tagging — backlog.
- KHÔNG bao gồm video player cho artifact video lớn — backlog.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Trang detail layout.
- [ ] Component preview screenshot / hierarchy / text.
- [ ] Download action + permalink copy.

**Contract / API** (`layer:contract`)

- [ ] Generated client content + artifact.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] Test render artifact types.
- [ ] Test permalink protect.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-010-01 | Positive | Content có 2 artifact | Mở | Render đầy đủ |
| TC-DF-T-11-010-02 | Positive | Click download | Download | File OK |
| TC-DF-T-11-010-03 | Positive | Click breadcrumb | Navigate | Đến campaign |
| TC-DF-T-11-010-04 | Negative | Artifact đã hết hạn / xóa | Mở | Placeholder "artifact expired" thay vì broken image |
| TC-DF-T-11-010-05 | Negative | Content cross-org | Mở | 403 + redirect |
| TC-DF-T-11-010-06 | Edge | Hierarchy XML 5 MB | Render | Lazy load + virtual scroll, không freeze |
| TC-DF-T-11-010-07 | Positive | Permalink token-protect | Mở ở browser khác | Bounce login + sau login OK |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-009.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-06**.

**Rủi ro:**

- **Artifact lớn:** lazy load + render virtual.
- **Permalink leak:** token-protected + audit.

**Phụ thuộc bên ngoài:** Artifact store DF-E-06.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: counter artifact_download.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-11](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator.
- **Thuật ngữ:** Content item, Artifact.
