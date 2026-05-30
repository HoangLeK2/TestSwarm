# DF-T-01-001 — Helm chart skeleton & runtime lifecycle

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-001 |
| **Title** | Helm chart skeleton & runtime lifecycle (mount 4 auth boundary) |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:infra`, `layer:backend`, `layer:contract`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-08, FR-01-11, FR-01-12 |
| **Truy vết — UC refs** | UC-01-05, UC-01-06, UC-01-09 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là ticket nền móng đầu tiên của toàn bộ sản phẩm. Trước khi bất kỳ logic nghiệp vụ nào (device, campaign, content) có thể được build, hệ thống cần một **runtime entrypoint thống nhất** chịu trách nhiệm: khởi động tiến trình FastAPI, mount đúng các nhóm route vào đúng auth boundary (public / user-auth / admin-auth / device-auth), khởi tạo kênh WebSocket gốc, và xuất bản OpenAPI spec làm chân lý API. Đồng thời, runtime phải triển khai được dưới dạng helm chart trên Kubernetes — đây là cách team release sản phẩm cho khách hàng B2B.

Persona hưởng lợi trực tiếp là **Platform Engineer** — họ là người gắn module mới vào đúng boundary và đồng bộ OpenAPI với frontend. Pain point hiện tại: chưa có khung deploy thống nhất, mỗi lần thêm route phải copy-paste mount logic, dễ "vô tình public" một endpoint admin. Ticket này giải bằng cách định nghĩa một **router registry** với chỉ 4 boundary và một CI check chặn route không khai báo boundary.

Trong sơ đồ luồng đặc tả module mục 5.1, ticket này sở hữu phần "Endpoint login công khai", "Route user-auth gắn dưới /api", "Route admin-auth", và "Route runtime" — tức là toàn bộ điểm vào trước khi vào logic nghiệp vụ. Ưu tiên P0 vì mọi Epic khác phải đợi helm chart deploy được lên môi trường dev trước khi bắt đầu.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** có một helm chart và runtime entrypoint thống nhất, mount route theo 4 auth boundary tách biệt, xuất OpenAPI spec tự động và phục vụ WebSocket gốc
> **Để** team nghiệp vụ có một nền tảng deploy-được, không bao giờ vô tình public một route admin, và frontend có spec đáng tin cậy để sinh client

Persona phụ: toàn bộ team — không ai có thể deploy nếu chart không sẵn.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI khởi động FastAPI app với 4 router gốc: `public_router`, `user_router` (gắn `/api`), `admin_router` (gắn `/api/admin`), `device_router` (gắn `/api/device`) — trace FR-01-12.
- Hệ thống PHẢI từ chối merge nếu một route mới không khai báo `boundary=` ở decorator (CI check) — trace FR-01-12.
- Hệ thống PHẢI xuất OpenAPI spec tại `/openapi.json` phản ánh đúng route hiện tại — trace FR-01-08.
- Hệ thống PHẢI cung cấp WebSocket entrypoint tại `/ws` nhận JWT để xác thực, từ chối kết nối không kèm JWT — trace FR-01-11 (auth thực sự ở DF-T-01-012, ticket này lo entrypoint).
- Hệ thống PHẢI có helm chart `device-farm-runtime` với value cho image, replica, env, secret refs, ingress.
- Hệ thống PHẢI có lifecycle hook (`startup`, `shutdown`) chạy ordered: load config → connect DB → mount router → ready.
- Hệ thống PHẢI publish OpenAPI spec dưới dạng artifact CI để frontend regenerate TypeScript client từ artifact đó.
- Hệ thống NÊN có endpoint `/api/server/version` trả version, commit hash, build time (public).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Deploy thành công helm chart trên cluster dev**

```
Given helm chart "device-farm-runtime" đã được push lên chart repo
And cluster dev có namespace device-farm-dev
When team chạy "helm install runtime device-farm/device-farm-runtime -n device-farm-dev"
Then chart deploy thành công trong < 90 s
And tất cả pod READY 1/1
And service expose port 8000 trong cluster
And ingress trả 200 ở "/health"
```

**AC-2: Mount đúng 4 auth boundary**

```
Given runtime đã khởi động
When team gọi "GET /openapi.json"
Then mỗi path trong spec có tag boundary chính xác (public | user-auth | admin-auth | device-auth)
And không tồn tại path nào không có tag boundary
And CI route-matrix script confirm tất cả route đã khai báo
```

**AC-3: Route không khai báo boundary bị CI reject**

```
Given developer thêm route mới "@router.get('/api/secret-stuff')" mà không khai báo boundary=
When PR được push
Then CI fail tại bước "router-boundary-check"
And error message chỉ rõ file, route, lý do reject
And PR không thể merge cho đến khi developer thêm boundary
```

**AC-4: WebSocket entrypoint từ chối kết nối không JWT**

```
Given runtime đã khởi động
When client mở kết nối WebSocket tới "/ws" không kèm Authorization header
Then server đóng kết nối ngay với close code 4401
And event "ws.auth.rejected" được log với client IP
```

**AC-5: OpenAPI spec được xuất làm artifact CI**

```
Given PR merge vào nhánh main
When CI pipeline chạy job "publish-openapi"
Then artifact "openapi.json" được upload lên artifact store
And version artifact gắn với commit hash
And job downstream "generate-ts-client" download và build thành công
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm logic JWT cấp/verify — thuộc DF-T-01-002.
- KHÔNG bao gồm RBAC enforcement chi tiết — thuộc DF-T-01-003.
- KHÔNG bao gồm WebSocket auth thật (JWT decode trong handshake) — DF-T-01-012 lo phần auth + session lifecycle.
- KHÔNG bao gồm secret management (lưu, rotate) — thuộc DF-T-01-006.
- KHÔNG bao gồm rate limit — thuộc DF-T-01-013.
- KHÔNG bao gồm cấu hình ingress TLS cấp production — chỉ lo dev/staging trong ticket này; production hardening sẽ là ticket tech-debt riêng.
- KHÔNG bao gồm sinh TypeScript client (build và publish package) — thuộc ticket riêng trong DF-E-11 (frontend).

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Tạo module `device_farm/runtime/app_factory.py` lắp ráp FastAPI app.
- [ ] Định nghĩa 4 router gốc với prefix và tag tương ứng.
- [ ] Implement decorator `@boundary(...)` để route khai báo boundary tường minh.
- [ ] Lifecycle hook `startup` / `shutdown` ordered: config → DB ping → mount → ready.
- [ ] Endpoint `/api/server/version` trả version metadata.
- [ ] WebSocket entrypoint `/ws` skeleton (đóng kết nối nếu thiếu Authorization).

