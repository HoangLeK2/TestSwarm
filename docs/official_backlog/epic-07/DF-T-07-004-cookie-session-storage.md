# DF-T-07-004 — Cookie / session secure storage (vault-ready)

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-07-004 |
| **Title** | Cookie / session secure storage (vault-ready abstraction) |
| **Type** | `type:feature` |
| **Epic** | DF-E-07 — Account & Account Group |
| **Module** | DF-MOD-07 — Account & Account Group |
| **Priority** | P2 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:accounts`, `layer:backend`, `layer:db`, `layer:contract`, `layer:infra`, `type:feature`, `platform:agnostic`, `persona:social-data-operator`, `coverage:L2`, `risk:auth`, `risk:legal-compliance` |
| **Truy vết — FR refs** | Lộ trình SPG-008 (vault-backed credential), FR-07-01 metadata isolation |
| **Truy vết — UC refs** | UC-07-01 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module §8 ghi nhận tại SPG-008: "credential (nếu lưu) nằm trong trường metadata của account dưới dạng JSON, không có vault tách biệt và không có mã hóa ở lớp ứng dụng." Đây là rủi ro lớn về compliance (GDPR, dữ liệu cá nhân) và bảo mật (credential plaintext trong DB dump). Ticket này dựng **abstraction vault-ready** để tách credential (cookie session, password placeholder) khỏi metadata thường, mã hóa ở lớp ứng dụng (envelope encryption với master key từ DF-E-01), và để ngỏ plug HashiCorp Vault sau này mà không phải migrate schema lần nữa.

Persona hưởng lợi: Social Data Operator (an tâm lưu cookie session không sợ leak), Platform Engineer (chuẩn cho audit compliance), Automation Builder (scenario login dùng API chuẩn, không truy thẳng JSONB).

Đặc tả module cũng cảnh báo: "Product intent nói rõ không khuyến khích thiết kế workflow xoay quanh credential plaintext" — ticket này hiện thực hóa khuyến nghị đó ở lớp hạ tầng.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** lưu cookie session, password placeholder, 2FA TOTP secret vào storage tách biệt với metadata thường, có mã hóa ở lớp ứng dụng
> **Để** không leak credential khi DB bị dump, không vi phạm policy compliance, và sẵn sàng migrate sang Vault không đổi API

Persona phụ: Platform Engineer (compliance audit), Automation Builder (scenario login API).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI có bảng `account_credentials(account_id, version, payload_ciphertext, key_id, iv, auth_tag, scheme, created_at, rotated_at)` tách khỏi bảng `accounts`.
- Hệ thống PHẢI hỗ trợ ít nhất 3 credential scheme: `cookie_session_v1`, `password_placeholder_v1`, `totp_secret_v1`. Schema từng scheme được khai báo trong code, không cho client gửi cấu trúc tự do — trace FR-07-01 metadata isolation.
- Hệ thống PHẢI mã hóa payload bằng envelope encryption: DEK random per record, mã hóa bằng KEK lưu trong KMS (DF-E-01); ciphertext + auth_tag lưu DB; plaintext không bao giờ lưu disk.
- Hệ thống PHẢI cung cấp endpoint:
  - `PUT /api/accounts/{id}/credentials/{scheme}` set credential (body plaintext, sẽ mã hóa server-side).
  - `GET /api/accounts/{id}/credentials/{scheme}/preview` trả masked preview (vd cookie domain + expiry, KHÔNG plaintext value).
  - `POST /api/accounts/{id}/credentials/{scheme}/rotate` xoay key (re-encrypt cùng plaintext với DEK mới).
  - `DELETE /api/accounts/{id}/credentials/{scheme}` xóa credential.
- Hệ thống PHẢI cung cấp internal API `resolve_credential(account_id, scheme)` cho dispatch / scenario step login — trả plaintext IN-MEMORY, không log, không persist trace.
- Hệ thống PHẢI KHÔNG bao giờ trả plaintext credential qua REST API public; chỉ resolve được qua internal API có scope `scenario_runtime` hoặc `vault_admin`.
- Hệ thống PHẢI audit mọi resolve credential (DF-T-07-011): user/service, account_id, scheme, timestamp, scope (KHÔNG log plaintext).
- Hệ thống PHẢI có driver abstraction: implementation `LocalKmsDriver` (default) + `VaultDriver` (stub) — chuyển sang Vault chỉ đổi config, không đổi API.
- Hệ thống PHẢI scan và reject nếu phát hiện cookie plaintext trong field metadata của bảng `accounts` (linter migration) — trace SPG-008.
- Hệ thống NÊN cung cấp metric `credential_resolve_total{scheme, scope}` cho audit.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Lưu cookie session — mã hóa thật sự**

```
Given user U có account A
When U PUT /api/accounts/{A.id}/credentials/cookie_session_v1 body {cookies:[{name,value,domain,expiry}]}
Then trả 200, response không chứa plaintext value
And bảng account_credentials có row mới với payload_ciphertext ≠ plaintext
And query trực tiếp DB không thấy plaintext cookie
```

**AC-2: Preview masked**

```
Given account A có cookie session lưu
When U GET /api/accounts/{A.id}/credentials/cookie_session_v1/preview
Then trả {domains:["facebook.com"], cookie_count:5, expires_at:"2026-..."}
And KHÔNG có field "value" trong response
```

**AC-3: Resolve internal trả plaintext — không log**

```
Given dispatch service có scope "scenario_runtime"
When service resolve_credential(account_id=A, scheme="cookie_session_v1")
Then trả plaintext cookies in-memory
And audit log entry "credential_resolved" có account_id, scope, KHÔNG có plaintext value
And application log không chứa plaintext (verify qua grep)
```

**AC-4: Public API KHÔNG trả plaintext**

```
Given account A có credential
When external client GET /api/accounts/{A.id}/credentials/cookie_session_v1
Then trả 405 METHOD_NOT_ALLOWED hoặc 403
And không bao giờ trả plaintext qua public REST
```

**AC-5: Rotate key — re-encrypt**

```
Given account A có credential lưu với key_id=v1
When admin POST /credentials/cookie_session_v1/rotate
Then re-encrypt với DEK mới, key_id chuyển sang v2
And plaintext không đổi (verify qua resolve_credential trả cùng kết quả)
And bảng có 2 row (version cũ giữ N ngày cho rollback rồi GC)
```

**AC-6: Linter reject credential trong metadata**

```
Given migration check chạy
When phát hiện row accounts.metadata chứa field "cookie", "password", "session"
Then migration báo lỗi với hướng dẫn move sang account_credentials
And CI fail nếu PR thêm credential vào metadata
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm Vault production deployment — chỉ stub driver, deploy thật ở DF-T-01-XXX.
- KHÔNG bao gồm 2FA flow tự động (TOTP code generation runtime) — Automation Builder tự code trong scenario; module này chỉ lưu TOTP secret.
- KHÔNG bao gồm cookie auto-refresh khi platform expire — ngoài phạm vi module (xem §3.2 đặc tả module).
- KHÔNG bao gồm captcha solving — ngoài phạm vi module.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Driver abstraction `CredentialStorageDriver` interface.
- [ ] `LocalKmsDriver` implementation (envelope encryption AES-GCM).
- [ ] `VaultDriver` stub (chỉ interface, throw NotImplemented khi gọi).
- [ ] Service `CredentialService` set / preview / rotate / delete / resolve.
- [ ] Internal API gRPC hoặc internal HTTP cho dispatch.
- [ ] Audit hook → DF-T-07-011.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI 4 endpoint public.
- [ ] Proto internal `ResolveCredential`.
- [ ] Schema JSON cho 3 scheme.
- [ ] Mã lỗi `CREDENTIAL_NOT_FOUND`, `SCHEME_NOT_SUPPORTED`, `KMS_UNAVAILABLE`.

