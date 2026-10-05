# ADL-19a — Hygiene protocol và quarantine một Approved Device Target

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production device isolation prerequisite / COMPLETE — PASS_APPROVED_EMULATOR |
| Owner / review | Operator + BE fleet / QA + security |
| Dependencies | 00; permitted device/app scope; 01 run before cleanup validation |
| Deliverable | Hygiene protocol/state/audit, reset failure exclusion và isolated target reuse proof |

## 2. Source/gap
`backend/services/device_override/service.py:admin_reset_device_state` thay FSM/release claim; không tự chứng minh app/account/profile cleanup. DeviceReserveSession theo TTL không chứng minh customer data đã sạch. Phải định nghĩa hygiene state riêng, không dùng online=clean. Với emulator, wipe-data hoặc tạo AVD mới chỉ là cleanup action; vẫn cần canary readback, canonical identity và evidence như physical target.

## 3. Contract
- HygieneState per canonical device: dirty/draining/cleaning/verified_clean/quarantined, protocol_version, completed_at, actor, verification evidence, last customer campaign ref.
- Cleanup scope rõ app sandbox data/session/account/files/downloads nếu flow sử dụng; Play account ownership/continuity không tự sign-out/delete ngoài consent.
- Run đang active → drain/confirm terminal trước cleanup. Reset failure/uncertain command → quarantine, allocator 05/dispatcher 16 deny.
- verified_clean chỉ sau readback/device verification theo protocol, không set bởi lệnh thành công đơn thuần; replay audit không tạo false clean.

## 4. Bước làm
1. Security/operator ký cleanup inventory, target type và các thao tác cleanup/reset được phép.
2. Persist hygiene observations/state; fleet selection check với 05; audit actor/protocol/result.
3. Implement drain→clear/sign-out permitted scope→verify→release hoặc quarantine; bounded retry.
4. Run Approved Device Target trial sau scenario/login dữ liệu test, kiểm session/files canary và next re-claim. Emulator trial phải dùng profile/AVD độc lập và ghi reset/snapshot provenance.
5. Reset offline/fail và unauthorized actor negative tests; document recovery/quarantine release.

## 5. Acceptance
- [x] AC1: AVD độc lập được ghi canary, `-wipe-data -no-snapshot`, rồi readback xác nhận canary không còn trước khi `verified_clean`.
- [x] AC2: kết quả có `active_run=true` chuyển sang `draining`, không tạo trạng thái clean.
- [x] AC3: reset fail/uncertain chuyển sang `quarantined`; fleet reservation tests tiếp tục deny target chưa sạch.
- [x] AC4: API cùng-org ghi actor/protocol/evidence và PostgreSQL giữ audit `dirty → quarantined → draining → verified_clean`.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 19a-T1 | Test session/data then cleanup+reclaim | No previous customer session/data canary; evidence readback |
| 19a-T2 | Device offline/reset command fails | quarantine; no selection/dispatch |
| 19a-T3 | Active run while reset requested | drain first, not blind clear |
| 19a-T4 | Wrong role/org asks cleanup/release | Denied before device side effect |
| 19a-T5 | Lệnh reported success but readback dirty | Remains quarantined/dirty, not verified_clean |

## 7. Review và DoD
Operator witnesses device trial, QA independently verifies canary absent, security scope review. Evidence target type, serial masked, protocol version, cleanup timestamps/readbacks and API/DB logs. Fail → quarantine until fix/reverification; DONE needs AC1–4. One-device protocol proof does not replace fleet lifecycle 19b.

## 8. Kết quả 2026-10-04

- Báo cáo: [ADL-19a emulator hygiene E2E](reports/ADL-19a-emulator-hygiene-2026-10-04.md).
- Evidence: [`reports/evidence/adl-19a-emulator-2026-10-04`](reports/evidence/adl-19a-emulator-2026-10-04).
- Capacity áp dụng [WVR-12](CAPACITY-WAIVER.md): một Approved Device Target đủ cho protocol acceptance này; invariant 12 lane/168 slot vẫn giữ nguyên.
