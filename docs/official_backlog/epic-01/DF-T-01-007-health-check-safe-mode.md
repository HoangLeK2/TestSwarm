# DF-T-01-007 — Health check & safe mode

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-01-007 |
| **Title** | Health check endpoint & safe mode khi database tạm tắt |
| **Type** | `type:feature` |
| **Epic** | DF-E-01 — Nền tảng & Bảo mật truy cập |
| **Module** | DF-MOD-01 — Nền tảng & Bảo mật truy cập |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:platform-runtime`, `layer:backend`, `layer:infra`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-01-09, FR-01-10 |
| **Truy vết — UC refs** | UC-01-08, UC-01-10 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 5.2 mô tả chế độ safe mode: khi database tạm không sẵn sàng (đang restore, đang nâng cấp, hoặc tạm sự cố), runtime **vẫn khởi động được**, route public và một số route hạ tầng vẫn phục vụ, nhưng các route CRUD nghiệp vụ không được mount. Mục tiêu là **phân biệt sự cố tầng dữ liệu với sự cố toàn bộ ứng dụng** từ phía hệ thống giám sát hạ tầng.

Pain point thực tế: nếu một sự cố DB ngắn 30s mà toàn bộ app trả 500 hoặc không có response, alert sẽ kích "app down", on-call vào điều tra mất 15 phút trong khi DB đã tự hồi. Với safe mode, alert chỉ đánh dấu "degraded mode" — đỡ noise đáng kể cho team vận hành.

Ticket build (1) endpoint `/health` luôn 200 (không touch DB); (2) endpoint `/api/server/status` trả flag `safe_mode`, `db_connected`, `version`; (3) lifecycle hook detect DB down lúc startup → mount giới hạn; (4) background job tự re-check DB và mount lại CRUD route khi DB trở lại; (5) dashboard hiển thị banner safe mode.

P0 vì là chỉ báo vận hành cơ bản — không có nó thì alerting không có tín hiệu phân biệt.

## 3. Câu chuyện người dùng

> **Là** hệ thống giám sát hạ tầng
> **Tôi muốn** endpoint /health luôn trả 200 khi tiến trình runtime còn sống, kể cả khi DB tắt
> **Để** alert phân biệt được "app crash" với "DB tạm sự cố"

> **Là** Admin tổ chức
> **Tôi muốn** thấy banner safe mode trên dashboard khi sản phẩm đang chạy ở chế độ giới hạn
> **Để** biết tại sao một số chức năng tạm không dùng được, không phải nghĩ là "sản phẩm sập"

## 4. Yêu cầu chức năng

- Hệ thống PHẢI endpoint `GET /health` luôn trả 200 OK với body `{"status":"alive","ts":<unix>}` nếu tiến trình còn sống — trace FR-01-09.
- Hệ thống PHẢI endpoint `GET /health/ready` trả 200 nếu DB connected, 503 nếu safe mode — phục vụ Kubernetes readiness probe.
- Hệ thống PHẢI endpoint `GET /api/server/status` (public) trả `{safe_mode: bool, db_connected: bool, version, started_at}` — trace FR-01-10.
- Hệ thống PHẢI startup hook detect DB unreachable trong N giây (default 10s) → bật safe mode, mount giới hạn (chỉ public + một số route hạ tầng), tiếp tục khởi động.
- Hệ thống PHẢI background job ping DB mỗi 10s (cấu hình được); khi DB trở lại → mount đầy đủ route CRUD trong < 60s — trace FR-01-09.
- Hệ thống PHẢI debounce safe mode flip: không vào lại safe mode nếu DB ping thành công ≥ 3 lần liên tiếp.
- Hệ thống PHẢI emit metric `runtime.safe_mode` gauge (0/1) và event `runtime.safe_mode_entered`, `runtime.safe_mode_exited`.
- Hệ thống PHẢI khi safe mode, route CRUD nghiệp vụ trả 503 với body `{"code":"SERVICE_DEGRADED", "safe_mode": true}`.
- Hệ thống NÊN dashboard hiển thị banner màu vàng "Hệ thống đang ở chế độ giới hạn (safe mode). Một số chức năng tạm không dùng được. Auto-refresh..." (implement chính ở DF-E-11 — ticket này chỉ enable endpoint).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: /health luôn 200 ngay cả khi DB down**

```
Given runtime đang chạy
And database container bị stop
When monitoring gọi GET /health
Then response 200 với body {"status":"alive","ts":...}
And response time < 100 ms (không touch DB)
```

**AC-2: /health/ready 503 khi safe mode**

```
Given runtime ở safe mode (DB down)
When Kubernetes gọi GET /health/ready
Then response 503
And Kubernetes ngừng route traffic vào pod đó (nếu có pod khác healthy)
And pod KHÔNG bị restart (vì liveness /health vẫn 200)
```

**AC-3: /api/server/status phản ánh đúng trạng thái**

```
Given DB đang up
When client gọi GET /api/server/status
Then response 200 với body {safe_mode: false, db_connected: true, version: "1.0.0", started_at: ...}
When DB bị stop
And client gọi lại
Then response 200 với body {safe_mode: true, db_connected: false, ...}
```

**AC-4: Startup với DB down vẫn boot được**

```
Given DB unreachable từ trước khi runtime khởi động
When pod start
Then runtime detect DB down trong 10s
And bật safe mode, mount route public + status
And pod READY ở probe liveness, NOT READY ở readiness
And /health trả 200, /api/server/status trả safe_mode: true
```

**AC-5: DB trở lại tự động exit safe mode**

```
Given runtime đang safe mode
When DB container start lại
Then background job phát hiện DB connected trong 10s
And sau 3 ping thành công liên tiếp (debounce), runtime mount route CRUD đầy đủ
And metric runtime.safe_mode chuyển 1 → 0
And event runtime.safe_mode_exited emit
And /api/server/status trả safe_mode: false trong < 60s từ lúc DB lên
```

**AC-6: CRUD route trả 503 khi safe mode**

```
Given safe mode active; user alice có JWT hợp lệ
When alice gọi GET /api/devices (route CRUD)
Then response 503 với body {"code":"SERVICE_DEGRADED", "safe_mode": true, "retry_after": 30}
And header Retry-After: 30
And response KHÔNG tiết lộ stack trace
```

**AC-7: Flip-flop debounce**

```
Given DB ping: success, fail, success, fail (mỗi 1s)
When background job đánh giá
Then runtime KHÔNG flip safe_mode mỗi lần thay đổi
And chỉ exit safe mode sau 3 success liên tiếp
And chỉ enter safe mode sau 3 fail liên tiếp
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm safe mode cluster-wide (cờ chung cho nhiều instance) — open question, defer.
- KHÔNG bao gồm partial safe mode (Redis down, Celery queue down) — chỉ DB ở ticket này; mở rộng sau.
- KHÔNG bao gồm UI banner đầy đủ (component, animation, copy) — DF-E-11.
- KHÔNG bao gồm graceful drain khi safe mode entered (cancel inflight CRUD) — defer; hiện trả 503 ngay.
- KHÔNG bao gồm replica/failover DB — DevOps task.
- KHÔNG bao gồm prometheus alert rule — DF-T-01-008 ticket riêng.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/runtime/health.py` — endpoint /health, /health/ready, /api/server/status.
- [ ] Module `device_farm/runtime/safe_mode.py` — flag manager, debounce logic.
- [ ] Background job `db_ping_job` (asyncio task hoặc Celery beat).
- [ ] Integrate với app_factory: nếu safe mode, không mount user/admin/device router CRUD.
- [ ] Middleware trả 503 cho route CRUD khi safe mode active.

**Frontend** (`layer:frontend`)

- [ ] (Endpoint /api/server/status sẵn sàng; banner UI build ở DF-E-11.)

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho /health, /health/ready, /api/server/status.
- [ ] Mã lỗi SERVICE_DEGRADED.

**Database / Migration** (`layer:db`)

- [ ] (Không có migration ở ticket này.)

**Infra / DevOps** (`layer:infra`)

- [ ] Helm value `healthcheck.db_ping_interval_sec` (default 10).
- [ ] Helm value `healthcheck.safe_mode_debounce_count` (default 3).
- [ ] Kubernetes Deployment: liveness probe = /health, readiness probe = /health/ready.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/platform-runtime.md` mục "Health & Safe Mode".
- [ ] `docs/runbooks/safe-mode-incident.md` — quy trình khi safe mode kéo dài > 5 phút.

