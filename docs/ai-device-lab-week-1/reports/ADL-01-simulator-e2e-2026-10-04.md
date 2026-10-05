# ADL-01 simulator E2E evidence — 2026-10-04

## Kết luận

`ADL-01 DEVICE ACCEPTANCE PASS — APPROVED EMULATOR TARGET`.

Luồng scenario đã chạy end-to-end qua backend API, relay `agent-boot`, ADB và UIAutomator2 trên Android Emulator. Theo Approved Device Target contract đã cập nhật, emulator có canonical serial, profile riêng, observed package/version, relay control và evidence được chấp nhận cho ADL-01. Play enrollment và các provider gate khác vẫn thuộc task riêng.

## Môi trường

- AVD: `galaxy_note10_plus`, serial `emulator-5580`.
- Android 15, API 35, ARM64; model `sdk_gphone64_arm64`.
- Chạy headless, `read-only`, không load snapshot, GPU host.
- Backend local healthy; relay container `agent-boot` kết nối emulator qua shared host ADB.
- Bootstrap runtime: ATX, UIAutomator2, STFService, quyền và U2 IME đều ready.

Metadata có cấu trúc nằm tại [environment.json](evidence/adl-01-simulator-2026-10-04/environment.json).

## Simulator acceptance

Cả năm tiêu chí thay thế `SIM-AC1`–`SIM-AC5` đều `PASS`; kết quả máy đọc được nằm tại [simulator-acceptance.json](evidence/adl-01-simulator-2026-10-04/simulator-acceptance.json):

| Tiêu chí | Kết quả | Bằng chứng |
|---|---|---|
| SIM-AC1 — identity/version/correlation | PASS | serial, Android/package version, timestamp và trace IDs được persist |
| SIM-AC2 — pass/fail/blocked/offline | PASS | positive assertion pass; missing element, missing capability và disconnected relay không pass |
| SIM-AC3 — retry/capture separation | PASS | absolute step index, failed-attempt artifact và no-cache failure capture regressions pass |
| SIM-AC4 — TTL/cross-org | PASS | URL được ký lại từ object key; cross-org trả 404 |
| SIM-AC5 — capture error/integrity | PASS | missing capture có trạng thái rõ; screenshot/hierarchy có SHA-256 |

## E2E đã chạy

### Capability preflight

Lần gọi trước bootstrap bị chặn với HTTP `400`, `node_capability_preflight_failed`, thiếu `has_u2` ở bước `assert_element`. Sau khi cài ATX/UIAutomator2/STFService và restart riêng `agent-boot`, relay probe lại capability rồi mới cho phép chạy scenario. Raw response trước bootstrap được giữ tại [prebootstrap-preflight-response.txt](evidence/adl-01-simulator-2026-10-04/prebootstrap-preflight-response.txt).

### Positive path

Request mở `com.android.settings`, sau đó assert phần tử có text `Settings`:

- HTTP `200`.
- `success=true`.
- `steps_executed=2`.
- `launch_app` pass; `assert_element` pass.

Artifact: [request](evidence/adl-01-simulator-2026-10-04/pass-request.json), [response](evidence/adl-01-simulator-2026-10-04/pass-response.json), [HTTP status](evidence/adl-01-simulator-2026-10-04/pass-http-status.txt), [screenshot](evidence/adl-01-simulator-2026-10-04/settings-screen.png), [UI hierarchy](evidence/adl-01-simulator-2026-10-04/settings-hierarchy.xml).

### Negative path

Request mở Settings rồi assert text `__ADL_ELEMENT_THAT_MUST_NOT_EXIST__` với timeout 3 giây:

- HTTP `200`; transport/API hoàn tất bình thường.
- `success=false`.
- Bước mở app pass.
- Bước assertion fail với thông báo phần tử không hiển thị sau 3 giây; policy dừng scenario được áp dụng.

Artifact: [request](evidence/adl-01-simulator-2026-10-04/fail-request.json), [response](evidence/adl-01-simulator-2026-10-04/fail-response.json), [HTTP status](evidence/adl-01-simulator-2026-10-04/fail-http-status.txt).

### Offline và recovery

`agent-boot` được dừng riêng trong khi emulator vẫn chạy. Scenario trả HTTP `200` với `success=false`, `reason_code=device_lost`, dừng tại bước `launch_app` vì không còn control channel. Sau khi relay khởi động lại và probe capability, cùng positive scenario pass lại `2/2` bước. Artifact: [offline response](evidence/adl-01-simulator-2026-10-04/offline-response.json), [recovery response](evidence/adl-01-simulator-2026-10-04/recovery-response.json).

### Retry, capture, TTL và tenant isolation

Focused backend regression chạy `10 passed`, bao phủ Temporal retry giữ absolute step index, failed-attempt evidence, hai failure không dùng stale screenshot cache, required/missing capture behavior, stable object key + re-sign khi đọc và cross-org 404. Output: [regression-tests.txt](evidence/adl-01-simulator-2026-10-04/regression-tests.txt).

## Performance smoke

Ba lần chạy positive path tuần tự trên cùng emulator đều pass:

| Run | HTTP | Total time | Result |
|---|---:|---:|---|
| 1 | 200 | 2.607 s | pass |
| 2 | 200 | 1.903 s | pass |
| 3 | 200 | 1.637 s | pass |

Trung bình `2.049 s`, tối đa `2.607 s`. Đây là smoke measurement trên một AVD local, không phải capacity/load test và không chứng minh mục tiêu 12 điện thoại của ADL-06/07/21. Raw metrics nằm tại [performance-summary.json](evidence/adl-01-simulator-2026-10-04/performance-summary.json).

## Tính toàn vẹn và giới hạn

- SHA-256 của screenshot và hierarchy nằm tại [checksums.sha256](evidence/adl-01-simulator-2026-10-04/checksums.sha256).
- Screenshot hiển thị màn Settings; hierarchy chứa text `Settings`.
- Emulator vẫn đang chạy để có thể tiếp tục test local.
- Manifest SHA-256 của toàn bộ evidence bundle nằm tại [manifest.sha256](evidence/adl-01-simulator-2026-10-04/manifest.sha256).
- ADL-01 device acceptance là `COMPLETE/PASS` trên Approved Emulator Target. ADL-19a vẫn cần chạy hygiene/reset/quarantine protocol trên emulator; các gate fleet vẫn cần đủ số instance và chronology của task tương ứng. Không còn blocker bắt buộc phone vật lý cho ADL-01.
