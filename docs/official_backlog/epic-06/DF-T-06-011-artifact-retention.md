# DF-T-06-011 — Artifact retention policy & lifecycle (MinIO/S3)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-011 |
| **Title** | Artifact retention policy & lifecycle (MinIO/S3) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:infra`, `type:feature`, `platform:agnostic`, `persona:fleet-operator`, `coverage:L2`, `risk:data-loss` |
| **Truy vết — FR refs** | FR-06-12 |
| **Truy vết — UC refs** | UC-06-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module §8 ghi rõ: "Một campaign 1000 device với scenario 20 step sẽ tạo ~40,000 screenshot. Chính sách lưu trữ artifact theo execution có thể được cấu hình ở triển khai; cần rà soát chính sách giữ artifact (ví dụ giữ 30 ngày, sau đó archive hoặc xóa)." Chi phí object storage tăng nhanh nếu không có retention.

Ticket này dựng retention policy theo organization và theo execution status: artifact của execution success giữ ngắn hơn; artifact của execution fail giữ lâu hơn (vì cần debug); artifact của execution có gắn report cho khách hàng giữ theo policy riêng. Tự động chạy job dọn dẹp theo lifecycle.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** artifact được dọn dẹp tự động theo policy retention rõ ràng (ví dụ 30 ngày cho success, 90 ngày cho failed)
> **Để** chi phí object storage trong kiểm soát mà vẫn giữ evidence khi cần

Persona phụ: Social Data Operator (cần đảm bảo artifact của execution có report được giữ đủ lâu).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp config retention per organization:
  ```
  { artifact_retention: {
      execution_success: 30d,
      execution_failed: 90d,
      execution_pinned: -1 (không xóa),
      direct_extract: 7d
  } }
  ```
- Hệ thống PHẢI gán `retention_class` cho mỗi artifact lúc tạo (DF-T-06-002), dựa trên trạng thái execution / kind.
- Hệ thống PHẢI cung cấp endpoint `POST /api/executions/{id}/pin` để Social Data Operator "ghim" execution → artifact không bị xóa kể cả sau retention.
- Hệ thống PHẢI có job nền (Temporal hoặc cron) chạy daily quét artifact quá hạn và xóa cả object lẫn row `execution_artifacts`.
- Hệ thống PHẢI giữ row `execution_artifacts` (audit) trong 1 năm với cờ `object_deleted=true` thay vì xóa cứng — để truy vết.
- Hệ thống PHẢI emit event `artifact_deleted` cho audit.
- Hệ thống PHẢI hỗ trợ option archive (chuyển sang cold storage S3 Glacier) thay vì delete — config flag, mặc định delete.
- Hệ thống NÊN cung cấp dashboard số bytes / số object / cost ước tính per organization.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Cleanup artifact của execution success > 30 ngày**

```
Given org X có 1000 execution success, mỗi execution có 40 artifact, đã 31 ngày
And retention.execution_success = 30d
When daily cleanup job chạy
Then 40,000 artifact bị xóa object trên MinIO
And 40,000 row execution_artifacts có object_deleted=true
And event "artifact_deleted" emit 40,000 lần (batch nếu cần)
```

**AC-2: Pin execution không bị xóa**

```
Given execution E pinned bởi user U; đã 31 ngày sau retention
When cleanup job chạy
Then artifact của E không bị xóa
And UI hiện badge "Pinned by U at <ts>"
```

**AC-3: Cleanup không động vào execution failed mới 30 ngày**

```
Given org X có execution failed 30 ngày trước; retention.execution_failed = 90d
When cleanup job chạy
Then artifact của execution failed vẫn còn
And không có row execution_artifacts có object_deleted=true cho execution này
```

**AC-4: Override retention per organization**

```
Given org X custom retention.execution_success = 7d
When cleanup job chạy
Then artifact của org X success > 7 ngày bị xóa
And artifact của org khác vẫn theo default 30d
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm archive sang Glacier — chỉ delete ở phase này, archive là option flag chưa enable mặc định.
- KHÔNG bao gồm xóa content_item theo retention — chỉ artifact (content có lifecycle khác, do người dùng quản lý).
- KHÔNG bao gồm dashboard cost (chỉ metric thô) — đó là DF-E-09 hoặc DF-E-11 build trên metric.
- KHÔNG bao gồm xóa execution row — chỉ artifact object + flag deleted.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Config schema retention per org (lưu trong bảng `organization_settings`).
- [ ] Service `ArtifactRetentionService.evaluate_and_cleanup(batch_size, dry_run=false)`.
- [ ] Endpoint pin/unpin execution.
- [ ] Daily cron / Temporal workflow `artifact_retention_workflow`.
- [ ] Batch delete with rate limit để không quá tải MinIO.

