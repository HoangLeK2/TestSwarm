# ADL-00 — Khôi phục baseline và xác nhận source-of-truth production

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production prerequisite / IN_REVIEW — BLOCKED_INPUT (AC1, AC5) |
| Owner / review | Backend maintainer + FE build owner / QA + migration owner; tên người D1 |
| Dependency | Không; ownership và môi trường phải do maintainer xác nhận |
| Deliverable | Baseline chạy được, canonical paths, OpenAPI workflow, migration/test commands, evidence |

## 2. Evidence và vấn đề đã tái hiện
- Worktree ngày 02/10: `backend/` untracked, `device_farm/` nhiều deletion, FE có thay đổi có trước.
- `backend/services/campaign/dispatcher.py:65` import `services.platform_entity_locator`; không tìm thấy module trong backend tại lúc rà soát. Không mặc định copy bản cũ nếu migration chủ ý bỏ dependency.
- Lệnh từ `backend/`: `uv run --no-sync pytest -q tests/test_epic04_step_capture.py tests/test_crypto.py tests/test_temporal_retry_step_indices.py` dừng trước collection với ModuleNotFoundError. **Không có test nào PASS từ lần này.**
- `front-end/package.json:gen:api:sync` dùng path `../device_farm/swagger/openapi.json`; cần canonical backend/OpenAPI path.

## 3. Contract và bước làm
1. Snapshot git status/diff có trước; maintainer ký danh sách migration ownership và file được sửa. Không tự restore/xóa/stage toàn worktree.
2. Xác nhận backend canonical, import root, Python interpreter/venv path và pytest plugin provenance; loại tình trạng test load support từ checkout khác.
3. Xác định intended replacement của resolve_entity_locator; kiểm mọi caller/import, chạy impact trước sửa symbol, review compatibility rồi sửa dependency đúng migration.
4. Chạy startup/import smoke, migrations trên DB thử và focused suites. Lỗi tiếp theo mở finding kèm path/trace, không bỏ plugin/test để có màu xanh.
5. Xác nhận lệnh export OpenAPI và generate client; regenerate rồi kiểm diff drift. Ghi commands/workdir/env cần thiết, không ghi secrets.

## 4. Acceptance
- [ ] AC1: ownership/canonical layout được maintainer xác nhận.
- [x] AC2: focused tests collect và execute trên checkout hiện tại; failures được xử lý hoặc blocker rõ, không báo baseline PASS khi suite fail.
- [x] AC3: backend startup và DB migration thử thành công.
- [x] AC4: OpenAPI/client sync chạy từ canonical source, không stale path.
- [ ] AC5: intended diff không ghi đè user edits; environment tái lập được.

## 5. Test matrix
| ID | Hành động | Kết quả / evidence |
|---|---|---|
| 00-T1 | Repeat command đã fail sau migration fix | PASS: focused backend core 167/167; E2E/N2N 59/59; agent generic 129/129 |
| 00-T2 | Start backend trên test DB/config | PASS: `/api/live`, `/api/ready`, `/health/ready` đều 200 |
| 00-T3 | Export OpenAPI, generate client hai lần | PASS: lần hai không drift; 347 paths; FE typecheck, Playwright 6/6 và production build thành công |
| 00-T4 | Upgrade migration trên copied fixture DB | PASS: schema version 138; accounts/devices/executions giữ nguyên 6/5/707 |
| 00-T5 | Compare intended files với baseline ownership | BLOCKED_INPUT: cần maintainer ký ownership của worktree đang có 320 file thay đổi |
| 00-T6 | Clean install + startup lặp lại trên database riêng | PASS: migration 139; database `android_platform_tester`; 0 database/bảng/dữ liệu Facebook và 0 token legacy import |
| 00-T7 | Backend health E2E với PostgreSQL riêng | PASS: `/api/live`, `/api/ready` (`db: ok`) và `/health/ready` đều HTTP 200; shutdown sạch |

## 6. Kiểm duyệt và DoD
Maintainer review imports/migration, FE owner review client pipeline, QA chạy T1–4 từ commands đã ghi. Lưu sanitized error-before/fix-after, commit, schema diff và test outputs. Fail → REWORK hoặc BLOCKED_INPUT, ghi owner/ETA. DONE chỉ khi AC1–5 PASS; task này không xác nhận Approved Device Target runtime hay production readiness thay các task sau.

Evidence triển khai: [`reports/ADL-00-implementation-2026-10-03.md`](reports/ADL-00-implementation-2026-10-03.md).
