# AI Device Lab — kế hoạch giao sản phẩm PRODUCTION

> **PHẠM VI:** Sản phẩm production đầy đủ. Có **28 file task ADL** (00…21 với subdivisions), mỗi file đã được viết lại với giao nhận, source/gap, contract, bước làm, acceptance, test matrix và review/DoD. Đọc [PRODUCTION-CONTRACT.md](PRODUCTION-CONTRACT.md), [dependency/register](DELIVERY-REGISTER.md) và task trước implement. Không dùng prototype/test fixtures thay sản phẩm thật hoặc cắt tính năng để vừa deadline.

Nguồn: [`../ai-device-lab-research-and-tasks.md`](../ai-device-lab-research-and-tasks.md) (ADL-01…20); PRD [`../AI_Device_Lab_Product_Presentation_Final.pdf`](../AI_Device_Lab_Product_Presentation_Final.pdf). Rà soát source tại worktree ngày 02/10/2026; đây là **kế hoạch**, chưa phải các hạng mục đã hoàn thành. Mỗi liên kết ADL bên dưới là **một file, một definition of done**. Các mã a/b/c tách những task trong tài liệu gốc vốn có nhiều mốc.

## Mục tiêu một tuần và ranh giới nghiệm thu production

**Sprint 02–08/10/2026:** mục tiêu triển khai và tích hợp **toàn bộ chức năng production**, không chỉ một vertical slice: intake/AI approval, order/payment, readiness, reservation 12 máy, 168 slots, runtime adapter, secret management, dashboard, issues/retest, report/PDF, RBAC/audit và vận hành. Mọi task chưa đạt cuối tuần phải ghi `BLOCKED/FAIL/NOT_STARTED`, tác động deadline và người xử lý; không tự chuyển thành “phase sau MVP”. Chưa có sizing và đội thực tế xác nhận nên đây là **target**, chưa phải cam kết khả thi. 03–04/10 chỉ xếp làm việc khi đội xác nhận; 14 ngày kiểm chứng liên tục không được mô phỏng thành evidence thật.

**Capacity gate D1:** technical lead xác nhận owner và estimate giờ cho từng task, năng lực BE domain/billing/runtime/security, FE, QA automation, DevOps và operator; capacity 12 Approved Device Targets (physical Android hoặc 12 emulator instance độc lập theo `PRODUCTION-CONTRACT`) + cohort tài khoản được phép; provider, storage, deployment và môi trường test. Chưa xác nhận capacity thì trạng thái lịch là `UNVALIDATED`, không khẳng định đủ người hay đủ thời gian. Các estimate cũ 2–7 ngày/task cho thấy target một tuần có rủi ro cao; báo thiếu capacity/đường găng, không hạ DoD.

**Waiver hiện tại:** [WVR-12](CAPACITY-WAIVER.md) cho phép dùng một Approved Device Target để đóng device-execution acceptance trong giai đoạn hiện tại. Domain/API/tests vẫn giữ contract 12 lanes/168 slots và các invariants mở rộng; báo cáo không được tuyên bố đã đo capacity 12 thiết bị.

| Ngày | Ưu tiên/gate | Giao nhận dự kiến |
|---|---|---|
| D1 02/10 | capacity, contract, baseline | 00, 01, 20a; khóa schema/API/job contract, owners, estimate, provider, retention/video và deployment; thiết kế 04/09/18a/21 song song |
| D2–D3 03–04/10 | chỉ khi đội xác nhận trực | chuẩn bị branches/contracts/fixtures; không giả định capacity cuối tuần để báo deadline chắc chắn |
| D4 05/10 | foundation production | mục tiêu 02/03a/03b/04/18a/19a đạt gate; 05/09/15/16 bắt đầu sau dependencies; FE xây trên contract, mock chưa được đóng task |
| D5 06/10 | tích hợp dịch vụ | mục tiêu 05/09/15/16/18b đạt; nối 06/07/13a/13b/14 và 17/19b; QA race/isolation/provider tests |
| D6 07/10 | hoàn thiện hành trình | mục tiêu 08/10/11/20b/21 tích hợp; E2E full journey + 12 Approved Device Targets, reconciliation, deployment/restore/rollback rehearsal |
| D7 08/10 | production candidate review | đối chiếu tất cả task; nếu functional/operational gate đạt thì bắt đầu 12 kiểm chứng 14 ngày và hoàn thiện 20c sau kỳ đo; chưa được ghi launch production trước gate cuối |

**Quan hệ:** 00 → mọi chỉnh sửa API/runtime; 01 → 03a; 01 → 19a; 20a → copy/UX của 02 & 13a; 01 → 02 → 13a; 02 → 18a. Foundation 18a được xây song song với 02 nhưng chỉ đóng khi policy được test trên đường intake/dispatch. Một task có thể hoàn tất sớm/muộn, không tự coi ngày lịch là bằng chứng pass.

