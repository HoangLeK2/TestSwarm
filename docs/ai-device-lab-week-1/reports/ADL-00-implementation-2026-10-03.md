# ADL-00 — Báo cáo triển khai ngày 2026-10-03

## Trạng thái

`IN_REVIEW — BLOCKED_INPUT`. AC2–AC4 đã đạt. AC1 và AC5 vẫn cần backend maintainer, FE build owner, QA và migration owner xác nhận ownership cho worktree hiện có trước khi task được đánh dấu `DONE`.

Không stage, commit, push, deploy hoặc thay đổi dịch vụ production. GitNexus được rebuild sạch từ worktree hiện tại; `detect_changes --scope compare --base-ref main` ghi nhận mức `CRITICAL`: 320 file, 1.246 symbol và 21 execution flow. Kết quả này bao gồm lượng lớn thay đổi có trước ADL-00.

## Thay đổi trong phạm vi

- Chuyển đường dẫn vận hành và OpenAPI sang backend canonical `backend/`; tái tạo venv bằng lockfile.
- Bổ sung `services.platform_entity_locator` vào backend canonical để campaign dispatcher collect và chạy được.
- Loại toàn bộ route, service, UI, template, parser, fixture, test, kế hoạch và artifact runtime của tích hợp mạng xã hội cũ khỏi Platform Tester.
- Generic hóa session/account verification, XML extraction strategy và selector heuristics để không phụ thuộc một ứng dụng cụ thể.
- Regenerate scenario schema và OpenAPI client từ source canonical; xóa các snapshot/debug index đã stale.
- Giữ nguyên byte của migration đã áp dụng. Hai module `backend/services/scenario_migrations/` còn mapping dữ liệu legacy vì migration 111/126 import trực tiếp các module này khi khởi tạo hoặc nâng cấp database.
- Tách storage của Platform Tester khỏi Device Farm: backend chỉ nhận `ANDROID_PLATFORM_TESTER_DATABASE_URL`, từ chối database không thuộc namespace `android_platform_tester*`, và Compose dùng project, database, volume cùng cổng host riêng.
- Thêm migration 139 để xóa dữ liệu/bảng Facebook còn lại khỏi schema cuối. Migration lịch sử vẫn giữ nguyên checksum; bảng tương thích tạm chỉ tồn tại trong lúc chạy chuỗi migration cũ và không còn sau startup.

## Evidence

| Gate | Kết quả |
|---|---|
| Focused backend core | `167 passed, 2 warnings in 16.37s` |
| Focused backend sau cleanup cuối | `158 passed in 18.13s` |
| Backend E2E/N2N | `59 passed in 15.95s` |
| Agent-boot generic executor/flows | `129 passed, 47 warnings in 12.82s` |
| Scenario schema + STF source contracts | `5 passed in 0.05s` |
| Frontend flow editor | `142 passed`; cây khuếch đại trên 200 node; walk `2.5µs/op` |
| Playwright AI Device Lab E2E | `6 passed in 20.2s` |
| Frontend typecheck + i18n + navigation | PASS |
| Frontend production build | PASS; compile, typecheck, static generation và route manifest hoàn tất |
| Backend startup từ source hiện tại | `/api/live`, `/api/ready`, `/health/ready` trả 200 |
| Database isolation E2E | PostgreSQL riêng ở host port 55434; database `android_platform_tester`; migration 139; `/api/ready` trả `db: ok` |
| Database isolation tests | `21 passed, 1 warning in 1.53s` cho isolation, connection budget, app factory và migration regression |
| Schema sạch sau startup lặp lại | 0 database `device_farm`; 0 bảng/dữ liệu Facebook; 0 token legacy import; 0 bảng compatibility |
| Copied PostgreSQL fixture | migration 138; counts giữ nguyên: accounts 6, devices 5, executions 707 |
| OpenAPI/client idempotency | 347 paths; OpenAPI `915a8ae295f456ebcf394470783ab50d9b2fd226c50b1126e09d32f4ca5a13a1`; client `4f4472bac70a81b26f2a5c8bda7cffcaed295f5e35c6e591cf7a282c47309919` |
| Active integration scan | 0 match trong source/runtime/UI/docs/test ngoài migration compatibility |
| GitNexus change detection | `CRITICAL`: 320 file, 1.246 symbol, 21 flow |

Playwright chạy trên Chromium thật qua route AI Device Lab và kiểm sáu luồng responsive/navigation. Production build chạy lại sau cleanup cuối và hoàn tất thành công.

Database isolation được kiểm trên volume mới chỉ thuộc Compose project `android-platform-tester`. Hai lần chạy migration liên tiếp đều thành công, chứng minh clean install và startup idempotent. Container PostgreSQL Device Farm đang dùng cổng khác được giữ nguyên, không restart, không xóa volume và không truy vấn dữ liệu của nó.

Android agent source contract đã PASS. `./gradlew :app:assembleDebug` chưa chạy được vì máy không có Java Runtime (`Unable to locate a Java Runtime`), nên chưa có bằng chứng APK compile mới.

## Phần legacy bắt buộc giữ

- Migration database đã áp dụng không được đổi tên hoặc sửa byte vì hệ thống theo dõi checksum. Tên file còn lại gồm `104_facebook_candidates.py`, `138_facebook_login_password_method_continue.py` và các giá trị lịch sử trong migration liên quan.
- Migration 111/126 import `social_node_rename.py` và `platform_session_cleanup.py`; xóa hai module này sẽ làm clean install và upgrade database cũ lỗi giữa chừng.
- `facebook-wda` trong lockfile là tên upstream của dependency WebDriverAgent cho iOS, không phải tích hợp sản phẩm.

## Full-suite finding

Lần chạy full backend gần nhất, trước cleanup cuối, không xanh: `3059 passed, 4 skipped, 102 failed, 2 errors in 389.58s`. Sau đó các test social mồ côi đã được xóa và focused suite 158 test đã PASS, nhưng full suite chưa được chạy lại nên không được báo xanh.

Các failure baseline ngoài ADL-00 gồm XPath/U2 selector, scenario capture, live typing order, device install mock và workspace revoke. Cần triage riêng hoặc maintainer xác nhận ownership. ADL-00 không được đánh dấu `DONE` cho tới khi AC1/AC5 được ký và full-suite blockers có quyết định owner.

## Lệnh tái lập chính

Từ `backend/`:

```bash
uv sync --frozen
uv run --no-sync pytest -q tests/test_scenario_schema_snapshot.py tests/test_stf_apk_ws_reconnect.py
uv run export-openapi
```

Từ `agent-boot/`:

```bash
uv run pytest -q relay/tests/test_u2_executor.py relay/tests/test_u2_flows.py
```

Từ `front-end/`:

```bash
pnpm gen:api:sync
pnpm typecheck
pnpm check:i18n
pnpm verify:nav
pnpm test:flow-editor
pnpm test:e2e:ai-device-lab
pnpm build
```

Từ repository root:

```bash
node .gitnexus/run.cjs analyze
node .gitnexus/run.cjs detect-changes --scope compare --base-ref main -r device-farm
```
