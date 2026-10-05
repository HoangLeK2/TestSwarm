# ADL-16 — Farm adapter E2E trên emulator (2026-10-04)

## Kết luận

`PASS_APPROVED_EMULATOR / PENDING_INDEPENDENT_REVIEW` cho ADL-16. Adapter đã chạy chuỗi thật trên source backend, PostgreSQL cô lập và AVD `emulator-5580` với Temporal tắt để kiểm tra fallback production path. WVR-12 áp dụng với `observed_device_count=1`; domain vẫn giữ 12 logical lanes, 14 ngày và 168 slots.

Evidence root: [`evidence/adl-16-emulator-2026-10-04`](evidence/adl-16-emulator-2026-10-04).
Evidence files được khóa trong [`CHECKSUMS.sha256`](evidence/adl-16-emulator-2026-10-04/CHECKSUMS.sha256).

## Hợp đồng đã triển khai

- API tạo run atomically khóa đúng organization, campaign, lane, slot, execution, approved scenario version/hash, app build và active reservation; server tự tạo operation policy từ approval.
- `RunAttempt`, `FarmJob` và durable outbox dùng idempotency key duy nhất. Worker claim bằng lease/fencing, bounded batch/concurrency, retry/backoff và dead-letter lỗi dispatch không thể xác định.
- Inbox dedup theo source/event ID. Event `adl-farm-event-v1` bắt buộc `execution_id`; public API chỉ nhận step evidence và từ chối terminal verdict do caller gửi. Reducer terminal độc lập arrival order; late completion không đảo failed/blocked/cancelled thành pass.
- Temporal và fallback dùng cùng pinned snapshot validation, terminal monitor và reducer. Cả hai chờ kết quả runtime; deadline chỉ ghi `DEADLINE_EXCEEDED` sau cancel drain, hoặc fail closed bằng `CANCEL_DRAIN_UNCONFIRMED`.
- Trước dispatch, adapter đọc `dumpsys package`, persist observed package/version/build target rồi fail closed nếu không khớp. Live run xác nhận `com.android.settings`, `versionName=15`, `versionCode=35`.
- Emulator local chỉ chấp nhận serial `emulator-NNNN[N]`, nối qua ADB forward đến uiautomator2 và dùng local ADB scoped serial cho shell/app launch. Đăng ký lặp lại tái sử dụng forward khỏe; forward cũ được dọn trước khi thay.
- Payload chỉ chứa reference/ID và bounded metadata. Mỗi job tối đa 2.000 events, mỗi event tối đa 64 KiB, mỗi artifact reference tối đa 1.024 UTF-8 bytes; reducer chỉ đọc terminal evidence thay vì toàn bộ step history.

## Live identity chain

API tạo và theo dõi run đã trả cùng một chuỗi ID:

- service campaign `799f86b4-7388-45ff-b087-d16c5f5f29ce`
- lane `bdcab4b9-5b98-4e0d-9642-13040cf8bba1`
- slot `e97bfd25-d7b3-4ba0-bfca-dcf120b067be`
- run attempt `9262f1bf-6936-42cb-a202-c9b8564e6dcd`
- farm job `3e043066-6148-420b-bff7-929fab03e443`
- execution `03f1fed2-7d99-49ca-a83e-b2bb8134ae2b`
- scenario version `3e237c59-cee5-47ea-9896-3dfb88c2902e`
- device `bd4c674c-00ca-47fe-bea9-89c07dc3eb76`, serial `emulator-5580`

Approved scenario mở Android Settings, chờ, assert text `Settings`, rồi gửi phím Home. [`before-focus.txt`](evidence/adl-16-emulator-2026-10-04/before-focus.txt) và [`before-settings.png`](evidence/adl-16-emulator-2026-10-04/before-settings.png) ghi Settings; [`after-focus.txt`](evidence/adl-16-emulator-2026-10-04/after-focus.txt) và [`after-home.png`](evidence/adl-16-emulator-2026-10-04/after-home.png) ghi Nexus Launcher.

[`db-identity-review-fixes.json`](evidence/adl-16-emulator-2026-10-04/db-identity-review-fixes.json) xác nhận job `succeeded/pass`, attempt `passed`, execution `completed`, bốn `ExecutionStep` đều passed, outbox `delivered`, event terminal có schema `adl-farm-event-v1` và đúng execution ID. Cùng file lưu observed build `15/35` và target build ID. [`api-job-review-fixes-final.json`](evidence/adl-16-emulator-2026-10-04/api-job-review-fixes-final.json) là readback API của run mới.

Một run chẩn đoán trước đó đã fail ở `launch_app` vì local emulator chưa có shell control channel. Lỗi này dẫn tới bổ sung local ADB scoped serial trong `DeviceClient`; run mới ở trên sau restart đã pass toàn bộ Settings → assert → Home. Evidence fail không được dùng làm acceptance pass.

## Fault, cancel và parity verification

| Test | Kết quả |
|---|---|
| 16-T1 live API → Approved Device Target → DB/evidence | PASS, exact identity/version/hash và emulator target |
| 16-T2 commit/crash/expired lease/idempotent resend | PASS, một attempt/job và fenced recovery |
| 16-T3 duplicate/reordered terminal events | PASS, terminal state không bị late pass ghi đè |
| 16-T4 uncertain fallback dispatch | PASS, dead-letter `FALLBACK_DISPATCH_UNCERTAIN`, không blind retry |
| 16-T5 deadline/cancel/shutdown | PASS, unit tests xác nhận runtime drain trước deadline verdict; unconfirmed drain fail closed |
| 16-T6 Temporal/fallback contract | PASS, cùng snapshot/policy/reducer và terminal monitor; fallback live, Temporal terminal/deadline tests |

Backend AI Lab + campaign/runtime/watchdog regression: `120 passed, 1 skipped`; focused review suite: `16 passed`. Frontend typecheck PASS; Playwright AI Device Lab `11 passed`. OpenAPI export và generated TypeScript client sync PASS.

## Hiệu năng và khả năng mở rộng

[`control-plane-benchmark.json`](evidence/adl-16-emulator-2026-10-04/control-plane-benchmark.json) chạy 168 lần inspect job với concurrency 12, tương ứng mô hình 12 lane × 14 ngày: 168/168 HTTP 200 và cùng trạng thái `succeeded`, throughput `363.596 req/s`, median `24.086 ms`, p95 `131.276 ms`, max `139.926 ms` trên máy local.

Đây là benchmark control-plane, không phải phép đo 12 thiết bị đồng thời. WVR-12 chỉ miễn runtime capacity nhiều thiết bị; database/API vẫn giữ unique constraints, 12-or-zero reservation, 168-slot materialization và bounded concurrency.

[`api-emulator-health-after-watchdog.json`](evidence/adl-16-emulator-2026-10-04/api-emulator-health-after-watchdog.json) ghi hierarchy HTTP 200 sau `2286.115 s`, vượt ngưỡng Watchdog `120 s`; XML 7,840 bytes được lưu và checksum để chứng minh uiautomator2 vẫn hoạt động sau nhiều vòng health check.

## Phạm vi còn cần con người xác nhận

AC1–AC5 và device runtime evidence đã đạt theo Approved Device Target contract. Distributed-systems reviewer, security reviewer và QA/operator vẫn cần ký evidence pack trước khi gọi production DoD `DONE`. Báo cáo này không thay thế Play enrollment, 14-day chronology, payment/provider, private storage hoặc production deployment gates của các task khác.