**Lịch trên là checkpoint target chưa được sizing xác nhận, không phải bằng chứng mỗi nhóm task làm được trong một ngày.** Contract/schema/permission design làm sớm; integration acceptance chỉ đóng sau dependency thật. [DELIVERY-REGISTER.md](DELIVERY-REGISTER.md) chỉ rõ sequence để không tạo vòng phụ thuộc hoặc gọi phần thiết kế là task đã DONE.

## Toàn bộ phạm vi production — không phải backlog tùy chọn

| Nhóm | Task (đọc file để thấy code gap, acceptance, case, gate) |
|---|---|
| Foundations và UX | [00](ADL-00-worktree-contract.md), [01](ADL-01-real-run-proof.md), [02](ADL-02-intake-scenario-approval.md), [03a](ADL-03a-track-proof.md), [13a](ADL-13a-landing-to-draft.md), [18a](ADL-18a-fail-closed-foundation.md), [19a](ADL-19a-device-hygiene-proof.md), [20a](ADL-20a-prototype.md) |
| Cohort + contract | [03b](ADL-03b-self-service-participation.md), [04](ADL-04-service-campaign-one-slot.md), [05](ADL-05-twelve-device-reservation.md), [16](ADL-16-farm-adapter.md), [18b](ADL-18b-secret-reference.md) |
| Paid + readiness | [09](ADL-09-order-payment.md), [06](ADL-06-readiness-gate.md), [14](ADL-14-wizard-payment.md), [13b](ADL-13b-landing-to-paid.md), [15](ADL-15-rbac-audit.md) |
| 12×14 execution | [07](ADL-07-schedule-quota.md), [08](ADL-08-three-progress-dashboard.md), [19b](ADL-19b-fleet-operations.md), [17](ADL-17-evidence-retention.md), [10](ADL-10-build-issue-retest.md) |
| Ship decision | [11](ADL-11-report.md), [20b](ADL-20b-kpi.md), [12](ADL-12-fourteen-day-pilot.md), [20c](ADL-20c-acceptance-pack.md) |
| Production operations | [21](ADL-21-production-operations.md): deployment, monitoring, backup/restore, rollback, capacity và incident response |

**Phải triển khai trong target tuần 1:** khả năng reserve 12 máy/tạo 168 slots, provider checkout/webhook/refund, full UI, retest/report/secret/RBAC và production operations. **Phải nghiệm thu theo thời gian thật:** [12](ADL-12-fourteen-day-pilot.md) ít nhất 14 ngày kể từ start hợp lệ, counts/report cuối kỳ, KPI cohort thật và [20c](ADL-20c-acceptance-pack.md). Nếu bắt đầu kiểm chứng 08/10 thì không thể xong trước 22/10 cùng giờ, còn cần review cuối. Clock simulation chỉ kiểm logic scheduler, không thay proof 14 ngày. Release candidate chưa là production launch.

## Đối chiếu source: có gì và thiếu gì

| Vùng | Source đã đọc | Kết luận kiểm định tiếp |
|---|---|---|
| Runtime | `backend/db/models/{campaign,execution,scenario_version,schedule,device_reserve_session}.py`; `backend/services/{scheduler,campaign_dispatch,execution_trace}.py` | Có campaign/execution/version/schedule/claim TTL; chưa thấy service campaign, slot/lane/attempt, reservation dài hạn, track participation, order/entitlement. `ScheduleRun` không là slot service. |
| Baseline test | `backend/services/campaign/dispatcher.py:65` import `services.platform_entity_locator`; file chỉ còn trong `device_farm/services/` đang bị xóa, không có ở `backend/services/` | `uv run --no-sync pytest -q tests/test_epic04_step_capture.py tests/test_crypto.py tests/test_temporal_retry_step_indices.py` (từ `backend/`) dừng **trước collection** với `ModuleNotFoundError`. ADL-00 cần xác nhận migration/restore ownership rồi mới test code. |
| Evidence | `backend/services/execution/{epic06_capture_adapter,step_runner}.py`, `backend/api/routes/executions.py`, `backend/tests/test_epic04_step_capture.py` | Có object key và re-sign ở đường đọc, unit test; cần live capture + TTL/retry + phân quyền; `execution_trace.py` có giới hạn events 500/steps 2000 nên không thể đếm final report từ trang UI. |
| AI/secrets | `backend/runtime/ai/ai_scenario.py`, `backend/common/crypto.py` | LLM trả steps, không có contract phê duyệt/allowlist riêng cho customer goal; khi key vắng, `encrypt_password` trả plaintext → chặn onboarding credential khách hàng đến khi fail-closed. |
| Hygiene | `backend/services/device_override/service.py`, `backend/db/models/device_reserve_session.py` | Admin FSM reset/release không chứng minh clear app/account data vật lý hoặc quarantine sau reset fail; TTL claim không là reservation 14 ngày. |
| Frontend | `front-end/src/features/campaigns/`, `front-end/src/features/device-farm/services/generated/DeviceFarmApi.ts`, `front-end/package.json` | Có monitor + generated client; chưa có flow dịch vụ; `gen:api:sync` vẫn sao chép từ `../device_farm/swagger/openapi.json` trong khi worktree đang di chuyển sang `backend/`: phải xác nhận nguồn OpenAPI và sửa ở task đầu tiên cần API mới. |

