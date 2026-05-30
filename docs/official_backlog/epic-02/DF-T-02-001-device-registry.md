# DF-T-02-001 — Device registry — schema, 4 định danh, pair/unpair

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-001 |
| **Title** | Device registry — data model, 4 loại định danh, endpoint pair/unpair |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:db`, `layer:contract`, `type:feature`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-02-01, FR-02-14, FR-02-15 |
| **Truy vết — UC refs** | UC-02-01, UC-02-13 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Mô hình spec nêu rõ pain point: *"một thiết bị có thể có serial Android, có ADB serial endpoint khác (đặc biệt khi qua WiFi), có id trong cơ sở dữ liệu, và có relay serial do agent-boot tự sinh. Nếu hệ thống nhầm giữa các định danh này, người vận hành mất khả năng truy vết."* Ticket này giải quyết bằng schema chuẩn lưu **4 loại định danh tách biệt** cho cùng một thiết bị vật lý:

1. **db_id** (UUID) — id nội bộ DB, ổn định, dùng cho mọi endpoint CRUD.
2. **device_serial** (string) — serial Android do hệ điều hành cung cấp.
3. **adb_serial** (string) — endpoint ADB (USB hoặc WiFi IP:port).
4. **relay_serial** (string) — id do agent-boot quản lý, có thể thay đổi giữa các session bootstrap.

Ticket build (1) bảng `devices` với 4 cột tách biệt; (2) endpoint pair (admin / fleet operator) đăng ký thiết bị mới hoặc cập nhật khi relay agent báo cáo; (3) endpoint unpair giữ lịch sử artifact và chỉ chuyển status; (4) quy ước **mỗi endpoint nói rõ chấp nhận loại id nào** (vd `GET /api/devices/{db_id}` vs `POST /api/device/runtime/{device_serial}/gesture`); (5) validation: device thuộc đúng org (tenant scoping); (6) audit log pair/unpair.

P0 — block toàn bộ DF-E-02 và DF-E-03.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** đăng ký thiết bị mới vào fleet và unpair thiết bị đã loại bỏ
> **Để** inventory phản ánh đúng phần cứng đang vận hành

> **Là** Platform Engineer (gián tiếp)
> **Tôi muốn** schema device giữ 4 loại định danh tách biệt
> **Để** không có nhầm lẫn truy vết khi debug

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bảng `devices` (db_id UUID PK, device_serial, adb_serial, relay_serial, name, org_id FK, status, model, android_version, created_at, updated_at, paired_at, unpaired_at) — trace FR-02-15.
- Hệ thống PHẢI mỗi cột định danh có ý nghĩa độc lập; KHÔNG dùng một field "serial" gộp lung tung.
- Hệ thống PHẢI device_serial UNIQUE per org (trong một org không có 2 device cùng device_serial).
- Hệ thống PHẢI thuộc org qua `org_id` (TenantScopedModel theo DF-T-01-004) — trace FR-02-15.
- Hệ thống PHẢI endpoint `POST /api/devices/pair` body `{device_serial, adb_serial, relay_serial, name?, model?, android_version?}` — admin-auth hoặc fleet-operator role — trace FR-02-01.
- Hệ thống PHẢI khi pair: nếu device_serial đã tồn tại trong org → update các định danh khác (re-pair sau khi WiFi đổi IP); nếu chưa → tạo mới với status="paired", FSM state "UNKNOWN" (đẩy event sang DF-T-02-002).
- Hệ thống PHẢI endpoint `POST /api/devices/{db_id}/unpair` set status="unpaired", giữ lịch sử artifact, **từ chối** nếu đang trong session active — trace FR-02-14.
- Hệ thống PHẢI endpoint `GET /api/devices/{db_id}` trả đầy đủ 4 định danh + metadata.
- Hệ thống PHẢI endpoint `PATCH /api/devices/{db_id}` cho phép đổi `name`, gắn `notes`.
- Hệ thống PHẢI emit audit event `device.paired`, `device.repaired`, `device.unpaired`, `device.metadata_updated`.
- Hệ thống PHẢI generate `device_key` (lưu hash trong `device_keys` table — DF-T-01-006) khi pair lần đầu; trả về plaintext **chỉ một lần** trong response pair để agent lưu local.
- Hệ thống PHẢI document quy ước id loại nào cho endpoint nào — section trong OpenAPI description.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Pair thiết bị mới thành công**

```
Given Fleet Operator bob (acme) gọi POST /api/devices/pair
And body {device_serial:"R58M12345", adb_serial:"192.168.1.10:5555", relay_serial:"relay-h1-001", name:"Test #1"}
When request được xử lý
Then response 201 với {db_id, device_key (plaintext, chỉ lần này), ...}
And bảng devices có record mới: org_id=acme, status="paired", FSM state="UNKNOWN"
And bảng device_keys có record hash của device_key
And event "device.paired" emit sang FSM (DF-T-02-002)
And audit log "device.paired" với actor=bob, device_id
And response body có disclaimer "device_key chỉ trả về một lần"
```

**AC-2: Re-pair khi WiFi đổi IP**

```
Given device "R58M12345" đã pair, adb_serial="192.168.1.10:5555"
When agent báo cáo serial mới adb_serial="192.168.1.20:5555" qua POST /api/devices/pair
Then response 200 (không 201 — đây là update)
And device record cập nhật adb_serial mới, các định danh khác giữ nguyên
And device_key KHÔNG được rotate ngầm; muốn rotate gọi endpoint riêng (DF-T-01-006)
And event "device.repaired" emit
And audit log "device.repaired" với old_adb_serial, new_adb_serial
```

**AC-3: Unpair giữ lịch sử**

```
Given device "R58M12345" status="paired", không trong session active
When bob gọi POST /api/devices/{db_id}/unpair
Then response 200
And status chuyển "unpaired", unpaired_at set
And artifact history KHÔNG bị xóa (DF-T-06 sẽ giữ); device_key cũ vẫn hash trong DB nhưng status=revoked
And event "device.unpaired" emit; FSM transition tới state cuối (defer DF-T-02-002)
And audit log "device.unpaired"
And nếu re-pair sau này với cùng device_serial, tạo bản ghi MỚI (không revive) — vì pair sau khi unpair là chu trình mới
```

**AC-4: Từ chối unpair khi device đang BUSY**

```
Given device "R58M12345" đang FSM state BUSY (có session active)
When bob gọi POST /api/devices/{db_id}/unpair
Then response 409 CONFLICT với body {"code":"DEVICE_IN_SESSION", "session_id":"..."}
And device không bị unpair
And audit log "device.unpair_blocked_session_active"
```

**AC-5: Cross-tenant — không thấy device org khác**

```
Given device "X-beta-001" thuộc org beta
And alice là member acme
When alice gọi GET /api/devices/{X-beta-001.db_id}
Then response 404 NOT_FOUND
And audit log "tenant.cross_access_attempt"
```

**AC-6: Endpoint runtime nhận device_serial, không db_id**

```
Given OpenAPI spec mô tả /api/device/runtime/{device_serial}/screenshot
When agent gọi với db_id nhầm
Then response 400 BAD_REQUEST với body {"code":"INVALID_IDENTIFIER_TYPE", "expected":"device_serial", "received":"<looks like db_id (UUID)>"}
```

**AC-7: Pair cùng device_serial khác org (cấp DB)**

```
Given device "R58M12345" đã pair trong org acme
When org beta cố pair cùng device_serial "R58M12345"
Then response 201 (vì UNIQUE per org, không cross-org)
And bảng devices có 2 record cho cùng device_serial nhưng khác org_id
And lưu ý: agent ở host phải nhận device_key khác → tự nhiên không xung đột
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm UI pair thiết bị qua dashboard — DF-E-11.
- KHÔNG bao gồm CLI fleet-op tool đăng ký bulk — DF-T-03-014 (bulk bootstrap).
- KHÔNG bao gồm health check thiết bị (battery, temperature) — đưa vào lộ trình sau module.
- KHÔNG bao gồm device key rotation logic chi tiết — DF-T-01-006 + DF-T-03-013.
- KHÔNG bao gồm FSM state machine logic — DF-T-02-002 (ticket này chỉ emit event).
- KHÔNG bao gồm transfer device giữa org — defer.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Module `device_farm/devices/models.py` — Device(TenantScopedModel).
- [ ] Module `device_farm/devices/service.py` — pair, unpair, update_metadata.
- [ ] Endpoint pair, unpair, get, patch.
- [ ] Generate + hash device_key.
- [ ] Validation id type (UUID vs serial format).
- [ ] Emit event sang FSM module (in-process pub/sub hoặc DB outbox).

