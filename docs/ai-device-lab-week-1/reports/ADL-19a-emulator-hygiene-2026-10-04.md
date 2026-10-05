# ADL-19a — Emulator hygiene E2E (2026-10-04)

## Kết luận

`PASS_APPROVED_EMULATOR` cho ADL-19a. AVD `galaxy_note10_plus`, serial runtime `emulator-5580`, Android API 35/ARM64 được dùng làm Approved Device Target theo production contract và WVR-12. Protocol chỉ đánh dấu `verified_clean` sau khi wipe-data hoàn tất và readback xác nhận canary không còn.

Evidence root: [`evidence/adl-19a-emulator-2026-10-04`](evidence/adl-19a-emulator-2026-10-04).

## Hợp đồng và triển khai

- API mới: `POST /api/ai-device-lab/devices/{device_id}/hygiene-results`, yêu cầu quyền `devices:update` và cùng organization.
- Input ghi `target_type`, `protocol_version`, reset result, readback result, active-run flag và evidence ref.
- Service khóa canonical device trước khi đọc/tạo row hygiene, ngăn race ở lần ghi đầu tiên và serialize observations theo device.
- Reset fail hoặc readback bẩn tạo `quarantined`; active run tạo `draining`; clean chỉ được cấp khi reset thành công, readback sạch và không có active run.
- OpenAPI và TypeScript client đã được sinh lại từ backend schema.

## E2E trên emulator thật

1. Tạo canary `/sdcard/Download/adl19a-canary.txt` và đọc lại thành công; [`before-reset.json`](evidence/adl-19a-emulator-2026-10-04/before-reset.json) ghi profile còn dữ liệu.
2. Gửi reset failure qua API; response [`api-dirty-response.json`](evidence/adl-19a-emulator-2026-10-04/api-dirty-response.json) trả `quarantined/RESET_FAILED`.
3. Gửi clean observation khi `active_run=true`; [`api-active-response.json`](evidence/adl-19a-emulator-2026-10-04/api-active-response.json) trả `draining/ACTIVE_RUN_DRAIN_REQUIRED`.
4. Dừng AVD, khởi động lại với `-wipe-data -no-snapshot`, chờ `sys.boot_completed=1`, xác nhận canary `ABSENT`.
5. Cài lại uiautomator APK, test APK, STFService và `atx-agent 0.10.1`; agent-boot quan sát offline rồi online lại.
6. Gửi clean observation; [`api-clean-response.json`](evidence/adl-19a-emulator-2026-10-04/api-clean-response.json) trả `verified_clean/CLEAN_READBACK_VERIFIED` và trỏ tới [`after-reset.json`](evidence/adl-19a-emulator-2026-10-04/after-reset.json).
7. PostgreSQL xác nhận state cuối và chuỗi audit trong [`database-hygiene-audit.json`](evidence/adl-19a-emulator-2026-10-04/database-hygiene-audit.json).

## Test, hiệu năng và khả năng mở rộng

- Backend focused regression: `16 passed`; toàn bộ AI Lab backend: `90 passed, 1 skipped`.
- Frontend typecheck: PASS.
- Playwright AI Device Lab: `11 passed`; harness dùng một worker vì các case dùng chung một Next dev compiler. Perf sample: navigation `243.7 ms`, 454 DOM nodes, không horizontal overflow.
- Burst API trên state đã có: 24 request đồng thời đều HTTP 200 và `verified_clean`; median `196.39 ms`, p95 `225.36 ms`, max `231.69 ms`.
- First-write race trên device benchmark mới: 24/24 request đồng thời HTTP 200, không unique conflict; median `181.29 ms`, p95 `203.86 ms`, max `211.44 ms`. Canonical-device row lock giữ thứ tự theo device; nhiều device vẫn có thể xử lý độc lập.
- Cross-org device write trả 404; unit/integration test cũng khóa các nhánh dirty readback và active run.

## Phạm vi waiver

WVR-12 tạm miễn bằng chứng 12 thiết bị đồng thời. Thiết kế 12 logical lanes, 168 slots và database reservation invariants không thay đổi. Kết quả này đóng protocol một target của ADL-19a; không thay thế rehearsal lifecycle nhiều target của ADL-19b hoặc các gate Play/payment/14-day/staging.