**Database / Migration** (`layer:db`)

- [ ] Migration bảng `account_credentials`.
- [ ] Linter migration: scan `accounts.metadata` cho credential pattern.

**Infra / DevOps** (`layer:infra`)

- [ ] KEK lưu trong KMS (config từ DF-E-01).
- [ ] Secret rotation runbook.

**Documentation** (`layer:docs`)

- [ ] "How to store cookie session" guide.
- [ ] Compliance doc: GDPR mapping cho credential storage.
- [ ] Cập nhật đặc tả module §8 SPG-008 status.

**Test** (`layer:test`)

- [ ] Unit test envelope encryption.
- [ ] Test resolve không log plaintext (grep log).
- [ ] Test rotate giữ plaintext không đổi.
- [ ] Test public API không leak.
- [ ] Penetration test: dump DB → không có plaintext.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-07-004-01 | Positive | Account A; KMS available | PUT cookie_session_v1 với 5 cookies | 200; row tạo; ciphertext ≠ plaintext |
| TC-DF-T-07-004-02 | Positive | Credential đã lưu | GET preview | Trả masked (domain, count, expiry), không có value |
| TC-DF-T-07-004-03 | Positive | Internal scope scenario_runtime | resolve_credential | Plaintext trả in-memory; audit log entry; log application clean |
| TC-DF-T-07-004-04 | Negative | External client | GET /credentials với scope public | 403 / 405 |
| TC-DF-T-07-004-05 | Negative | KMS unavailable | PUT credential | 503 KMS_UNAVAILABLE; không lưu plaintext |
| TC-DF-T-07-004-06 | Edge | Rotate key | POST rotate; resolve | Plaintext không đổi; key_id mới |
| TC-DF-T-07-004-07 | Edge | DB dump → grep plaintext | Sau khi 100 credential lưu | Không xuất hiện plaintext cookie value |
| TC-DF-T-07-004-08 | Edge | PR thêm credential vào metadata | CI lint | CI fail với message rõ |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-07-001 (account model), DF-E-01 (KMS / master key).