**Test** (`layer:test`)

- [ ] Unit test debounce logic.
- [ ] Integration test 7 AC trên kind cluster (chạy postgres container, stop/start để simulate).
- [ ] Test load: /health đáp ứng 10000 req/s không tăng latency app.
- [ ] Test chaos: DB flip mỗi 5s suốt 10 phút, runtime không flip-flop safe mode.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-01-007-01 | Positive | Runtime up, DB up | GET /health | 200 {"status":"alive",...} trong < 100 ms |
| TC-DF-T-01-007-02 | Positive | Runtime up, DB up | GET /api/server/status | 200, safe_mode=false |
| TC-DF-T-01-007-03 | Positive | Runtime đang safe mode, DB trở lại | Quan sát trong 60s | safe_mode chuyển true → false; CRUD route trả lại 200 |
| TC-DF-T-01-007-04 | Negative | Runtime safe mode, alice JWT hợp lệ | GET /api/devices | 503 SERVICE_DEGRADED, header Retry-After: 30 |
| TC-DF-T-01-007-05 | Negative | DB unreachable từ startup | Pod start | Pod liveness OK, readiness FAIL; /health 200, /api/server/status safe_mode=true |
| TC-DF-T-01-007-06 | Edge | DB ping flip success/fail liên tục (mỗi 1s) trong 30s | Quan sát flag | Safe mode KHÔNG flip-flop; cần ≥ 3 lần liên tiếp để chuyển |
| TC-DF-T-01-007-07 | Edge | 10000 req /health/s | Bắn load | Tất cả 200, p99 < 50 ms, không ảnh hưởng app metric khác |
| TC-DF-T-01-007-08 | Edge | DB partially functional (connection OK nhưng query treo) | Gọi /api/server/status | db_connected có thể true; nhưng CRUD route timeout → cần health check sâu hơn đưa vào lộ trình sau |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime entrypoint).

