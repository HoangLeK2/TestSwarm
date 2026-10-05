# ADL-01 — Chứng minh execution Android trên Approved Device Target

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Runtime verification gate / AUTO_TEST_PASS trên emulator; independent review pending |
| Owner / reviewers | BE runtime + operator / QA + security |
| Dependencies | ADL-00; app, serial, org và phạm vi Approved Device Target được cho phép |
| Deliverable | Run có assertion thật; API/DB/browser/device evidence; regression fix nếu tái hiện |

## 2. Source và giới hạn
`backend/services/campaign_dispatch.py`, `backend/services/execution/{epic06_capture_adapter,step_runner,capture_service}.py`, `backend/api/routes/executions.py` đã có capture refs/re-sign/retry logic. Suites `test_epic04_step_capture.py`, `test_temporal_retry_step_indices.py`, `test_execution_access.py` là baseline để tái chạy. Android Emulator đáp ứng Approved Device Target contract khi có serial riêng, runtime relay thật, observed package/version và screenshot/hierarchy evidence.

## 3. Contract và triển khai
1. Khóa org/workspace/serial/allowed package và target type (`physical`/`emulator`); operator xác nhận online và runtime claim trước dispatch. Ghi observed installed package/versionCode, không suy diễn từ requested build.
2. Dùng safe scenario có assertion đo được: launch/wait/assert nội dung được phép. Không có assertion thì verdict inconclusive, không Passed.
3. Lưu identity chain dispatch→execution→step_path/index→capture object/attempt và expected/observed.
4. Thực hiện fail hai bước sát nhau, retry, upload failure và reopen sau signed URL TTL; capture cache/object key phải phân biệt đúng step/attempt.
5. Chứng minh Temporal/fallback nếu cả hai là đường deployment hỗ trợ; nếu bỏ một engine phải có quyết định kiến trúc, không giả vờ parity đã test.

## 4. Acceptance
- [ ] AC1: serial/org/version observed và timestamp có persisted evidence.
- [ ] AC2: assert pass/fail/blocked đúng tình huống; offline không pass.
- [ ] AC3: retry và hai failure không mất hoặc ghép nhầm ảnh.
- [ ] AC4: reopen sau TTL cấp URL mới và cross-org bị từ chối.
- [ ] AC5: capture lỗi có reason/missing status và live proof redacted.

## 5. Test matrix
| ID | Preconditions / action | Expected và evidence |
|---|---|---|
| 01-T1 | Approved sandbox scenario, Approved Device Target online đúng org | Assertion observed, DB step refs và screenshot target khớp |
| 01-T2 | Device target offline hoặc org khác | Dispatch reject/blocked; zero successful verdict |
| 01-T3 | Open screenshot sau actual TTL | URL mới đọc được; object key không đổi |
| 01-T4 | Hai failures + retry cùng execution | Đúng step/attempt ảnh; old evidence còn đọc được |
| 01-T5 | Storage upload fault | Missing/capture_error, không placeholder evidence |
| 01-T6 | Org B đọc API/artifact của A | Denied, không trả object URL hoặc identity |

## 6. Review và DoD
QA đối chiếu API/SQL/browser với Approved Device Target, runtime reviewer xem correlation/retry, security kiểm privacy/URLs. Evidence gồm target type, test commands, execution IDs, serial redacted, timestamps/version, captures và recording UI. Bug → fix impacted symbol sau impact → rerun case + focused suites → independent review. DONE cần AC1–5 PASS; one-target proof là prerequisite, không thay 12-device gate ADL-07.
