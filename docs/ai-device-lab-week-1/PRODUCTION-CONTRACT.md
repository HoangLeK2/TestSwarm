# Hợp đồng triển khai PRODUCTION — đọc trước mọi task

## 1. Mục tiêu và ưu tiên diễn giải

Yêu cầu chủ sở hữu: **sản phẩm production đầy đủ**. Tên thư mục `week-1` là target thời gian triển khai, không định nghĩa mức chất lượng. Contract này áp dụng cho mọi file ADL; các task đã viết lại trực tiếp theo scope production. Không tự cắt tính năng để vừa deadline. Prototype chỉ phục vụ design review; mocks chỉ phục vụ tests.

Toàn bộ 28 task ADL-00…21 với 03a/b, 13a/b, 18a/b, 19a/b, 20a/b/c đều bắt buộc. Khi nhận một task riêng, agent phải đọc README, contract này, DELIVERY-REGISTER, task và dependencies trước khi code. Không suy trạng thái DONE từ chữ “đã có code” trong source/gap.

## 2. Không được tự suy diễn

### Thiết bị nghiệm thu hợp lệ

Trong toàn bộ bộ kế hoạch ADL, `phone`, `device`, `live device`, `real device` và `máy` được hiểu là **Approved Device Target** trừ khi một test ghi rõ `PHYSICAL_ONLY`. Approved Device Target có thể là:

1. điện thoại Android vật lý; hoặc
2. Android Emulator/AVD chạy độc lập, có canonical device ID/serial riêng, profile dữ liệu riêng, package/version quan sát được, relay/control channel thật, screenshot/hierarchy evidence và lifecycle online/offline/reset kiểm chứng được.

Emulator evidence có giá trị nghiệm thu ngang physical device cho runtime, scheduling, reservation, isolation, retry, capture, quarantine và capacity rehearsal. Một instance chỉ tính là một device; yêu cầu 12 devices cần 12 instance đồng thời và identity/evidence tách biệt. Snapshot clone chỉ hợp lệ sau khi cấp canonical ID riêng và chứng minh không dùng chung mutable profile/claim. Các bài kiểm phụ thuộc đặc tính phần cứng như USB, modem/SIM, camera/sensor, thermal, OEM firmware hoặc hardware attestation phải tự gắn `PHYSICAL_ONLY`; nếu không có nhãn đó thì không được từ chối emulator chỉ vì nó không phải máy vật lý.

Trong schema/evidence ledger hiện có, evidence kind `live-device` bao gồm cả physical Android và emulator đang chạy thật qua relay; record phải ghi thêm `target_type` để phân biệt. `live-device` không đồng nghĩa `physical-only`.

### Waiver capacity đang hiệu lực

[WVR-12](CAPACITY-WAIVER.md) tạm thời cho phép nghiệm thu device execution bằng một Approved Device Target. Waiver chỉ thay ngưỡng capacity runtime; mô hình 12 lanes/168 slots, transaction invariants và mọi gate provider/Play/14-day/reviewer vẫn giữ nguyên. Khi báo kết quả phải ghi rõ `observed_device_count=1`, không suy diễn đã đo tải 12 thiết bị.

- Không thay payment provider bằng admin-granted entitlement để đóng 09/14/13b. Sandbox kiểm integration; trước mở thu tiền phải xác nhận production credentials, webhook endpoint, reconciliation/refund và smoke payment theo chính sách được duyệt.
- Không dùng file operator ngoài DB thay model participation ở đường self-service: 03a là proof nguồn, 03b là persistence/API/UI production bắt buộc. Attestation thủ công hợp lệ phải có provenance, quyền review và audit; không giả danh Google verification.
- Không dùng manual scenario fallback để đóng khả năng goal→AI scenario của 02. AI unavailable phải có trạng thái lỗi/retry rõ; approval và version pin bắt buộc.
- Không thay reservation 12 máy bằng claim một máy; không thay 168 slots bằng demo một slot; không dùng mutable JSON làm nguồn truth duy nhất cho quota/billing/slot.
- Không thay private report/PDF bằng mock/download public; screenshot/log phải tồn tại và gắn attempt. Video là quyết định contract D1: nếu cam kết cung cấp thì MP4 production là gate; nếu hỗ trợ có giới hạn phải mô tả trung thực khả năng, không tự loại vì deadline.
- Không bỏ migration, RBAC, secrets, cancel/drain/hygiene, audit, accessibility/i18n, observability/backup/rollback để gọi chức năng “done”.
- Không gọi production candidate, staging deployment hay 7 ngày chạy là production nghiệm thu. Không lấy 168 run hoàn tất hoặc 336 giờ dịch vụ để tuyên bố Google cấp production access.

