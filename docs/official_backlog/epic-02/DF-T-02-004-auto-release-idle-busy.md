# DF-T-02-004 — Auto-release & idle/busy transition logic

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-004 |
| **Title** | Auto-release session khi timeout và quy tắc idle/busy transition |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:infra`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-04 |
| **Truy vết — UC refs** | UC-02-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 8 nêu: "Nếu một session bị bỏ quên (người vận hành đóng tab không bấm release, hoặc scenario chết giữa chừng), hệ thống tự release sau ngưỡng cấu hình. Đặt ngưỡng quá ngắn sẽ cắt phiên thật đang chạy; đặt quá dài giữ thiết bị BUSY vô ích."

Ticket này build worker chạy nền quét bảng `device_sessions` đều đặn (mỗi 30s), tìm các session có `released_at IS NULL AND last_heartbeat + ttl_sec < now()`, release tự động và emit event `session.timeout_released`. Đồng thời định nghĩa rõ ngưỡng heartbeat khác nhau theo `owner_type` (manual: 5 phút inactivity; scenario: 1 phút; mcp: 2 phút) để phù hợp pattern thực tế.

P0 vì thiếu auto-release sẽ rò rỉ device BUSY vĩnh viễn khi client crash — fleet sẽ cạn dần.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** thiết bị tự động trở về pool khi session bị bỏ quên
> **Để** không phải can thiệp thủ công mỗi khi client crash hay người dùng đóng tab

## 4. Yêu cầu chức năng

- Hệ thống PHẢI background worker quét sessions mỗi 30s, release session quá hạn — trace FR-02-04.
- Hệ thống PHẢI ngưỡng inactivity cấu hình per owner_type: manual 300s, scenario 60s, mcp 120s (default, có thể override per tenant).
- Hệ thống PHẢI khi auto-release: set released_at = now, set release_reason = "timeout", emit event `session.timeout_released`.
- Hệ thống PHẢI device về ONLINE qua FSM transition (DF-T-02-002).
- Hệ thống PHẢI ghi audit log "session.auto_released" với last_heartbeat và idle_seconds.
- Hệ thống PHẢI notify owner qua event stream (DF-T-02-015) để frontend có thể hiển thị "Session đã hết hạn".
- Hệ thống PHẢI metric `session.auto_release_count` theo owner_type và reason.
- Hệ thống PHẢI worker idempotent — chạy multiple instance (HA) không double-release.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Auto-release manual session sau 5 phút không heartbeat**

```
Given session S1 owner_type=manual, last_heartbeat = now - 310s
When worker chạy
Then S1 released_at set, release_reason="timeout"
And device về ONLINE
And event "session.timeout_released" emit
And audit log entry tạo
```

**AC-2: Heartbeat reset timer**

```
Given session S2 owner_type=scenario, last_heartbeat = now - 70s (đã quá 60s ngưỡng)
When ngay trước worker chạy, owner heartbeat
Then last_heartbeat → now
And worker không release S2
And S2 vẫn active
```

**AC-3: Override ngưỡng per tenant**

```
Given org "vip" cấu hình manual_idle_threshold=900 (15 phút)
And session S3 trong vip, owner_type=manual, last_heartbeat = now - 600s
When worker chạy
Then S3 KHÔNG bị release (chưa quá 900s)
```

**AC-4: HA — 2 worker instance không double-release**

```
Given 2 worker instance chạy đồng thời
And session S4 quá hạn
When cả 2 worker scan cùng lúc
Then đúng 1 worker release S4 (dùng SELECT FOR UPDATE SKIP LOCKED hoặc advisory lock)
And không có duplicate event "session.timeout_released"
```

**AC-5: Auto-release không ảnh hưởng session khác**

```
Given 1000 session active, 50 quá hạn
When worker chạy
Then đúng 50 session released, 950 không bị động đến
And worker hoàn tất < 5s
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm manual force-release của admin — DF-T-02-011.
- KHÔNG bao gồm UI thông báo session expired — DF-E-11.
- KHÔNG bao gồm preemptive release khi có claim priority cao hơn — đưa vào lộ trình sau.
- KHÔNG bao gồm graceful shutdown khi auto-release scenario session — DF-E-04 lo cleanup scenario state.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/devices/auto_release_worker.py`.
- [ ] Loop với interval 30s, query expired sessions với `FOR UPDATE SKIP LOCKED`.
- [ ] Config provider đọc threshold per owner_type + per tenant override.
- [ ] Integration với release service từ DF-T-02-003.

**Frontend** (`layer:frontend`)

- [ ] Không có (consumer của event stream ở DF-E-11).

**Contract / API** (`layer:contract`)

- [ ] Bổ sung trường `release_reason` enum (manual, timeout, force) vào schema session.
- [ ] Event schema `session.timeout_released`.

**Database / Migration** (`layer:db`)

- [ ] Cột `release_reason` TEXT trên `device_sessions`.
- [ ] Cấu hình `tenant_settings.session_idle_threshold` JSON (nếu DF-T-01-010 chưa có thì coordinate).

**Infra / DevOps** (`layer:infra`)

- [ ] Deploy worker như sidecar hoặc separate container.
- [ ] Helm value `autoRelease.intervalSec` (default 30), `autoRelease.threshold.manual=300`, ..
- [ ] Liveness probe cho worker.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/devices.md` mục "Auto-release thresholds".
- [ ] Runbook "Tune session timeout cho workflow đặc thù".