**Chặn:** DF-T-01-010 (login UI cần biết safe mode để show banner), DF-T-01-008 (metric runtime.safe_mode).

**Phụ thuộc giữa Epic:** Mọi route CRUD DF-E-02-11 phải subject to safe mode gate (middleware tự áp dụng).

**Rủi ro:**

- **R1 — Safe mode flag flip-flop gây mount/unmount route liên tục, ảnh hưởng performance.** Giảm thiểu: debounce.
- **R2 — Route CRUD mounted bằng decorator; unmount dynamic phức tạp.** Implementation: middleware gate ở entry level thay vì unmount thực sự.
- **R3 — Db ping false positive (connection trả OK nhưng query thật fail).** Giảm thiểu: ping bằng SELECT 1, monitor latency.

**Phụ thuộc bên ngoài:** PostgreSQL.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 80%.
- [ ] 8 test case automation; AC-5 và AC-7 đặc biệt phải có test integration với DB stop/start thật.
- [ ] Runbook `safe-mode-incident.md` reviewed.
- [ ] Telemetry: `runtime.safe_mode` gauge, event safe_mode_entered/exited.
- [ ] Đã chạy chaos test (DB flip 10 phút) trên staging, không có flip-flop.
- [ ] Performance: /health endpoint không tăng latency app endpoint khác > 1%.
- [ ] Code review từ Platform Engineer + SRE.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/01-platform-runtime-and-access.md`](../../official_docs/modules/01-platform-runtime-and-access.md) — mục 5.2 luồng safe mode, FR-01-09, FR-01-10.
- **Ma trận năng lực:** "Safe mode khi database tạm tắt" — Active.
- **Nhóm người dùng:** Hệ thống giám sát hạ tầng, Admin tổ chức.
- **Thuật ngữ:** Safe mode.
- **Open question liên quan:** "Khi có nhiều instance Device Farm chạy song song, safe mode là cờ chung hay riêng?" — ticket này chọn riêng từng instance; cluster-wide defer.
