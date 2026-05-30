# DF-T-02-006 — Reconnect strategy config — exponential backoff

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-02-006 |
| **Title** | Cấu hình chiến lược reconnect (exponential backoff) ở control plane |
| **Type** | `type:feature` |
| **Epic** | DF-E-02 — Thiết bị & Mặt phẳng điều khiển |
| **Module** | DF-MOD-02 — Thiết bị & Mặt phẳng điều khiển |
| **Priority** | P1 |
| **Story Points** | 3 |
| **Status** | Backlog |
| **Labels** | `module:devices`, `layer:backend`, `layer:contract`, `type:feature`, `persona:platform-engineer` |
| **Truy vết — FR refs** | FR-02-02, FR-03-06 (cross-Epic) |
| **Truy vết — UC refs** | UC-03-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Module DF-MOD-03 FR-03-06 nêu agent dùng exponential backoff khi reconnect. Ticket này build phía control plane: nơi tenant cấu hình các tham số backoff (interval_base, max_interval, max_attempts), expose endpoint admin lấy/sửa, và publish config tới agent qua heartbeat response (DF-E-03 sẽ consume).

Đây là ticket "config infrastructure" — control plane là source of truth cho config reconnect; agent kéo về và áp dụng. Không build logic backoff ở control plane (đó là DF-E-03).

## 3. Câu chuyện người dùng

> **Là** Platform Engineer
> **Tôi muốn** điều chỉnh tham số reconnect backoff cho fleet vận hành ở môi trường mạng yếu
> **Để** giảm tỷ lệ DEAD false positive mà không cần redeploy agent

## 4. Yêu cầu chức năng

- Hệ thống PHẢI bảng `reconnect_policies` (org_id PK, interval_base_ms, max_interval_ms, max_attempts, jitter_factor, updated_at, updated_by).
- Hệ thống PHẢI default policy (interval_base=1000ms, max_interval=60000ms, max_attempts=20, jitter=0.2).
- Hệ thống PHẢI endpoint `GET /api/admin/reconnect-policy` đọc policy của org.
- Hệ thống PHẢI endpoint `PUT /api/admin/reconnect-policy` cập nhật, admin-auth required, validate range.
- Hệ thống PHẢI policy được trả về agent qua heartbeat response (contract với DF-T-03-006).
- Hệ thống PHẢI audit log "reconnect_policy.updated" với old + new values.
- Hệ thống PHẢI version policy (last_updated_at) để agent biết khi nào cần reload.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Get default policy khi chưa cấu hình**

```
Given org "acme" chưa cấu hình policy riêng
When admin GET /api/admin/reconnect-policy
Then response 200 với policy default
And response header X-Policy-Source: "default"
```

**AC-2: Update policy thành công**

```
Given admin alice
When PUT /api/admin/reconnect-policy với {interval_base_ms:2000, max_interval_ms:120000}
Then response 200, policy saved
And audit log "reconnect_policy.updated"
And next heartbeat từ agent thuộc org acme sẽ nhận policy mới
```

**AC-3: Validation reject value bất hợp lý**

```
When PUT với {interval_base_ms:0}
Then response 400 với code=INVALID_RANGE
When PUT với {max_attempts:99999}
Then response 400 (max_attempts > 100)
When PUT với {jitter_factor:2.0}
Then response 400 (jitter ∈ [0, 1])
```

**AC-4: Non-admin không sửa được**

```
Given member thường bob
When PUT
Then 403 FORBIDDEN
```

**AC-5: Policy version để agent reload**

```
Given agent đã pull policy version v1
When admin update tới v2
Then agent nhận policy mới qua heartbeat response sau đó
And agent log "policy_reloaded" với old=v1 new=v2
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm thực thi backoff (DF-E-03 DF-T-03-006).
- KHÔNG bao gồm per-device override policy — defer.
- KHÔNG bao gồm UI cấu hình — DF-E-11.

## 7. Kế hoạch triển khai

**Backend**

- [ ] Module `device_farm/devices/reconnect_policy.py`.
- [ ] 2 endpoint GET/PUT.
- [ ] Validation Pydantic.

**Contract / API**

- [ ] OpenAPI policy schema.
- [ ] Heartbeat response schema bổ sung policy block (coordinate DF-T-03-006).

**Database / Migration**

- [ ] Migration `reconnect_policies`.

**Documentation**

- [ ] `docs/modules/devices.md` mục "Reconnect tuning".
- [ ] Runbook "Tune reconnect cho phòng máy mạng yếu".

**Test**

- [ ] Unit test validation.
- [ ] Integration test 5 AC.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-02-006-01 | Positive | Org chưa cấu hình | GET policy | 200, default values |
| TC-DF-T-02-006-02 | Positive | Admin update | PUT valid | 200, saved, audit |
| TC-DF-T-02-006-03 | Positive | Policy version v2 | Heartbeat agent | Agent nhận policy mới |
| TC-DF-T-02-006-04 | Negative | Member thường | PUT | 403 |
| TC-DF-T-02-006-05 | Negative | interval=0 | PUT | 400 INVALID_RANGE |
| TC-DF-T-02-006-06 | Negative | jitter=2.0 | PUT | 400 |
| TC-DF-T-02-006-07 | Edge | Update đồng thời 2 admin | 2 PUT concurrent | Last-write-wins, audit cả 2 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-01-003 (RBAC admin), DF-T-01-005 (audit).

**Chặn:** DF-T-03-006 (heartbeat consume policy).

**Rủi ro:**

- **R1 — Tenant cấu hình quá lỏng gây tốn tài nguyên reconnect.** Giảm thiểu: hard limit max_attempts ≤ 100.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] 7 test case pass.
- [ ] Audit log đầy đủ.
- [ ] OpenAPI policy schema publish.
- [ ] Runbook reviewed.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** DF-MOD-03 FR-03-06.
- **Liên quan:** DF-T-02-005 dead detection, DF-T-03-006 heartbeat.