**Contract / API** (`layer:contract`)

- [ ] Endpoint pin: `POST /api/executions/{id}/pin`, `DELETE /api/executions/{id}/pin`.
- [ ] Endpoint config retention: `PUT /api/organizations/{id}/settings/artifact_retention`.

**Database / Migration** (`layer:db`)

- [ ] Cột `pinned_at`, `pinned_by` ở bảng `executions`.
- [ ] Cột `object_deleted`, `object_deleted_at` trong `execution_artifacts`.
- [ ] Cột `retention_class` (xác định ở DF-T-06-002).

**Infra / DevOps** (`layer:infra`)

- [ ] Schedule cron daily 02:00 UTC.
- [ ] Alert nếu cleanup job fail.
- [ ] Bucket lifecycle rule fallback (MinIO/S3 native) cho trường hợp cron không chạy.

**Documentation** (`layer:docs`)

- [ ] Runbook "Artifact retention policy".
- [ ] Bảng default retention.

**Test** (`layer:test`)

- [ ] Dry-run test trên staging.
- [ ] Test pin/unpin.
- [ ] Test scenario org override.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-011-01 | Positive | 1000 execution success > 30 ngày | Chạy cleanup | Tất cả artifact bị xóa object; row giữ với flag |
| TC-DF-T-06-011-02 | Positive | Execution E pinned | Chạy cleanup sau 60 ngày | Artifact của E vẫn còn |
| TC-DF-T-06-011-03 | Negative | Execution failed 30 ngày (retention 90d) | Chạy cleanup | Artifact không bị xóa |
| TC-DF-T-06-011-04 | Negative | Config retention.execution_success = "abc" (sai format) | PUT settings | 422 INVALID_RETENTION_FORMAT |
| TC-DF-T-06-011-05 | Edge | Cleanup batch 1M artifact trong 1 lần | Job chạy | Batch chia 10k mỗi vòng; rate limit; không OOM; latency < 30 phút |
| TC-DF-T-06-011-06 | Edge | MinIO trả 503 lúc delete | Job | Retry exponential; alert nếu fail > 100 lần liên tiếp; không loop infinit |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-002 (bảng execution_artifacts có retention_class).

**Chặn:** Không.

**Phụ thuộc giữa Epic:** DF-E-09 (Notifications) có thể tiêu thụ event "artifact_deleted" để cảnh báo nếu cần.

**Rủi ro:**

- **Mất evidence khi user cần xem lại sau quá retention:** giảm thiểu: pin execution, archive option (lộ trình), tài liệu nhắc người dùng pin execution quan trọng.
- **Cleanup job fail im lặng:** giảm thiểu: healthcheck job, alert P2 nếu không chạy > 24h.
- **Bill tăng vọt trước khi retention enable:** giảm thiểu: enable trong release đầu tiên của Epic.

**Phụ thuộc bên ngoài:** MinIO/S3 delete API + IAM permission.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Cleanup job chạy thành công trên staging 7 ngày liên tục.
- [ ] Default retention applied cho mọi org chưa override.
- [ ] Runbook published.
- [ ] Telemetry: `artifact_cleanup_deleted_total`, `artifact_cleanup_bytes_freed`, `artifact_cleanup_duration_seconds`, `artifact_pinned_total`.
- [ ] Code review ≥ 1 approve owner module + 1 approve owner Infra.
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §6 FR-06-12, §8 "Artifact pre/post capture chi phí lưu trữ"](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Module KPI:** "Dung lượng artifact trung bình mỗi execution trong ngưỡng đã thỏa thuận".
- **Nhóm người dùng:** Fleet Operator (§3.3), Social Data Operator (§3.1).
- **Thuật ngữ:** [Artifact](../../official_docs/00-glossary.md), [MinIO / S3](../../official_docs/00-glossary.md).