**Frontend** (`layer:frontend`)

- [ ] (Out of scope chi tiết — chỉ check rằng generated client từ artifact build được, sẽ implement đầy đủ ở DF-E-11.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI generator config (title, version, license, server URL).
- [ ] Tag taxonomy: `public`, `user-auth`, `admin-auth`, `device-auth`.
- [ ] Documentation spec endpoint `/api/server/version`.

**Database / Migration** (`layer:db`)

- [ ] (Không có migration ở ticket này — DB ping chỉ là healthcheck; bảng nghiệp vụ ở ticket khác.)

**Infra / DevOps** (`layer:infra`)

- [ ] Tạo helm chart `charts/device-farm-runtime` với values.yaml mặc định.
- [ ] Define Deployment, Service, Ingress, ConfigMap, ServiceAccount.
- [ ] CI job `publish-openapi` upload artifact.
- [ ] CI script `router-boundary-check` parse OpenAPI và fail nếu thiếu boundary tag.
- [ ] Helm chart README + values mẫu cho dev/staging/prod.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` — mô tả router registry, lifecycle.
- [ ] `docs/runbooks/deploy.md` — quy trình helm install/upgrade.
- [ ] Cập nhật `docs/official_docs/modules/01-platform-runtime-and-access.md` nếu phát hiện chênh.
- [ ] Changelog M1 ghi "runtime entrypoint sẵn sàng".

**Test** (`layer:test`)

- [ ] Unit test cho `boundary` decorator (parse đúng metadata).
- [ ] Integration test: deploy chart lên kind cluster, gọi /health.
- [ ] Test CI route-matrix script với fixture route thiếu boundary.
- [ ] E2E test: regenerate OpenAPI và diff với file commited; fail nếu khác.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-001-01 | Positive | Helm chart đã build, cluster kind sẵn sàng | `helm install runtime ./charts/device-farm-runtime -n df-test` | Chart deploy < 90 s, pod READY, `GET /health` trả 200 |
| TC-DF-T-01-001-02 | Positive | Runtime đã chạy | `GET /openapi.json`; parse spec | Spec có > 0 path, mỗi path có tag boundary thuộc {public, user-auth, admin-auth, device-auth} |
| TC-DF-T-01-001-03 | Positive | PR thêm route mới có `@boundary("admin-auth")` | Push PR | CI job `router-boundary-check` pass |
| TC-DF-T-01-001-04 | Negative | PR thêm route mới thiếu decorator `@boundary` | Push PR | CI job `router-boundary-check` fail, error message chỉ rõ file:line:route_name |
| TC-DF-T-01-001-05 | Negative | Runtime đã chạy | Mở kết nối WebSocket tới `/ws` không có Authorization header | Server đóng kết nối với close code 4401 trong < 1 s |
| TC-DF-T-01-001-06 | Edge | Cluster dev có giả lập DB chậm (probe response > 5 s) | Khởi động pod | Lifecycle startup hook chờ DB sẵn sàng có timeout 30 s, fail rõ ràng nếu vượt; pod restart theo policy |
| TC-DF-T-01-001-07 | Edge | Helm upgrade khi pod cũ vẫn đang phục vụ traffic | `helm upgrade` với new image | Rolling update không có downtime, /health luôn trả 200 từ ít nhất 1 pod |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** Không.

**Chặn:** DF-T-01-002 (JWT auth — cần runtime mount), DF-T-01-007 (health & safe mode — cần lifecycle), DF-T-01-008 (observability — cần entrypoint), DF-T-01-013 (rate-limit — cần app factory), toàn bộ ticket DF-E-02 và DF-E-03 (cần môi trường deploy).

**Phụ thuộc giữa Epic:** Block DF-E-02 và DF-E-03 (môi trường runtime), block DF-E-11 (frontend cần OpenAPI artifact).

**Rủi ro:**

- **R1 — Helm chart bị bloat khi thêm Epic mới.** Giảm thiểu: values.yaml chia subchart theo module sau khi M1 close.
- **R2 — OpenAPI spec drift giữa code và file commit.** Giảm thiểu: CI bắt buộc regenerate và diff; PR không merge được nếu drift.
- **R3 — Lifecycle ordering sai gây race condition lúc startup.** Giảm thiểu: integration test cho cold start với DB chậm.

**Phụ thuộc bên ngoài:** Kubernetes ≥ 1.27, Helm ≥ 3.12, Python 3.11+, FastAPI ≥ 0.110, OpenAPI 3.1.

## 10. Điều kiện hoàn thành

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% cho `device_farm/runtime/app_factory.py` và `boundary` decorator.
- [ ] TC-DF-T-01-001-01 → 07 đã được map sang test tự động (kind cluster + integration test).
- [ ] `docs/modules/platform-runtime.md` cập nhật.
- [ ] `docs/runbooks/deploy.md` đã có quy trình helm install/upgrade/rollback.
- [ ] Telemetry: log có request-id (chuẩn bị cho DF-T-01-008), metric `app.startup.duration_ms` đã expose.
- [ ] Code review có ≥ 1 approve từ Platform Engineer lead.
- [ ] Changelog M1 ghi rõ.
- [ ] Helm chart đã được install thành công trên cluster dev và staging, /health pass ≥ 24h.
- [ ] CI job `router-boundary-check` và `publish-openapi` đã xanh ổn định 3 PR liên tiếp.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — mục 5.1 (luồng auth boundary), FR-01-08, FR-01-11, FR-01-12.
- **Ma trận năng lực:** [`docs/official_docs/03-capability-matrix.md`](../../official_docs/03-capability-matrix.md) — "Public/user-auth/admin-auth/device-auth boundary", "OpenAPI spec là chân lý API".
- **Nhóm người dùng:** [`docs/official_docs/02-personas-and-journeys.md`](../../official_docs/02-personas-and-journeys.md) — Platform Engineer (3.4).
- **Thuật ngữ:** Public router, OpenAPI, WebSocket.
- **Lộ trình:** Milestone M1 — Infrastructure Bootstrap.