Đây là xác nhận **source-only** trong checkout đang có nhiều thay đổi cá nhân, không phải kết quả chạy test/live. Đừng gộp/xóa các thay đổi đó. Trước khi sửa symbol chạy GitNexus `impact` (index cũ không index `backend/`: ghi rõ thiếu độ phủ và đọc source bổ sung); trước sửa route chạy `api_impact`; trước commit chạy `detect_changes`. Không kết luận code an toàn chỉ vì graph cũ trả 0 caller.

## Contract dữ liệu production cần thống nhất trước khi chia nhánh

Chi tiết contract nằm ở [04](ADL-04-service-campaign-one-slot.md), [03b](ADL-03b-self-service-participation.md), [05](ADL-05-twelve-device-reservation.md), [09](ADL-09-order-payment.md), [10](ADL-10-build-issue-retest.md), [16](ADL-16-farm-adapter.md). Tên canonical trong plan: `ServiceCampaign`, `Lane`, `RunSlot`, `RunAttempt`, `AppBuild`, `TrackParticipation`/`ParticipationEvent`, `DeviceReservation`, billing records và quota ledger. RunAttempt khác step retry trong `ExecutionStep.attempts_json`; trạng thái execution khác app verdict. Đây là thiết kế đề xuất cần reviewer ký, chưa là schema production đang tồn tại.

Ba progress: **service** (slot/quota/calendar), **app quality** (assertion/issue), **Play participation** (account/provenance). `Passed` chỉ khi có assertion được đánh giá; `Blocked/Unknown/Missed` không được nâng thành pass. 168 = 12×14 planned slots; 2.520 device-minutes là trần dự tính nếu mỗi slot ≤15 phút. Một account opt-out rồi re-opt-in phải tính lại 14 ngày, không reset lịch sử service.

## Vòng kiểm duyệt bắt buộc cho từng file

1. **Thiết kế trước code:** implementer gắn link PR/commit và diff phạm vi, reviewer kiểm contract, migration, RBAC, quota, idempotency, proof nguồn. `impact` + `api_impact` trước sửa nếu phù hợp; nếu GitNexus stale ghi lại kiểm chứng bằng source.
2. **Test tự động:** implementer thêm case trong từng file, chạy focused backend test + migration/DB concurrency nơi có dữ liệu, UI typecheck/i18n/browser nơi có UI; cung cấp lệnh, exit code, môi trường, artifact. Test mocks không thay chứng cứ điện thoại/provider.
3. **Kiểm duyệt độc lập:** QA/operator replay case âm và dương trên môi trường cho phép; security/product duyệt wording, secret/permissions và claims Google ở task liên quan. Với Approved Device Target lưu loại target (`physical`/`emulator`), serial đã che, thời gian, execution ID, version và screenshot redacted trong kho evidence riêng (không commit account/password/PII).
4. **Go/no-go:** reviewer ghi `PASS / BLOCKED / FAIL`, lý do, thời điểm, evidence refs và bug/owner. Fail → sửa → chạy lại focused tests + case liên quan → review lại; không đánh dấu `[x]` theo dự định. Thay API: sync OpenAPI + generated client; thay UI: browser desktop/mobile; thay device: cần live proof.

## Nguồn research và mức độ xác nhận

- [Google Play account requirements](https://support.google.com/googleplay/android-developer/answer/14151465): quy tắc 12 account opt-in liên tục 14 ngày dành cho personal developer account tạo sau 13/11/2023; chỉ được nộp đơn production access rồi Google duyệt.
- [Google Play closed testing](https://support.google.com/googleplay/android-developer/answer/9845334): tester cần tự opt-in; published link mất thời gian khả dụng; versionCode có thể đến từ track khác; closed paid app có thể phải mua.
- [Android Publisher `edits.testers` REST resource](https://developers.google.com/android-publisher/api-ref/rest/v3/edits.testers): chỉ đọc/ghi địa chỉ Google Groups trong track, **không phải** API xác nhận opt-in liên tục từng tài khoản; không hứa auto-verify qua API này.
- Repo source như bảng trên (02/10/2026). Có thử baseline focused pytest nhưng dừng ở import, **0 case được chạy**; chưa có thử nghiệm device/browser/provider được thực hiện khi tạo kế hoạch này.

**Quyết định cần product owner chốt D1:** ai cung cấp và đồng ý dùng tài khoản Play; ứng dụng/build/test account và phạm vi hành động; người có quyền duyệt; provider/currency/refund/quota, retention, video contract, SLO/RPO/RTO và tải đồng thời. Chưa chốt một yêu cầu thì ghi `BLOCKED_DECISION`, không tự bỏ tính năng. Nếu chưa chốt billing, không chuyển task [09](ADL-09-order-payment.md) thành charge thật.
