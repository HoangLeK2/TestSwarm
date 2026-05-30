# DF-T-01-013 — API rate-limit foundation

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-013 |
| **Title** | API rate-limit foundation — middleware, budget per user/IP/endpoint |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P3 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:contract`, `layer:infra`, `type:feature`, `risk:performance` |
| **Truy vết — FR refs** | FR-01-12, FR-01-13; Lộ trình: Rate limit trung ương cho REST API |
| **Truy vết — UC refs** | UC-01-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 ghi: *"Mỗi route nghiệp vụ tự quản lý mức tải của mình; chưa có lớp rate limit trung ương cho toàn bộ REST API."* Đây là lỗ hổng nếu một tổ chức khách hàng lạm dụng API hoặc bị compromise (key rò). Ticket build **foundation** — không phải policy đầy đủ cho mọi endpoint, mà là khung middleware + storage để mỗi ticket Epic sau có thể khai báo `@rate_limit(...)` thống nhất.

Phạm vi: (1) middleware token-bucket dùng Redis làm backend; (2) decorator `@rate_limit(budget="100/min", key="user")` cho route khai báo; (3) global default cho endpoint nhạy cảm (auth, invite); (4) response 429 với header `Retry-After`, `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`; (5) admin bypass tùy chọn (system account); (6) metric expose.

Default policy ở M1: auth endpoint 30 req/min per IP, invite 10/h per admin, refresh 60/min per user, các endpoint khác chưa cap. Hardening đầy đủ defer ticket riêng sau khi có traffic profile thực tế.

P2 vì không hard-block release, nhưng cần trước khi public-facing đầu tiên.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** có middleware rate-limit thống nhất tôi có thể áp dụng decorator vào route
> **Để** một abuser không kéo sập service và team nghiệp vụ không phải tự dựng lại logic

> **Là** Admin tổ chức
> **Tôi muốn** biết khi mình đang gần giới hạn rate
> **Để** điều chỉnh client integration không bị 429

## 4. Yêu cầu chức năng

- Hệ thống PHẢI middleware `RateLimitMiddleware` áp dụng theo decorator hoặc config per-route.
- Hệ thống PHẢI hỗ trợ key strategy: `user` (CurrentUser.id), `ip` (client IP), `org` (org_id), `device` (CurrentDevice.id), combination (`user+endpoint`).
- Hệ thống PHẢI hỗ trợ budget format: `<N>/<window>` với window ∈ {sec, min, hour, day}.
- Hệ thống PHẢI backend storage Redis với atomic increment + expire.
- Hệ thống PHẢI khi vượt budget → response 429 TOO_MANY_REQUESTS với headers:
  - `Retry-After: <seconds>`
  - `X-RateLimit-Limit: <N>`
  - `X-RateLimit-Remaining: 0`
  - `X-RateLimit-Reset: <unix_ts>`
- Hệ thống PHẢI mọi response (cả 200) thêm 3 header `X-RateLimit-*` nếu route có rate-limit.
- Hệ thống PHẢI fallback graceful khi Redis down: log error, **không reject request** (fail-open) nhưng emit metric `rate_limit.backend_down`.
- Hệ thống PHẢI default policy cho 3 endpoint nhạy cảm: `/api/auth/login` (30/min per IP), `/api/admin/members/invite` (10/h per admin), `/api/auth/refresh` (60/min per user).
- Hệ thống PHẢI admin platform có thể bypass với header `X-Bypass-Rate-Limit: <admin_token>` — chỉ cho internal tooling.
- Hệ thống PHẢI emit audit event `rate_limit.exceeded` với endpoint, key, key_value.
- Hệ thống PHẢI metric: `rate_limit.allowed.count`, `rate_limit.rejected.count`, `rate_limit.backend_down`.
- Hệ thống NÊN cho phép override budget per-org (vd enterprise plan có budget cao hơn).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Login endpoint áp dụng 30/min per IP**

```
Given IP X gửi 30 POST /api/auth/login trong 60s
When IP X gửi request thứ 31
Then response 429 TOO_MANY_REQUESTS
And headers: Retry-After, X-RateLimit-Limit=30, X-RateLimit-Remaining=0
And audit log "rate_limit.exceeded" với endpoint, key="ip:X"
And metric rate_limit.rejected.count tăng
```

**AC-2: Request bình thường có rate-limit header**

```
Given IP Y gửi 5 POST /api/auth/login trong 60s
When IP Y gửi request thứ 6
Then response 401 (do credential sai) hoặc 200 (đúng)
And headers: X-RateLimit-Limit=30, X-RateLimit-Remaining=24 (30-6)
```

**AC-3: Invite endpoint 10/h per admin**

```
Given bob admin gửi 10 invite trong 1 giờ
When bob gửi lần 11
Then 429 TOO_MANY_REQUESTS
And key="user:bob" trong audit
```

**AC-4: Decorator áp dụng đúng**

```
Given route /api/test có @rate_limit(budget="5/min", key="user+endpoint")
When alice gọi route đó 5 lần trong 60s
And gọi lần 6
Then lần 6 trả 429
And bob (user khác) vẫn được gọi vì key user+endpoint khác
```

**AC-5: Redis down — fail-open**

```
Given Redis backend bị disconnect
When client gửi request đến route có rate-limit
Then request được phục vụ bình thường (không reject)
And metric rate_limit.backend_down counter tăng
And log warning "Rate limit backend unavailable; failing open"
```

**AC-6: Admin bypass với token**

```
Given internal monitoring tool có ADMIN_BYPASS_TOKEN config
When tool gửi GET /api/some-endpoint với header X-Bypass-Rate-Limit: <correct_token>
Then rate-limit không kiểm tra cho request đó
And audit log "rate_limit.bypassed" với tool identity
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm rate-limit policy cho mọi endpoint (chỉ 3 default + framework) — Epic owner tự áp.
- KHÔNG bao gồm quota plan (free/standard/enterprise budget khác nhau) — defer.
- KHÔNG bao gồm WAF integration (Cloudflare, AWS WAF) — DevOps layer.
- KHÔNG bao gồm distributed rate-limit cho cluster mode — Redis single-instance OK ở M1 vì counter centralized.
- KHÔNG bao gồm sliding window log algorithm — token bucket đủ cho M1.
- KHÔNG bao gồm rate-limit cho WebSocket message — defer.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/rate_limit/middleware.py`.
- [ ] Module `device_farm/rate_limit/redis_store.py` — atomic Lua script INCR + EXPIRE.
- [ ] Decorator `@rate_limit(budget, key, ...)`.
- [ ] Header injector cho response.
- [ ] Áp dụng default policy cho 3 endpoint.
- [ ] Admin bypass logic với secret comparison constant-time.

**Frontend** (`layer:frontend`)

- [ ] Hiển thị message "Bạn đang gửi yêu cầu quá nhanh, đợi {n}s" khi 429.
- [ ] Backoff client tự động retry với jitter.

**Contract / API** (`layer:contract`)

- [ ] Mã lỗi TOO_MANY_REQUESTS.
- [ ] Document header X-RateLimit-* trong OpenAPI per-route.

**Database / Migration** (`layer:db`)

- [ ] Không có.

**Infra / DevOps** (`layer:infra`)

- [ ] Redis deploy (helm subchart hoặc dependency).
- [ ] Helm value `rate_limit.enabled` (default true), `rate_limit.redis_url`.
- [ ] Helm value cho budget của 3 default endpoint.
- [ ] Secret cho ADMIN_BYPASS_TOKEN.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Rate Limit".
- [ ] Catalog default policy.
- [ ] Guide cho Epic owner: "Cách thêm rate-limit cho route mới".

**Test** (`layer:test`)

- [ ] Unit test atomic Lua script.
- [ ] Integration test 6 AC.
- [ ] Test concurrent burst 100 request → đúng N được phục vụ.
- [ ] Test Redis down fail-open.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-013-01 | Positive | IP X dưới budget login | Gọi /api/auth/login lần 5 trong 60s | 200/401 tùy credential; header X-RateLimit-Remaining=25 |
| TC-DF-T-01-013-02 | Positive | bob admin gửi 5 invite | POST invite | 201, X-RateLimit-Remaining=5 |
| TC-DF-T-01-013-03 | Positive | Route /api/test có @rate_limit(5/min, key=user); alice gọi 3 lần | Gọi tiếp | 200, Remaining=2 |
| TC-DF-T-01-013-04 | Negative | IP X đã 30 login trong 60s | Request 31 | 429, Retry-After, audit entry |
| TC-DF-T-01-013-05 | Negative | bob đã 10 invite trong 1h | POST invite 11 | 429, key=user:bob trong audit |
| TC-DF-T-01-013-06 | Negative | alice gọi route /api/test đã 5 lần | Request 6 | 429 |
| TC-DF-T-01-013-07 | Edge | Redis down | Gọi route có rate-limit | 200 (fail-open); metric backend_down++; log warning |
| TC-DF-T-01-013-08 | Edge | 100 concurrent request login từ cùng IP trong 1s | Bắn 100 req | Đúng ≤ 30 được 200/401; ≥ 70 trả 429; counter atomic |
| TC-DF-T-01-013-09 | Edge | Admin bypass token đúng | GET với X-Bypass-Rate-Limit | Không count, response bình thường; audit rate_limit.bypassed |
| TC-DF-T-01-013-10 | Edge | Admin bypass token sai | GET với token sai | Rate-limit vẫn áp; audit rate_limit.bypass_attempt_failed (security log) |
| TC-DF-T-01-013-11 | Edge | Reset window đúng giờ | Budget 30/min, sau 60s | Counter reset 0; request được phục vụ lại |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime), DF-T-01-002 (CurrentUser cho key=user).

**Chặn:** DF-T-01-009 (invite cần rate-limit, ticket đó reference middleware này).

**Phụ thuộc giữa Epic:** Mọi Epic sau có thể áp dụng decorator này.

**Rủi ro:**

- **R1 — Redis bottleneck.** Giảm thiểu: Lua script atomic + pipeline batch.
- **R2 — Fail-open bị abuse khi Redis cố tình bị tấn công down.** Giảm thiểu: alert SRE khi backend_down counter tăng đột biến; fallback to in-memory rate-limit per pod (best-effort).
- **R3 — Clock skew giữa pod gây counter window sai.** Giảm thiểu: Redis là single source of truth; pod chỉ gọi Redis.
- **R4 — Admin bypass token rò.** Giảm thiểu: token trong Kubernetes Secret; rotation qua DF-T-01-006 framework.

**Phụ thuộc bên ngoài:** Redis ≥ 6 (Lua script support), `redis-py` library.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85%.
- [ ] 11 test case automation.
- [ ] Redis deploy trên staging.
- [ ] Default policy active cho 3 endpoint.
- [ ] Guide "thêm rate-limit cho route mới" reviewed bởi Epic owner.
- [ ] Telemetry: 3 metric core, dashboard "API rate limit" deploy.
- [ ] Performance: middleware overhead < 5ms p99 per request.
- [ ] Load test concurrent 100 request → counter chính xác.
- [ ] Audit log đầy đủ.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — mục 7 lộ trình "Rate limit trung ương", mục 8 ghi chú "tạm thời dựa vào reverse proxy".
- **Ma trận năng lực:** "Rate limit trung ương cho REST API" — Lộ trình; ticket này delivers foundation.
- **Nhóm người dùng:** Platform Engineer, Admin tổ chức.
- **Thuật ngữ:** N/A.
- **Standards:** RFC 6585 (429), draft-ietf-httpapi-ratelimit-headers.
