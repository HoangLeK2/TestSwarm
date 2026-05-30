# DF-T-02-007 — Fleet view query API — paginated list

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-007 |
| **Title** | Fleet view — endpoint liệt kê thiết bị phân trang kèm trạng thái |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `persona:fleet-operator`, `risk:performance` |
| **Truy vết — FR refs** | FR-02-02 |
| **Truy vết — UC refs** | UC-02-02, UC-02-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Fleet operator vận hành 100-1000 device cần endpoint liệt kê phân trang, hiển thị state, owner session, group, last_seen. Đặc tả module FR-02-02 yêu cầu "Danh sách phân trang được; lọc theo group, trạng thái, owner; dữ liệu cập nhật trong vòng 5s khi trạng thái đổi."

Ticket này build endpoint `GET /api/devices?cursor=&limit=&state=&group_id=&owner_type=` trả paginated list. Joins `devices` × `device_states` × `device_sessions` (owner) × `device_group_members`. Phải tối ưu cho 10k devices/org với p99 < 500ms (DoD DF-E-02). Dữ liệu "5s freshness" đạt được qua TTL cache hoặc đọc trực tiếp DB indexed.

## 3. Câu chuyện người dùng

> **Là** Fleet Operator
> **Tôi muốn** xem danh sách thiết bị kèm trạng thái online/offline/busy
> **Để** quyết định nhanh thiết bị nào cần can thiệp hoặc đưa vào campaign

## 4. Yêu cầu chức năng

- Hệ thống PHẢI endpoint `GET /api/devices` với query params: `cursor`, `limit` (default 50, max 200), `state`, `group_id`, `owner_type`, `q` (search name/serial), `sort`.
- Hệ thống PHẢI response body: `{items: [{db_id, device_serial, name, state, group_ids, current_session_id, owner_type, owner_id, last_seen_at, model, android_version}], next_cursor, total}`.
- Hệ thống PHẢI tenant scoping — chỉ trả device thuộc org của user.
- Hệ thống PHẢI cursor-based pagination ổn định khi data thay đổi.
- Hệ thống PHẢI sort options: `name`, `-last_seen_at`, `state`, default `-paired_at`.
- Hệ thống PHẢI filter combine được (AND): `state=ONLINE&group_id=grp-1`.
- Hệ thống PHẢI p99 < 500ms với 10k device.
- Hệ thống PHẢI 5s freshness — state thay đổi ở DF-T-02-002 phản ánh trong list trong 5s (qua đọc DB hoặc cache invalidation).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: List cơ bản**

```
Given org acme có 1500 device
When alice GET /api/devices?limit=50
Then response 200 với items 50 phần tử, next_cursor != null, total=1500
And mỗi item có đủ field { db_id, device_serial, name, state, last_seen_at, ... }
```

**AC-2: Filter theo state**

```
When GET /api/devices?state=ONLINE
Then items chỉ chứa device state=ONLINE
And total = số ONLINE
```

**AC-3: Tenant isolation**

```
Given org beta có 500 device, org acme có 1500
When alice (acme) GET /api/devices
Then items chỉ thuộc acme, total=1500
And không có device beta xuất hiện
```

**AC-4: Pagination ổn định**

```
Given device list, page 1 cursor=c1
When client request page 2 với cursor=c1
Then không có duplicate item giữa page 1 và 2
And không miss item dù có device pair mới giữa 2 request
```

**AC-5: 5s freshness**

```
Given device "df-001" state=ONLINE trong list
When DF-T-02-002 chuyển state→BUSY
And alice GET /api/devices 5s sau
Then df-001 state=BUSY trong response
```

**AC-6: Search by name/serial**

```
When GET /api/devices?q=R58M
Then items chứa device có device_serial hoặc name match "R58M" (case insensitive)
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm full-text search advanced — DF-T-02-014 (filter).
- KHÔNG bao gồm UI fleet table — DF-E-11.
- KHÔNG bao gồm real-time push update — DF-T-02-015.
- KHÔNG bao gồm export CSV/Excel — defer.
- KHÔNG bao gồm bulk action — DF-T-02-009.

## 7. Kế hoạch triển khai

**Backend**

- [ ] Module `device_farm/devices/fleet_query.py`.
- [ ] Endpoint GET /api/devices.
- [ ] Cursor encoding (base64 of (last_id, last_paired_at)).
- [ ] Query optimization với JOIN + index hints.

**Contract / API**

- [ ] OpenAPI schema response.
- [ ] Query param validation.

**Database / Migration**

- [ ] Composite index (org_id, state, last_seen_at DESC).
- [ ] Composite index (org_id, paired_at DESC).
- [ ] Composite index (org_id, name) for search.

**Documentation**

- [ ] OpenAPI examples cho 5 query pattern phổ biến.

**Test**

- [ ] Integration test 6 AC.
- [ ] Performance test với 10k device → p99 < 500ms.
- [ ] Cross-tenant test.
- [ ] Pagination consistency test với mutation.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-007-01 | Positive | 1500 device | GET ?limit=50 | 200, 50 items, next_cursor, total=1500 |
| TC-DF-T-02-007-02 | Positive | Filter ONLINE | GET ?state=ONLINE | Items đều ONLINE |
| TC-DF-T-02-007-03 | Positive | Filter group | GET ?group_id=g1 | Items đều thuộc g1 |
| TC-DF-T-02-007-04 | Positive | Search "R58M" | GET ?q=R58M | Match serial/name |
| TC-DF-T-02-007-05 | Negative | Cursor malformed | GET ?cursor=xxx | 400 INVALID_CURSOR |
| TC-DF-T-02-007-06 | Negative | limit=999 | GET ?limit=999 | 400 LIMIT_TOO_LARGE (max 200) |
| TC-DF-T-02-007-07 | Negative | Cross-tenant | alice (acme) thấy org beta? | Không, total chỉ acme |
| TC-DF-T-02-007-08 | Edge | Pagination với insert giữa chừng | page 1 → pair mới → page 2 | Không duplicate, không miss |
| TC-DF-T-02-007-09 | Edge | 10k device fleet | GET ?limit=200 | p99 < 500ms (perf test) |
| TC-DF-T-02-007-10 | Edge | Empty org | GET | 200, items=[], total=0, next_cursor=null |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-02-001 (devices), DF-T-02-002 (state), DF-T-02-003 (session info), DF-T-01-002, DF-T-01-003, DF-T-01-004.

**Chặn:** DF-T-02-010 (capacity uses fleet view), DF-T-02-014 (search advanced), DF-E-11 (UI).

**Rủi ro:**

- **R1 — N+1 query khi join groups + sessions.** Giảm thiểu: single query với LATERAL JOIN hoặc materialized view.
- **R2 — Cache stale > 5s.** Giảm thiểu: TTL 3s hoặc invalidate trên `device.state_changed` event.
- **R3 — Cursor leak giữa tenants.** Giảm thiểu: include org_id trong cursor signature.

## 10. Điều kiện hoàn thành

- [ ] 10 test case pass.
- [ ] Perf test 10k device p99 < 500ms.
- [ ] OpenAPI examples đầy đủ.
- [ ] Cross-tenant test pass.
- [ ] Metric `fleet.list.duration_ms` p50/p99.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** FR-02-02.
- **Liên quan:** DF-T-02-014 (search), DF-T-02-015 (realtime update).