**Frontend** (`layer:frontend`)

- [ ] Defer DF-E-11.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho 4 endpoint.
- [ ] Document quy ước id type per endpoint.
- [ ] Mã lỗi: DEVICE_IN_SESSION, INVALID_IDENTIFIER_TYPE.

**Database / Migration** (`layer:db`)

- [ ] Migration tạo bảng `devices`.
- [ ] Index (org_id, status), (org_id, device_serial UNIQUE), (relay_serial).
- [ ] Cập nhật `device_keys` (đã có từ DF-T-01-006) ref device_id.

**Infra / DevOps** (`layer:infra`)

- [ ] Không có hạng mục mới đáng kể.

**Documentation** (`layer:docs`)

- [ ] `docs/modules/devices.md` mục "Identifier types".
- [ ] OpenAPI description: "Endpoint runtime dùng device_serial; endpoint CRUD dùng db_id".
- [ ] Runbook "Re-pair khi WiFi đổi IP".

**Test** (`layer:test`)

- [ ] Unit test service pair/unpair.
- [ ] Integration test 7 AC.
- [ ] Test concurrent pair (2 agent cùng pair một device_serial) → 1 thành công, 1 update.
- [ ] Test cross-tenant 50 random GET.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-001-01 | Positive | bob fleet-op acme | POST /api/devices/pair với 4 serial valid | 201, db_id mới, device_key plaintext trả về 1 lần, audit |
| TC-DF-T-02-001-02 | Positive | Device đã pair, adb_serial đổi | POST pair lần 2 cùng device_serial | 200, adb_serial cập nhật, các field khác giữ |
| TC-DF-T-02-001-03 | Positive | Device paired, không session | POST /api/devices/{id}/unpair | 200, status=unpaired, audit |
| TC-DF-T-02-001-04 | Positive | bob GET device chi tiết | GET /api/devices/{db_id} | 200, body có 4 định danh, device_key KHÔNG trả về |
| TC-DF-T-02-001-05 | Negative | Device đang BUSY | Unpair | 409 DEVICE_IN_SESSION |
| TC-DF-T-02-001-06 | Negative | alice (acme) cố GET device org beta | GET /api/devices/{beta_device_id} | 404 NOT_FOUND |
| TC-DF-T-02-001-07 | Negative | Runtime endpoint nhận db_id thay vì device_serial | GET /api/device/runtime/{db_id_format}/screenshot | 400 INVALID_IDENTIFIER_TYPE |
| TC-DF-T-02-001-08 | Edge | 2 agent cùng pair device_serial "X" trong cùng org đồng thời | 2 POST pair concurrent | Đúng 1 record tạo, 1 trả 200 update; DB consistent |
| TC-DF-T-02-001-09 | Edge | Pair device_serial "X" trong org acme; org beta cũng pair "X" | POST pair org beta | 201, 2 record DB (org_id khác), 2 device_key khác |
| TC-DF-T-02-001-10 | Edge | Device đã unpaired, cùng device_serial pair lại | POST pair | 201, record MỚI; bản cũ giữ status=unpaired (audit/history) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-001 (runtime), DF-T-01-002 (auth + device_key infrastructure), DF-T-01-003 (RBAC role fleet-operator), DF-T-01-004 (tenant), DF-T-01-005 (audit), DF-T-01-006 (device_keys versioned table).