**Test** (`layer:test`)

- [ ] Unit test worker logic với time mock.
- [ ] Integration test 5 AC.
- [ ] HA test: 2 worker instance + 1000 expired session → mỗi session release đúng 1 lần.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-004-01 | Positive | Session manual, idle 310s | Worker chạy | Session released, state→ONLINE |
| TC-DF-T-02-004-02 | Positive | Session scenario, idle 70s | Worker chạy | Session released (vì ngưỡng 60s) |
| TC-DF-T-02-004-03 | Positive | Heartbeat ngay trước worker | Worker scan | Session không bị release |
| TC-DF-T-02-004-04 | Negative | Session đã released_at set | Worker scan | Skip, không re-release |
| TC-DF-T-02-004-05 | Negative | Session manual idle 200s | Worker chạy | Skip (chưa quá 300s) |
| TC-DF-T-02-004-06 | Edge | 2 worker concurrent | Mỗi worker thấy session expired | 1 worker release, 1 worker skip; no duplicate event |
| TC-DF-T-02-004-07 | Edge | Tenant override threshold=900 manual | Session idle 600s | Skip |
| TC-DF-T-02-004-08 | Edge | 1000 expired session cùng lúc | Worker batch | Hoàn tất < 5s, tất cả release đúng 1 lần |
| TC-DF-T-02-004-09 | Edge | Worker restart giữa batch | Worker crash, restart | Resume, session chưa release vẫn được scan lần sau |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-003 (release service), DF-T-02-002 (FSM event), DF-T-01-005 (audit).

**Chặn:** Stability của DF-E-04-5 dispatch (vì fleet không bị nghẽn vĩnh viễn).

**Rủi ro:**

- **R1 — Threshold quá ngắn cắt phiên thực tế.** Giảm thiểu: default phù hợp pattern hiện tại; tenant có thể override; alert khi auto-release rate vượt 10%/giờ.
- **R2 — Worker chạy multiple instance đè nhau.** Giảm thiểu: SKIP LOCKED hoặc advisory lock per row.
- **R3 — Heartbeat từ client bị delay làm session bị nhầm timeout.** Giảm thiểu: grace period 10s sau ngưỡng; client retry heartbeat.

**Phụ thuộc bên ngoài:** Background scheduler (APScheduler hoặc native asyncio task).

## 10. Điều kiện hoàn thành

- [ ] Worker chạy ổn định 24h trong staging, không miss session expired.
- [ ] HA test pass với 2 instance.
- [ ] Metric `session.auto_release_count{owner_type, reason}` xuất hiện.
- [ ] Audit log "session.auto_released" đầy đủ.
- [ ] Runbook tune threshold reviewed.
- [ ] Tài liệu cấu hình per-tenant threshold.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** FR-02-04, mục 8 "Auto-release session timeout".
- **Liên quan:** DF-T-02-003 (release), DF-T-02-015 (event stream notify).
