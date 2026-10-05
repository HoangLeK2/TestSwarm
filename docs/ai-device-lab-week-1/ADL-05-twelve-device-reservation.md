# ADL-05 — Reservation production cho cohort 12 thiết bị

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE fleet + operator / DB reviewer + QA |
| Dependencies | 04; hygiene eligibility contract 19a |
| Deliverable | Reservation model, atomic allocator, capacity/release API/UI, race tests |

## 2. Source và gap
`backend/db/models/device_reserve_session.py` lưu claim TTL; `backend/services/device_reserve/service.py` mặc định max TTL 28.800s và row-lock runtime claim; `backend/api/routes/workspace_admin.py` quản pool ownership. Các chức năng này không giữ lịch 14 ngày. Không kéo TTL claim thành reservation dịch vụ.

## 3. Contract
- Reservation(org_id, device_id, campaign_id, lane_id, starts_at, ends_at, state, created_by) dùng khoảng `[start,end)` UTC, start<end.
- Active allocations trên **cùng Approved Device Target canonical ID** không overlap, kể cả khác org/workspace. Alias serial hoặc cloned emulator profile không được tạo device thứ hai nếu chưa có canonical ID/profile độc lập.
- Chọn 12 eligible devices all-or-nothing trong transaction; locking order ổn định; DB exclusion constraint hoặc serializable protocol có race proof. Không chỉ check trước INSERT.
- Health/online, org pool eligibility và last successful hygiene là checks riêng; reservation chưa tự claim máy.
- Release idempotent có reason/audit; không release rồi cấp máy khi execution cũ chưa drain. Replacement history thuộc 19b.

## 4. Bước làm
1. Chốt canonical device key, overlap invariant và eligibility DTO với 04/19a.
2. Migration/index/time-range constraint; allocator transaction, stable lock order, bounded retries và capacity error.
3. Implement reserve/release/list availability/API; không tiêu quota hay charge trong allocator.
4. Operator capacity view có interval/campaign/lane và denial reason; generated client.
5. Dispatcher 16 kiểm active reservation + claim + health trước gửi command; test rollback/overlap.

## 5. Acceptance
- [ ] AC1: atomic 12 reservations hoặc zero partial allocation.
- [ ] AC2: DB invariant ngăn overlap cross-campaign/cross-org.
- [ ] AC3: quarantine/dirty device không eligible; máy tồn tại reservation nhưng offline không được dispatch.
- [ ] AC4: release/drain idempotent, audit đầy đủ.
- [ ] AC5: capacity UI đối chiếu DB và không lộ org khác.

## 6. Test matrix
| ID | Action | Expected / evidence |
|---|---|---|
| 05-T1 | 12 eligible devices, reserve interval | 12 rows cùng transaction, distinct canonical IDs |
| 05-T2 | Chỉ 11 eligible hoặc lỗi INSERT thứ 12 | Zero committed rows; no quota delta |
| 05-T3 | Hai processes tranh cùng device/interval | Một allocation thắng; không overlap sau retry |
| 05-T4 | end==next start, và overlap 1 microsecond | Adjacent accepted; overlap rejected |
| 05-T5 | Device quarantine/offline/alias serial | Không double select; dispatch blocked khi unhealthy |
| 05-T6 | Cancel khi run active, repeat release | Drain trước reuse; một release audit/result |

## 7. Review và DoD
DB reviewer chạy race với real PostgreSQL; operator xác minh eligibility/serial; QA kiểm API/UI+cross-org. Lưu schema, transaction traces, before/after counts, capacity screenshots. Fail → giữ allocator disabled, sửa và rerun concurrency. DONE cần AC1–5; live 12-device execution vẫn cần 07.