**Chặn:** DF-T-07-007 (resolve credential trong dispatch), DF-T-07-005 (state suspended/cooldown có thể dùng credential health check).

**Phụ thuộc giữa Epic:** DF-E-01 cung cấp KMS abstraction + master key rotation; DF-E-04 (dispatch) consume internal resolve API.

**Rủi ro:**

- **KMS outage chặn dispatch:** giảm thiểu: short TTL cache plaintext trong dispatch worker (15 phút) với secure memory; circuit breaker.
- **Migration credential từ metadata cũ:** giảm thiểu: tool migrate có dry-run; chạy theo org, rollback được.
- **Vault stub bị nhầm là production-ready:** giảm thiểu: stub throw exception rõ ràng; doc nhắc chỉ dùng LocalKmsDriver trong release này.
- **Compliance bị audit yêu cầu xóa credential cụ thể:** giảm thiểu: API DELETE credential hard-delete row ngay, không soft-delete.

**Phụ thuộc bên ngoài:** DF-E-01 KMS; HashiCorp Vault (tương lai, chỉ stub trong release này).

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Unit test coverage ≥ 85% (security-critical).
- [ ] Test plaintext không xuất hiện trong DB dump, log application, audit log.
- [ ] 4 endpoint public + internal API qua integration test.
- [ ] Documentation "How to store cookie session" published.
- [ ] Compliance doc GDPR mapping ký bởi product + legal proxy.
- [ ] Telemetry `credential_resolve_total{scheme,scope}`, `credential_rotate_total`, `kms_unavailable_total` published.
- [ ] Code review ≥ 1 owner module + 1 security reviewer.
- [ ] Penetration test pass: DB dump không leak plaintext.
- [ ] Đặc tả module §8 SPG-008 cập nhật trạng thái "MVP shipped, Vault driver Lộ trình".
- [ ] Changelog ghi nhận breaking change: scenario login không đọc metadata.cookies nữa.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [07-accounts-and-groups.md §8 SPG-008](../../official_docs/modules/07-accounts-and-groups.md).
- **Nhóm người dùng:** Social Data Operator (§3.1), Platform Engineer (§3.4).
- **Thuật ngữ:** [Account](../../official_docs/00-glossary.md), Credential, Session cookie.
- **Epic liên quan:** DF-E-01 cho KMS; DF-E-04 cho dispatch resolve.