**Chặn:** DF-T-02-002 (FSM cần device record), DF-T-02-003 (claim cần device), toàn bộ DF-E-02 còn lại. Cross-Epic: DF-T-03-001 agent-boot khi báo cáo device sẽ gọi pair endpoint này.

**Phụ thuộc giữa Epic:** Endpoint pair được gọi từ agent (DF-E-03) lúc bootstrap.

**Rủi ro:**

- **R1 — Confusion giữa 4 loại id gây bug.** Giảm thiểu: type-hint nghiêm ngặt (UUID vs str), validation runtime với regex.
- **R2 — Concurrent pair race.** Giảm thiểu: UNIQUE constraint DB + retry-on-conflict.
- **R3 — Re-pair làm mất device_key cũ.** Giảm thiểu: KHÔNG rotate ngầm; rotation explicit qua DF-T-01-006.
- **R4 — Unpair khi device đang stream — gây orphan resource.** Giảm thiểu: AC-4 từ chối nếu BUSY.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Unit test coverage ≥ 85%.
- [ ] 10 test case automation.
- [ ] OpenAPI spec đầy đủ, description nói rõ id type.
- [ ] Runbook "Re-pair WiFi đổi IP" reviewed.
- [ ] Audit log đầy đủ.
- [ ] Cross-tenant test 50 random pass.
- [ ] Code review từ module owner.
- [ ] Telemetry: `device.paired.count`, `device.unpaired.count`, `device.repair.count`.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [`docs/official_docs/modules/02-devices-and-control-plane.md`](../../official_docs/modules/02-devices-and-control-plane.md) — FR-02-01, FR-02-14, FR-02-15; mục 5.1 (luồng pair).
- **Ma trận năng lực:** "Reserve và release device session" — Active.
- **Nhóm người dùng:** Fleet Operator.
- **Thuật ngữ:** Device, Device serial, ADB serial, Relay serial, Pairing.
- **Liên quan:** DF-T-03-001 (agent-boot gọi pair).