## 3. Definition of Done chung cho MỖI task

1. Acceptance riêng của file và dependencies PASS; behavior trên API/UI/runtime nhất quán với contract dữ liệu đã review.
2. Code production tích hợp thật, migrations có kiểm upgrade và rollback/recovery; OpenAPI/generated client không drift; không còn placeholder trên đường người dùng nhận dịch vụ.
3. Test cases của file có kết quả PASS/FAIL/BLOCKED, lệnh/exit code/environment/commit/evidence; DB concurrency thật cho transaction invariants. Browser E2E cho UI; device proof cho tác vụ máy; provider proof cho billing.
4. Backend authorization/tenant isolation kiểm cả đọc, mutate, export và URL cấp mới. Secrets mã hóa, capability scoped/TTL, không plaintext trong log/event/report/media.
5. Errors/timeouts/retries/cancel/replay và outage không làm duplicate billing/dispatch hoặc biến Unknown/Blocked thành Passed; history build/attempt/evidence bất biến.
6. Reviewer độc lập kiểm code + QA replay; findings sửa và rerun đúng impacted cases; operator/product/security review khi task liên quan. Agent không tự xác nhận review độc lập thay người chưa thực hiện.
7. Có metric/log correlation, support runbook và rollback/recovery phù hợp; triển khai bằng build/version truy vết được trên môi trường rehearsal giống production.

Trạng thái chuẩn: `NOT_STARTED → DESIGN_REVIEW → IMPLEMENTING → AUTO_TEST → INTEGRATION_QA → REVIEW → DONE`; lỗi chuyển `REWORK`, thiếu input chuyển `BLOCKED` kèm reason/owner/deadline. `DONE` của task nhỏ không tự đóng ADL cha nếu subdivision còn thiếu.

## 4. Ba gate release không được trộn

**G1 — Production candidate functional:** tất cả chức năng/operational tasks đạt DoD; trong thời gian WVR-12 có hiệu lực, device-runtime gate dùng một Approved Device Target và capacity 12-target được ghi `WAIVED`. Billing sandbox + production configuration validation, end-to-end report/retention/retest/cancel, restore/rollback rehearsal vẫn bắt buộc. Đây là target tuần 1, feasibility chờ capacity D1.

**G2 — Kiểm chứng chu kỳ:** ADL-12 chạy đủ 14 ngày trên cohort được phép, evidence theo ngày và mọi exception không bị chỉnh thành pass; KPI đo numerator/denominator/cohort thật; report cuối kỳ reconcile DB/API/browser/Approved Device Target/provider. Chưa qua G2 thì ADL-12/20c chưa DONE.

**G3 — Launch production:** ADL-20c nghiệm thu toàn bộ G1/G2/21, owner ký go/no-go, production payment/infra readiness, on-call/backup/rollback/retention có bằng chứng. Google production access của app khách hàng là quyết định độc lập của Google.

## 5. Deadline và escalation

Một tuần là target triển khai, không rút ngắn thời gian kiểm chứng 14 ngày. Technical lead phải estimate giờ/owner cho từng file và tính critical path + capacity thực D1. Nếu không đạt deadline: báo task thiếu, evidence thiếu, dependency, capacity thiếu, earliest finish và người quyết định lịch; không tự chuyển thành MVP hay ghi DONE. Những estimate task 3–7 ngày trong research cũ phải được tái-sizing; không giả định tất cả có thể chạy song song dù dependencies chưa đạt.

## 6. Thiết kế, integration và evidence handoff

Dependency **contract** cho phép schema/DTO/policy design phối hợp trước khi downstream có code; dependency **integration** phải có implementation/test PASS trước đóng outcome. Không đặt schema AppBuild sau khi RunAttempt đã cần FK; 04/10 phải chốt cùng lúc. RBAC 15, policy 18a, retention 17, KPI definitions 20b và operations 21 thiết kế D1, không đợi UI/payment xong.

ADL-20b giao feature instrumentation và protocol; real cohort threshold validation được bàn giao rõ sang ADL-12/20c. Không dùng handoff này để ghi thresholds đạt sớm. ADL-12 phụ thuộc G1 và 20b protocol, **không** phụ thuộc 20c; 20c phụ thuộc 12 để tránh circular release gate.

Khi test fail, ghi finding ID, task/AC/test ID, commit/env, expected/observed, severity/impact, evidence, owner, fix version và retest result. Test chưa chạy phải NOT_RUN, thiếu environment BLOCKED; không ghi PASS. Evidence ở kho private theo retention policy, task lưu reference thôi. Reviewer độc lập chưa thực hiện phải PENDING_REVIEW; agent không tự ký thay người.
