# DF-T-06-012 — Artifact preview API (signed URL theo execution/step)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-06-012 |
| **Title** | Artifact preview API (signed URL theo execution/step) |
| **Type** | `type:feature` |
| **Epic** | DF-E-06 — Content Extraction & Artifact |
| **Module** | DF-MOD-06 — Content Extraction & Artifact |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:content`, `layer:backend`, `layer:contract`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `persona:automation-builder`, `coverage:L2`, `risk:auth` |
| **Truy vết — FR refs** | FR-06-12 |
| **Truy vết — UC refs** | UC-06-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module §5.1: "Artifact gắn execution id và step index; URL ký có thời hạn để truy cập an toàn." Social Data Operator dùng artifact để báo cáo cho khách hàng B2B "bài này extract lúc đó UI hiện ra sao". Automation Builder dùng artifact để debug step fail. Cả 2 use case đều cần một API:

1. List artifact theo execution (đã có ở DF-T-06-008 phần truy vấn — nhưng response không có URL).
2. Get signed URL cho 1 artifact để client GET trực tiếp từ MinIO/S3.
3. Stream binary nếu user không muốn signed URL.

Đặc tả module không cho client truy cập trực tiếp object_key (vì sẽ leak bucket layout) — phải qua signed URL với TTL.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mở artifact (screenshot, hierarchy snapshot) của một execution với 1 click trên dashboard
> **Để** kiểm chứng dữ liệu cho khách hàng B2B mà không phải truy cập trực tiếp object storage

Persona phụ: Automation Builder (debug step fail), Fleet Operator (xem device state lúc fail).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cung cấp `GET /api/executions/{id}/artifacts` trả danh sách artifact theo execution kèm metadata (kind, step_index, size, sha256, captured_at) — không kèm object_key, không kèm URL — trace FR-06-12.
- Hệ thống PHẢI cung cấp `GET /api/artifacts/{artifact_id}/url` trả `{url, expires_at, content_type, size_bytes}` với signed URL TTL ≤ 24h (mặc định 1h).
- Hệ thống PHẢI cung cấp `GET /api/artifacts/{artifact_id}/download` stream binary trực tiếp (proxy qua backend) cho client không hỗ trợ signed URL.
- Hệ thống PHẢI enforce authorization: user phải có quyền xem execution đó (cùng organization, owner hoặc role admin).
- Hệ thống PHẢI từ chối truy cập artifact đã bị xóa (`object_deleted=true`) với 410 Gone.
- Hệ thống PHẢI rate limit signed URL gen: 1000 URL / phút / user (chống abuse).
- Hệ thống PHẢI emit event `artifact_accessed` cho audit log.
- Hệ thống NÊN cung cấp `GET /api/executions/{id}/artifacts/preview-grid` trả URL signed của tất cả screenshot trong 1 lần gọi cho dashboard hiển thị grid timeline.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List + get signed URL**

```
Given execution E thuộc org X, có 40 artifact
And user U thuộc org X có role data-operator
When U GET /api/executions/E/artifacts
Then trả 40 entry với id, kind, step_index, size; KHÔNG có object_key
When U GET /api/artifacts/{first.id}/url
Then trả {url:"https://minio.../...?X-Amz-...", expires_at:NOW+1h, content_type:"image/png"}
And U có thể tải về 1 lần thành công
```

**AC-2: URL hết hạn**

```
Given signed URL có expires_at = NOW-10s
When client GET URL trực tiếp từ MinIO
Then trả 403 (MinIO native error)
And nếu client thử lại qua backend → backend gen URL mới
```

**AC-3: Cross-tenant**

```
Given execution E thuộc org X
When user U thuộc org Y GET /api/executions/E/artifacts
Then 404 (không leak existence)
And audit log "cross_tenant_attempt"
```

**AC-4: Artifact đã xóa**

```
Given artifact A có object_deleted=true
When user GET /api/artifacts/{A.id}/url
Then 410 Gone với message "Artifact deleted per retention policy"
And metadata vẫn xem được qua list endpoint nhưng kèm flag deleted
```

**AC-5: Rate limit**

```
Given user U gọi URL gen 1001 lần trong 60 s
When call thứ 1001
Then 429 RATE_LIMIT_EXCEEDED với Retry-After header
And audit log noted
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI render artifact (đó là DF-E-11).
- KHÔNG bao gồm video preview (chỉ static screenshot + XML hierarchy).
- KHÔNG bao gồm chia sẻ artifact ngoài organization (không có public link).
- KHÔNG bao gồm thumbnail generation (artifact lưu nguyên gốc PNG).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Service `ArtifactPreviewService.generate_signed_url(artifact_id, requester, ttl)`.
- [ ] Stream proxy endpoint (avoid large memory: stream chunk).
- [ ] Rate limit middleware per user.
- [ ] Auth check qua execution → organization.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 4 endpoint.
- [ ] Mã lỗi `ARTIFACT_DELETED`, `ARTIFACT_NOT_FOUND`, `RATE_LIMIT_EXCEEDED`.

**Documentation** (`layer:docs`)

- [ ] API reference artifact.
- [ ] Hướng dẫn dashboard sử dụng preview grid.

**Test** (`layer:test`)

- [ ] Integration test 4 endpoint.
- [ ] Test signed URL access từ ngoài (curl đến MinIO).
- [ ] Test rate limit.
- [ ] Test cross-tenant.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-06-012-01 | Positive | Execution E có 40 artifact; user same org | GET /executions/E/artifacts | 40 entry; không object_key |
| TC-DF-T-06-012-02 | Positive | Artifact A | GET /artifacts/A/url; sau đó GET URL từ curl | URL trả 200 + binary PNG; sha256 match |
| TC-DF-T-06-012-03 | Negative | User khác org | GET /executions/E/artifacts | 404 |
| TC-DF-T-06-012-04 | Negative | Artifact A đã deleted | GET /artifacts/A/url | 410 Gone |
| TC-DF-T-06-012-05 | Edge | URL expired 10s | GET URL từ curl | 403 từ MinIO; client refresh URL mới |
| TC-DF-T-06-012-06 | Edge | 1001 URL request / phút | Spam | 429 sau request thứ 1001 |
| TC-DF-T-06-012-07 | Edge | Stream download artifact 5 MB | GET /download | Stream chunked, không OOM, sha256 match |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-002 (data model), DF-T-06-011 (retention policy để biết deleted flag).

**Chặn:** DF-E-11 (UI mở artifact qua các endpoint này).

**Phụ thuộc giữa Epic:** DF-E-11 (Frontend dashboard sử dụng API).

**Rủi ro:**

- **Signed URL leak ra ngoài → ai có URL đều xem được:** giảm thiểu: TTL ngắn (1h default), audit log, hướng dẫn không share URL.
- **Rate limit không đủ chặt → abuse:** giảm thiểu: monitoring abnormal pattern, có thể tightening sau.

**Phụ thuộc bên ngoài:** MinIO/S3 signed URL support (presigned URL API).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] 4 endpoint qua integration test pass.
- [ ] Signed URL test với MinIO thật pass.
- [ ] OpenAPI publish.
- [ ] Telemetry: `artifact_url_gen_total{user_role}`, `artifact_download_bytes_total`, `artifact_access_denied_total{reason}`.
- [ ] Audit log entry "artifact_accessed" được tiêu thụ và lưu.
- [ ] Code review ≥ 1 approve owner module + 1 approve security (do signed URL).
- [ ] Changelog ghi nhận.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [06-content-extraction-artifacts.md §5.1, §6 FR-06-12](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Automation Builder (§3.2), Fleet Operator (§3.3).
- **Thuật ngữ:** [Artifact](../../official_docs/00-glossary.md), [MinIO / S3](../../official_docs/00-glossary.md).
- **Epic liên quan:** DF-E-11.
