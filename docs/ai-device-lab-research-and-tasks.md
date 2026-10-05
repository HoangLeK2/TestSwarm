# AI Device Lab — research và backlog triển khai

**Ngày rà soát:** 02/10/2026  
**Nguồn yêu cầu:** [`AI_Device_Lab_Product_Presentation_Final.pdf`](./AI_Device_Lab_Product_Presentation_Final.pdf), PRD v3.1, 30/09/2026.  
**Trạng thái:** backlog đề xuất bao phủ toàn bộ deck, chưa xác nhận bằng một campaign closed testing thực tế. Các ID `ADL-*` chỉ là mã task trong tài liệu, không phải issue đã mở.

## 1. Kết luận nghiên cứu

**Khả thi như một dịch vụ kiểm thử Android có bằng chứng, nhưng chưa thể coi 12 thiết bị là 12 tester hợp lệ của Google Play.** Google áp dụng yêu cầu closed test với tối thiểu **12 tài khoản tester opt-in liên tục 14 ngày** cho personal developer account tạo sau 13/11/2023; sau đó developer *có thể nộp* hồ sơ xin production access, còn Google đánh giá riêng quá trình thử nghiệm, tương tác và phản hồi. Tài khoản opt-out rồi opt-in lại phải bắt đầu lại quãng 14 ngày liên tục. [G1]

Theo hướng dẫn của Google, người tham gia closed test cần có Google Account/Workspace account, nằm trong danh sách/nhóm được phép và **tự opt-in** bằng liên kết. Testing link chỉ xuất hiện khi release ở trạng thái Published; có thể mất vài giờ để khả dụng. Cài APK trực tiếp, mở app hay một thiết bị chạy scenario **không** chứng minh tài khoản đã opt-in; một bản cài cũng có thể nhận versionCode cao hơn từ track khác. [G2]

Vì vậy phải theo dõi **ba nguồn sự thật**: (1) thời gian/quota dịch vụ, (2) các run kiểm thử và evidence, (3) trạng thái Play closed-track của *từng tài khoản*. Không tự tính 336 giờ kể từ lúc thanh toán hay kể từ lần chạy đầu tiên là bằng chứng Google đã công nhận 14 ngày. Không ghi “Google approved”, “đủ 12 tester” hay “100% pass” khi thiếu nguồn xác minh. [G1][PRD]

### Điều chỉnh so với bản task đề xuất trước

- **Đã có code sửa** cho `screenshot_object_key`/re-sign URL lúc đọc, absolute step index trên Temporal và giữ ảnh qua retry tại `backend/services/execution/epic06_capture_adapter.py`, `backend/api/routes/executions.py`, `backend/services/execution/step_runner.py` và `backend/services/execution/capture_service.py`. Task dưới đây là **xác minh end-to-end và sửa nếu tái hiện**, không mặc định làm lại. [S1]
- `backend/` có trong worktree hiện tại nhưng chưa tracked, còn `device_farm/` đang được đánh dấu xóa hàng loạt. Repo-brain và GitNexus được xây trên checkout cũ và hiện không index `backend/`; các dẫn chiếu source dưới đây đến từ việc đọc trực tiếp `backend/`, không phải xác nhận trên runtime hay graph mới. Xác nhận migration/ownership trước khi code.
- 168 = **12 logical lanes × 14 ngày × 1 slot/lane/ngày**; 2.520 device-minutes là **giới hạn kế hoạch** nếu mỗi run tối đa 15 phút, không phải kết quả đã đo và không phải yêu cầu Google. [PRD]

## 2. Hiện trạng và phần còn thiếu

| Nhu cầu | Bằng chứng hiện có trong checkout | Còn phải chứng minh/xây dựng |
|---|---|---|
| Scenario, campaign và execution | `backend/db/models/campaign.py`, `backend/db/models/execution.py`, `backend/api/routes/campaigns.py`; schema scenario có `launch_app`, `install_apk`, `wait_element`, `assert_element` | Chưa có app-testing service campaign gắn order, 14 ngày và từng run slot; scenario AI phải được duyệt trước khi chạy. |
| Lịch chạy và fan-out | `backend/api/routes/schedules.py`, `backend/services/scheduler.py`, `backend/temporal/schedule_workflow.py`; có run history và idempotency path | Chưa có mapping 12×14 slot, quota/replacement, readiness gate và bằng chứng 14 ngày; tạo schedule ≠ thực thi trên máy. |
| Device Pool | `backend/api/routes/workspace_admin.py`, `backend/db/models/device_reserve_session.py` | Workspace transfer và runtime claim/TTL không phải hợp đồng giữ 12 máy xuyên campaign; cần reservation theo khoảng thời gian, chống double booking, cleanup. |
| Run evidence | `backend/services/execution/{epic06_capture_adapter,step_runner,step_store}.py`, `backend/api/routes/{executions,artifacts}.py` | Source có fix nhưng chưa có bằng chứng được cung cấp về run thật, reopen > TTL, retry, artifact có phân quyền; cần test/live proof và chính sách retention tối thiểu bằng thời gian cung cấp report. |
| Google Play participation | Không thấy model `TrackParticipation` hoặc order/payment trong `backend/db/models/` | Cần tài khoản Play riêng biệt, provenance opt-in có thời điểm/nguồn, trạng thái không xác minh được; không nội suy từ device hay run. |
| UI/report/billing | `front-end/src/features/campaigns/` có monitor; `front-end/src/features/schedules/` có schedule UI | Chưa có wizard self-service, phân tách tiến độ, final report đóng băng, order/payment; dùng lại generated API client và i18n. |
| AI scenario | `backend/runtime/ai/ai_scenario.py` và scenario schema/node catalog có các primitive điều khiển app | Chưa chứng minh goal → scenario version với assertions, approval, allowlist và trace trên app bất kỳ; discovery/contract test trước khi dùng cho khách hàng. |
| Export completeness | `backend/db/models/execution_event.py` giữ event theo `step_path`; `backend/services/execution_trace.py` cap số step/event khi đọc; streaming video tồn tại nhưng không chứng minh có MP4 gắn execution | Report không được đếm từ trang `task-log` có giới hạn; cần truy vấn phân trang/snapshot toàn bộ, chính sách lưu video/log/capture và biểu thị missing evidence. |
| Secret handling | `backend/common/crypto.py` mã hóa account password **nếu có key**, còn dev mode lưu nguyên văn | Chưa có job-scoped reference/retention/redaction đã chứng minh cho customer app credential; phải fail closed trong deployment dịch vụ nếu encryption chưa bật. |

**Mức evidence hiện tại:** PDF + chính sách Google + source inspection; repo-brain read-only có artifact `repoos_artifacts:d03ec384-040b-472e-b85f-6be1fa31d3a1` và `repoos_artifacts:835774ac-00e0-441d-88f1-f6db1fed4e76` (lần sau báo không thấy `backend/`, nên **không** dùng làm xác nhận path hiện tại). Chưa chạy test, browser E2E, thanh toán hay thiết bị thật trong lần research này. Source không chứng minh runtime.

## 3. Các quyết định cần chốt trước khi nhận tiền

1. **Tên và lời hứa dịch vụ.** “12 AI testers” chỉ là 12 luồng kiểm thử trên máy; nếu tuyên bố đáp ứng điều kiện Google thì phải chứng minh 12 *Google accounts* opt-in liên tục bằng nguồn phù hợp. MVP nên hiển thị “12 AI device lanes” và số tài khoản Play đã được xác minh **riêng**.
2. **Nguồn tester và quyền tham gia.** Ai cung cấp/quản lý 12 Google accounts, ai đồng ý tham gia test, ai xác minh opt-in? Nếu khách hàng chỉ mua kiểm thử AI trên thiết bị, tránh cam kết rằng gói này tạo ra 12 tester được Google công nhận.
3. **Ngày bắt đầu.** Chỉ khởi động đồng hồ dịch vụ sau readiness đủ điều kiện và thời điểm start đã ghi; theo dõi mốc opt-in riêng theo từng tài khoản. Nếu một account mất opt-in, không tiếp tục hiển thị “14 ngày liên tục đạt” cho account đó. [G1]
4. **Build và môi trường.** MVP ưu tiên phát hành qua Play closed track; APK sideload chỉ là nhánh diagnostic và phải được gắn nhãn không chứng minh track enrollment. Xác định app có IAP/paid app, OTP, quyền nhạy cảm hoặc ghi dữ liệu thật trước khi duyệt scenario. [G2]
5. **Gói/giá và bồi hoàn.** Chốt nhà cung cấp thanh toán, tiền tệ, thời điểm charge, cutoff khi thiếu 12 máy/track, refund, extension và giới hạn retest; không giả định con số 23–34 ngày build trong deck là cam kết kỹ thuật.
6. **Quyền truy cập.** Trong MVP một owner có thể là developer; admin farm vận hành máy nhưng không mặc nhiên được xem secret/Play-account identity đầy đủ. Chốt role được thanh toán, duyệt scenario, xử lý blocker, xem report và xuất artifact trước khi mở self-service.
7. **Điểm nghẽn từ chính PRD.** Slide 5 loại “human tester recruiting” khỏi MVP nhưng slide 2 nhắc điều kiện 12 tài khoản opt-in; dịch vụ chỉ có thể *theo dõi* cohort có thật và báo mức chứng cứ, không bán lời hứa đạt yêu cầu 12 tester nếu chưa có mô hình tài khoản/đồng ý tham gia được xác minh. Bên cạnh đó slide 7 nói readiness bắt đầu sau payment: cần nói rõ refund/hoãn khi track không khả dụng và sức chứa farm không đủ.

## 4. Backlog có thứ tự phụ thuộc

Mỗi task mang một hành vi quan sát được qua API/UI/runtime; nơi chưa cần UI khách hàng, dùng operator view hoặc artifact có thể kiểm tra. `P0`/`P1`/`P2` ở ID cũ là phân loại ưu tiên **không trùng** với phase P0–P5 trên slide 17. Ở cuối có ma trận phase của deck. Thời lượng bên dưới là **ước lượng cần kiểm định**, không phải commitment.

### ADL-01 — Proof: một run Android an toàn có evidence thật (P0, ~3–5 ngày)

**Blocked by:** Không.  
**Outcome:** Operator chọn đúng workspace + serial, chạy một scenario chỉ đọc trên app kiểm thử được phép; theo dõi từ dispatch → execution → step → artifact trong cùng một màn hình.

**Acceptance**
- [ ] Chứng minh serial/workspace/online state ngay trước dispatch; scenario không mua hàng, click ads, sửa production data hay tự vượt OTP/CAPTCHA.
- [ ] Execution có timestamp, package/installed-version quan sát được (nếu thiếu thì ghi Unknown), step expected/observed và artifact mở được; offline hoặc không có assertion hợp lệ không thành Passed.
- [ ] Sau >1 giờ mở lại screenshot; hai step fail gần nhau vẫn đúng ảnh/step; retry không làm mất evidence cũ, capture lỗi hiện rõ. Chỉ sửa code nếu các case này fail trên checkout hiện tại.
- [ ] Có artifact redacted từ API, browser và real phone; kiểm tra đường Temporal lẫn fallback nếu pilot dùng cả hai.

**Verify:** focused test capture/retry/scheduler có sẵn trong `backend/tests/` (xác định đúng tên theo checkout), API persisted rows, browser `flow:agent --execute`, một live-device proof với serial an toàn. **Gate:** không khởi động P1 trước khi proof này đạt.

### ADL-02 — Một app-test intake và scenario được duyệt (P0, ~2–4 ngày)

**Blocked by:** ADL-01.  
**Outcome:** Developer nhập app/package, closed-testing link, test goal và build/version dự kiến; hệ thống tạo scenario draft từ goal nhưng chưa dispatch cho đến khi developer/operator duyệt scope hành động.

**Acceptance**
- [ ] Wizard lưu bản nháp tenant-scoped, validate package/link nhưng không coi link hợp lệ là track access đã xác minh.
- [ ] Scenario draft có flow, assertion và permission allowlist cố định; UI của app không thể tăng quyền tool. OTP/CAPTCHA chuyển human assist; có thể chọn luồng chỉ đọc khi app cần credential.
- [ ] Review cho biết hành động nào được phép, expected assertion nào đo được và có bước unsafe nào bị từ chối; lưu scenario version để build sau không ghi đè history.

**Verify:** API + UI create/edit/approve, validator/backend schema, generated client + EN/VI i18n, browser E2E cho draft/blocked state.

### ADL-03 — Closed-track participation của một tài khoản (P0, ~3–5 ngày)

**Blocked by:** ADL-01 cho operator P0; ADL-02 chỉ khi chuyển sang intake self-service ở P1.  
**Outcome:** Operator ghi nhận/kiểm chứng một Play account có quyền vào closed track bằng evidence có provenance, sau đó test install/open đúng app/build trên một máy.

**Acceptance**
- [ ] `TrackParticipation` tách khỏi result của `Execution`; lưu account identity đã che, package/track, opt-in evidence source, observed-at, reviewer và trạng thái `unknown/verified/lost` (hoặc tương đương); bản xác nhận thủ công chỉ được gắn nhãn operator-attested, không giả danh xác nhận chính thức của Google; không yêu cầu Play Console password.
- [ ] Không đánh đồng “nằm trong email list/group”, “đã mở link”, “đã cài”, “đã opt-in” và “Google công nhận đủ 14 ngày”; khi không xác minh được hiển thị Unknown/Needs attention.
- [ ] Preflight ghi package/version thực tế, khả năng truy cập track và chẩn đoán nếu release chưa published, link chưa khả dụng, account khác, thiếu quyền hoặc có OTP/CAPTCHA; không tuyên bố kiểm chứng được mọi tình huống này chỉ từ API hiện tại; chỉ tự động hành động đã được phép.

**Verify:** API isolation, case opt-out/re-opt-in reset continuity, một tài khoản thử nghiệm được cho phép và evidence thực tế có redact. Không dùng sideload làm proof Play opt-in. [G1][G2]

### ADL-04 — Service campaign và một lane có lịch một ngày (P1, ~3–5 ngày)

**Blocked by:** ADL-01, ADL-02.  
**Outcome:** Đơn vị sản phẩm `ServiceCampaign` tham chiếu campaign runtime hiện có, app/build, plan ngày, owner và logical lane; một slot chạy đúng một lần trên máy đã chọn.

**Acceptance**
- [ ] Phân biệt service state (`draft`, `ready`, `active`, `needs_attention`, `finished`) với trạng thái execution; một service campaign có 1 app/package, timezone, start/end và quota policy riêng.
- [ ] Một lane có `tester_label` bền vững; run slot `(campaign, lane, service_day)` unique, attempt/retry tách biệt, dispatch idempotent và quan sát được.
- [ ] View có slot scheduled/executed/evaluated/blocked/missed; dịch vụ không tự ghi “Google eligible”.

**Verify:** migration + API + UI một lane/ngày, concurrent duplicate dispatch test, scheduler run history, tenant scoping.

### ADL-05 — Reservation 12 devices và thay máy không mất identity (P1, ~4–6 ngày)

**Blocked by:** ADL-04.  
**Outcome:** Admin chọn một cohort 12 máy theo khoảng ngày; một máy không thể thuộc hai service campaign giao nhau. Cho phép thay máy nhưng giữ tester/lane history.

**Acceptance**
- [ ] All-or-nothing reserve 12 eligible serials; thiếu một máy hoặc race thì rollback, không thu quota; có expiry/release và lịch sử availability.
- [ ] Workspace pool assignment, reservation dịch vụ và execution claim tồn tại theo ba contract rõ ràng; dispatcher chỉ dùng máy còn reservation + health hợp lệ.
- [ ] Replacement ghi old/new serial, reason, actor, thời gian; không ghi đè lane, run/build/evidence cũ; reset failure đưa máy vào quarantine.

**Verify:** DB concurrency/overlap/rollback tests, UI operator capacity + substitution, API readback và device hygiene trên máy pilot.

### ADL-06 — Readiness gate có lý do và quyền resume (P1, ~3–5 ngày)

**Blocked by:** ADL-03, ADL-04, ADL-05, ADL-18 (foundation allowlist/encryption; job-scoped integration nếu có customer credential); ADL-09 trước khi kích hoạt paid campaign.  
**Outcome:** Customer/operator thấy từng check: scenario approved, reservation 12 máy, track access từng account, preflight app/install, entitlement; nút Start bị khóa nếu điều kiện chưa đạt.

**Acceptance**
- [ ] Check có trạng thái, timestamp, provenance, owner và cách xử lý; “Needs attention” khác app assertion Failed; không tự suy luận Play opt-in từ run.
- [ ] Start được khóa/idempotent ở server; không có lỗ hổng qua API trực tiếp; sau human assistance re-check mới resume.
- [ ] Không mở rộng AI permission từ text/screen ngoài allowlist; secret chỉ reference theo job, không xuất log/report.

**Verify:** table-driven checks cho từng blocker, API race/permission tests, browser E2E blocked → fixed → ready.

### ADL-07 — 14 ngày × 12 lanes, quota và exception (P1, ~4–6 ngày)

**Blocked by:** ADL-06, ADL-16 (khóa job/event contract trước dispatch quy mô 12).  
**Outcome:** Từ service start tạo 168 slot dự kiến (1 run/lane/ngày); từng slot dispatch bằng scheduler hiện có, có outcome cho missed/blocked/offline và chính sách catch-up.

**Acceptance**
- [ ] Slot khóa theo ngày dịch vụ/timezone; retry một slot không làm 168 tăng lên; số scheduled, attempted, executed, evaluated, passed, failed, blocked, missed tính được từ source rows. Kịch bản ngày 1–3 core, 4–7 explore, 8–11 retest/regression, 12–14 finalize là default service policy có thể kiểm tra, không phải lịch Google.
- [ ] Mỗi attempt có deadline 15 phút theo gói nếu được chốt; timeout ra kết quả rõ ràng, không bị coi là Passed; đo device-minutes thực tế và phần retest ngoài quota riêng.
- [ ] Offline/claim fail không thành Passed; máy thay đổi không tạo lane thứ 13; quota và tài nguyên được giải phóng cuối kỳ.
- [ ] Nếu opt-in bị mất, service timeline/test runs vẫn chính xác nhưng Play participation trở thành Needs attention; không lấy 168 completed để tuyên bố Google đạt yêu cầu.

**Verify:** clock/timezone boundary, crash/replay/misfire, concurrency tests; pilot một ngày trên 12 máy trước khi hứa 14 ngày.

### ADL-08 — Dashboard ba loại tiến độ và tester detail (P1, ~3–5 ngày)

**Blocked by:** ADL-07.  
**Outcome:** Developer thấy service day/quota, testing runs và Play status riêng; mở lane thấy lịch sử device, step/attempt và evidence.

**Acceptance**
- [ ] Không gộp service progress với pass rate; số run trên dashboard đối chiếu được từ slot/execution rows, trạng thái Unknown/Blocked có next action.
- [ ] Drill-down hiện actual/expected, screenshot/video/log *nếu tồn tại*; artifact thiếu hiện “missing”, không vẽ placeholder như có evidence.
- [ ] Customer chỉ thấy tài nguyên org mình, signed URL được cấp lúc đọc; UI dùng generated client + component và EN/VI i18n hiện có.

**Verify:** API roll-up tests, permission/isolation tests và browser `flow:agent --execute` ở desktop/mobile.

### ADL-09 — One-time order/payment/entitlement (P2, ~5–7 ngày)

**Blocked by:** ADL-04; có thể phát triển song song ADL-03/05.  
**Outcome:** Một order của một campaign có giá và quota cố định; verified payment cấp đúng một entitlement; chưa trả tiền không thể start.

**Acceptance**
- [ ] Checkout tạo idempotency key; webhook được xác thực và xử lý duplicate/out-of-order không tạo hai charge/order/entitlement; customer xem được payment state.
- [ ] Nếu preflight sau payment không đạt, hiển thị lý do và chính sách xử lý/refund; không bắt đầu 14 ngày ngầm khi readiness chưa đạt.
- [ ] Payment credential không ở browser/farm job/log; tenant billing read được scope đúng quyền.

**Verify:** provider sandbox webhook E2E, duplicate/delayed/refund scenarios và browser order journey. Với pilot trước tích hợp provider, chỉ dùng entitlement được admin xác nhận rõ, không mô tả là thanh toán thật.

### ADL-10 — Build mới, issue và retest giữ nguyên lịch sử (P2, ~4–6 ngày)

**Blocked by:** ADL-07, ADL-08.  
**Outcome:** Developer ghi build/version mới, chọn issue để retest, nhận attempt mới trên slot/lane phù hợp và so sánh trước/sau.

**Acceptance**
- [ ] Build immutable reference + package/version + install evidence; không sửa kết quả cũ; issue có severity, expected/actual, reproduction steps, device/build và artifact refs.
- [ ] Retest link issue → source attempt → retest attempt; `fixed/still failing/inconclusive` dựa trên assertion, blocked không bị diễn dịch thành fixed.
- [ ] Không tiêu quota retest một cách ngầm định; hiển thị quota/cost chính sách trước khi chạy.

**Verify:** backend lineage tests, reopen old artifact, browser issue→retest→compare.

### ADL-11 — Report/PDF có provenance và missing-evidence accounting (P2, ~3–5 ngày)

**Blocked by:** ADL-08, ADL-10.  
**Outcome:** Report cuối kỳ là snapshot của trạng thái nguồn: 168 scheduled, bao nhiêu executed/evaluated/pass/fail/blocked/missed, issue/retest, participation riêng và giới hạn kiểm thử.

**Acceptance**
- [ ] Report manifest có version, created-at, builder identity, snapshot query cutoff, run/attempt/build/device refs và counts đối chiếu được; export PDF giữ nguyên counts.
- [ ] Nếu evidence bị thiếu/hết hạn/xóa hoặc participation Unknown, hiển thị rõ; không ghi Google approval/eligibility dựa trên AI test.
- [ ] Report và media private, scoped theo org, redacted secrets, download link ngắn hạn; chính sách giữ artifact ít nhất đủ vòng đời báo cáo + thời gian truy cập đã cam kết.

**Verify:** fixture với retry, offline, replacement, missing artifact, duplicate webhook; API/report count reconciliation, PDF visual QA và cross-tenant download rejection.

### ADL-12 — Cancel/expire/quarantine và pilot 14 ngày (P2, ~14 ngày vận hành)

**Blocked by:** ADL-01 đến ADL-11, ADL-13 đến ADL-19 và capacity/account readiness thực tế; ADL-20a prototype là input trước pilot, còn ADL-20c acceptance pack chỉ hoàn tất sau pilot.  
**Outcome:** Một pilot end-to-end được vận hành đủ chu kỳ với log xử lý lỗi, device cleanup và kết luận có bằng chứng.

**Acceptance**
- [ ] Cancel/expire dừng slot mới, drain run cũ, release reservation, reset máy trước campaign sau; reset lỗi thành quarantine; audit mọi thay máy/refund/extension.
- [ ] 14 ngày có đối chiếu từng ngày: Play account participation evidence theo nguồn và run/evidence theo lane; opt-out/blocked/missing-day không bị sửa thành pass.
- [ ] Report nêu riêng chất lượng app, việc hoàn tất dịch vụ và tình trạng Play theo bằng chứng có được; xác định tỷ lệ onboarding tự phục vụ và ≥95% **run hoàn tất** có step log + result (định nghĩa mẫu số trước pilot).

**Verify:** live devices + persisted DB + customer browser journey + operator audit; chỉ kết luận “pilot đạt” khi đầy đủ source/API/browser/live evidence. Production access vẫn là quyết định của Google. Task này thực thi **pilot trước**; ADL-20 acceptance pack đọc kết quả pilot sau để quyết định launch.

### ADL-13 — Landing + một CTA đi tới draft campaign (P1, ~2–3 ngày)

**Blocked by:** ADL-02 cho landing→draft; ADL-09 cho CTA đi hết bước Payment thực.  
**Outcome:** Người dùng từ landing hiểu giá trị, phạm vi 12 máy/14 ngày và nhấn Start campaign để tạo draft của mình; đang đăng nhập thì tới wizard, chưa đăng nhập thì qua sign-in rồi trở lại draft.

**Acceptance**
- [ ] Landing nêu thiết bị thật, AI scenario, report có evidence và giới hạn về opt-in/Google approval; không khiến “12 AI testers” bị hiểu nhầm thành 12 human testers đã opt-in. Kiểm tra thông điệp/CTA với developer mục tiêu trước khi chọn copy cuối.
- [ ] CTA hoạt động trên mobile/desktop, hỗ trợ EN/VI, trạng thái auth/empty/error rõ ràng; một user bắt đầu hai lần không tạo hai order ngoài ý muốn.
- [ ] Funnel event có `landing_view → start_click → app_submitted → scenario_approved → payment_completed → readiness_started`, tenant-aware, không chứa PII/secret; định nghĩa mẫu số ≥80% onboarding tự phục vụ ở ADL-20.

**Verify:** product copy review với chính deck trang 1/5/6/12, thử nghiệm CTA với developer thực, browser E2E từ landing đến draft và quay lại qua auth; analytics event contract test.

### ADL-14 — Wizard App → Scenario → Review → Payment đi hết hành trình (P2, ~3–5 ngày)

**Blocked by:** ADL-02, ADL-09, ADL-13.  
**Outcome:** Developer đi bốn bước đúng slide 7: nhập app/link/goal, xem scenario, xác nhận gói, trả tiền một lần và tới readiness. Các dữ liệu draft/approved/ordered cùng một service campaign.

**Acceptance**
- [ ] Không mất draft khi refresh/back; package/link được validate và mô tả giới hạn verification; review hiển thị 12 devices/14 days/168 scheduled slots, giá, giới hạn retest, xử lý nếu readiness fail sau payment.
- [ ] Không thanh toán khi scenario chưa approved; submit lặp/back/refresh không tạo order/campaign trùng; payment state đến từ server/webhook chứ không từ redirect của browser.
- [ ] Sau payment, người dùng tới checklist readiness và thấy blockers của mình; cross-tenant không thể đọc/sửa wizard/order của workspace khác.

**Verify:** end-to-end sandbox browser `App → Scenario → Review → Payment → Readiness`, API repeat-submit/cross-tenant tests, EN/VI và accessibility form states.

### ADL-15 — Truy cập đúng vai trò và audit thao tác dịch vụ (P2, ~3–4 ngày)

**Blocked by:** ADL-04, ADL-09.  
**Outcome:** Owner/developer quản lý app, order, quota, report; admin vận hành quản lý fleet và blocked mà không thấy bí mật khách hàng; mọi quyết định nhạy cảm có audit.

**Acceptance**
- [ ] Có ma trận quyền cụ thể create/approve/start/retry/export/cancel/replace/extend/refund; một owner trong MVP nhưng không giả định superadmin và customer cùng quyền.
- [ ] Backend kiểm quyền ở từng mutation/read, kể cả export URL sau khi report được tạo; cross-tenant resource ID phải từ chối, admin audit lưu actor/action/time/reason.
- [ ] UI chỉ hiển thị hành động phù hợp và lời giải thích khi bị khóa; không dùng ẩn nút làm ranh giới bảo mật.

**Verify:** permission matrix tests cho owner/customer/operator/ngoài org, signed artifact/export rejection, browser E2E hai role.

### ADL-16 — Farm Adapter: job/event contract và correlation (P1, ~3–5 ngày)

**Blocked by:** ADL-01, ADL-04. Chỉ cho chạy customer job sau khi foundation ADL-18 đã kiểm chứng (allowlist và encryption gate); phần job-scoped integration ADL-18 triển khai sau contract ADL-16.  
**Outcome:** Service backend gửi job tới Device Farm qua interface tái dùng campaign dispatcher, nhận event theo một identity chain để trace chính xác slot → attempt → execution → step → artifact.

**Acceptance**
- [ ] Job có org, service campaign, lane, slot, attempt, device, account reference, app/build, scenario version, timeout, allowed operations và idempotency key; không gửi credential/farm token vào browser.
- [ ] Event có source timestamp, correlation IDs, step index/path, outcome có provenance; duplicate/out-of-order event không biến offline/blocked thành Passed, terminal/replay không dispatch thêm lần ngoài ý muốn.
- [ ] Temporal và fallback trả cùng ý nghĩa outcome; contract support timeout, cancellation, release runtime claim, replay và operator inspect của một job.

**Verify:** adapter contract tests, fake relay/failure modes, API to persisted execution/event/artifact correlation; một run thiết bị thật đã được ADL-01 chứng minh.

### ADL-17 — Chứng cứ screenshot/video/log và retention có trạng thái rõ (P2, ~3–5 ngày)

**Blocked by:** ADL-01, ADL-16.  
**Outcome:** Một attempt có manifest các evidence thực sự tạo được; screenshot/step log tối thiểu, video nếu có khả năng record/export được xác minh, không coi live stream là MP4.

**Acceptance**
- [ ] Ghi expected/observed, screenshot object key, step log/hierarchy tùy capture policy, media type, capture timestamp, checksum và error khi capture fail; video/log có `available/unsupported/missing/expired` riêng.
- [ ] Evidence của retry/build cũ giữ nguyên; không tải bytes lớn vào Temporal payload; retention policy phù hợp hợp đồng report, re-sign/proxy khi đọc và biểu thị 410 khi object đã xóa.
- [ ] Nếu quyết định MVP yêu cầu video, thử ghi MP4 an toàn trên một máy, so khớp thời gian/attempt và phát lại từ private storage; nếu không đạt, điều chỉnh UI/contract để báo “video chưa có”, không mock bằng live preview.

**Verify:** storage failure/TTL tests, capture xuyên hai attempt, browser reopen sau TTL, live proof loại evidence theo manifest.

### ADL-18 — Customer secrets và tool permission fail-closed (P1, ~3–5 ngày)

**Blocked by:** ADL-02 cho foundation allowlist/credential intake; ADL-16 cho phần integration. Có thể làm foundation song song ADL-04; foundation phải hoàn tất trước customer job từ ADL-16, sau đó gắn secret reference vào contract.  
**Outcome:** Credential app kiểm thử (nếu cần) được quản lý qua reference cấp cho job được phép, không lộ ở scenario, logs, media/report, frontend token hoặc tool arguments trả về.

**Acceptance**
- [ ] Chốt môi trường chỉ test/non-production, test account và quyền được phép; storage mã hóa ở deployment thực, encryption key thiếu thì reject onboarding credential thay vì rơi về chế độ lưu thô (`backend/common/crypto.py` hiện có dev fallback).
- [ ] Job chỉ nhận secret reference/ephemeral capability; khi cần resolve, scope theo org + campaign + lane + TTL, audit mà không ghi plaintext; scrub request, response, step log, screenshot/report khi có PII.
- [ ] AI tool executor chỉ nhận allowlist server-side; thử prompt injection trên màn hình app, purchase/ads/production mutation/OTP bypass đều phải dừng có reason, không được tự mở quyền từ UI.

**Verify:** secret leakage tests qua API, DB, events, exception, artifact, cross-tenant reference; policy-denial scenario và manual review những ảnh có input nhạy cảm.

### ADL-19 — Farm hygiene, device health, quarantine, replacement/extension (P0/P3, ~3–5 ngày build + proof)

**Blocked by:** Không với P0 reset/quarantine một máy; ADL-05 và ADL-07 cho operator view, replacement/extension đầy đủ.  
**Outcome:** Admin thấy health của 12 máy, xử lý blocked/offline, thay máy hoặc gia hạn có audit, và đảm bảo máy được reset trước khi đưa sang campaign khác.

**Acceptance**
- [ ] Trước khi reuse: reset/clear app-account data theo runbook, xác nhận hoàn tất có thời điểm/serial/actor; reset lỗi hoặc health fail làm quarantine, không chọn lại được.
- [ ] Replacement giữ nguyên lane và history, machine/account track participation là các state riêng; nếu đổi account thì continuity phải đánh giá lại, không tự cộng dồn 14 ngày.
- [ ] Extension có consent, order/entitlement/quota delta rõ, không sửa mốc kết thúc của report cũ; cancel/expiry giải phóng lease đúng sau drain.

**Verify:** fault injection reset fail/offline, operator UI demo blocked → replace → health ready và lease release; physical reset chỉ trên thiết bị được phép.

### ADL-20 — UX prototype, KPI instrumentation và pilot acceptance pack (P1/P5, ~3–5 ngày thiết kế + pilot thật)

**Blocked by:** Không với prototype mock-state; KPI instrumentation cần ADL-07/ADL-13/ADL-14, còn launch acceptance pack chờ ADL-12 và các task P2/P3/P4 liên quan. Prototype phải hoàn thành trước các task sản phẩm đó.  
**Outcome:** Trước build hàng loạt, kiểm tra prototype landing/wizard/dashboard/detail/report với developer và operator; sau đó theo dõi các KPI và toàn bộ acceptance của slide 4/18 qua pilot.

**Acceptance**
- [ ] Prototype nối được 5 màn trong deck, với loading/empty/error/blocked/recovery, focus/mobile và EN/VI; người dùng lần đầu chỉ ra được giá trị, việc cần làm tiếp và giới hạn về Google. Review bằng người dùng thật + product reviewer, không lấy mockup làm sản phẩm đã chạy.
- [ ] Định nghĩa KPI trước pilot: `self_serve_onboarding = số campaign đạt readiness không cần operator hoàn tất hộ / số campaign đủ input và đã thanh toán`; `run_with_trace = số execution terminal có ít nhất một step log và outcome / số execution terminal`. Dashboard hiển thị numerator/denominator, cohort và window; xét mục tiêu ≥80% và ≥95% của slide 4.
- [ ] Acceptance pack có case không double booking/billing duplication, offline≠Passed, OTP Blocked→resume, build/evidence immutable, tenant isolation/signed URL, 336h≠Google approved; evidence API/browser/live/DB cho `submit → readiness → run → evidence → report`.

**Verify:** UX prototype với ghi nhận task completion, review case matrix chạy trên pilot 14 ngày, report sai biệt và go/no-go có người chịu trách nhiệm. Synthetic review `repoos_artifacts:52cb95ef-c43b-4fe7-8e75-7e829b89d2b9` báo trust/CTA cần thử thực tế; đây chỉ là tín hiệu review, không phải kết quả user test.

## 5. Ma trận bao phủ từng slide

Số trang là **số trang PDF (1–19)**, khác nhãn mục 01–17 trong deck. `ADL-xx` là nơi yêu cầu được hiện thực hoặc kiểm chứng, không phải thứ tự bắt buộc của UI.

| Trang | Mục tiêu trong slide | Task nhận trách nhiệm |
|---|---|---|
| 1 | Tuyên bố 12 AI testers/14 ngày, một hành trình rõ | ADL-13, ADL-14, ADL-20 |
| 2 | 12 opt-in, 14 ngày và bằng chứng/engagement | ADL-03, ADL-06, ADL-07, ADL-08, ADL-11 |
| 3 | Submit → AI scenario → 12 máy → report; minh bạch Play | ADL-02, ADL-03, ADL-05, ADL-16, ADL-11 |
| 4 | Developer/owner/admin, onboarding ≥80%, trace ≥95% | ADL-14, ADL-15, ADL-19, ADL-20 |
| 5 | Android/1 app/12 máy/14 ngày/168 run/one-time payment; out of scope | ADL-04, ADL-05, ADL-07, ADL-09; quyết định §3 |
| 6 | Landing, giá trị 5 giây, CTA | ADL-13, ADL-20 |
| 7 | Wizard App/Scenario/Review/Payment và form app | ADL-02, ADL-09, ADL-14 |
| 8 | Payment+scenario+12 máy+track/install preflight; Blocked≠Failed | ADL-03, ADL-05, ADL-06, ADL-09, ADL-18 |
| 9 | Dashboard 12 lanes, 14 ngày, trạng thái máy | ADL-07, ADL-08, ADL-19 |
| 10 | Tester detail, step, screenshot/video/log/assertion, retry và OTP | ADL-06, ADL-08, ADL-10, ADL-17, ADL-18 |
| 11 | Core/explore/retest/finalize; 168 slot, ≤2.520 phút theo giả định | ADL-07, ADL-10, ADL-11 |
| 12 | Ba loại tiến độ độc lập, không claim Google/pass sai | ADL-03, ADL-08, ADL-11, ADL-13 |
| 13 | Report scheduled/executed/evaluated/pass/fail, issues, retest, export | ADL-10, ADL-11, ADL-17 |
| 14 | Frontend/backend/farm adapter/report worker/DB/private storage | ADL-04, ADL-09, ADL-11, ADL-16, ADL-17, ADL-18 |
| 15 | Assignment→Run→Attempt→StepResult→Artifact; track separate | ADL-03, ADL-04, ADL-05, ADL-07, ADL-16, ADL-17 |
| 16 | Cấm purchase/ads/data mutation/OTP bypass; secrets và reset | ADL-02, ADL-18, ADL-19 |
| 17 | P0–P5, real-run gate và pilot | ADL-01, ADL-20; phase gates §6 |
| 18 | Launch acceptance và 14-day journey | ADL-05, ADL-06, ADL-09, ADL-10, ADL-11, ADL-12, ADL-15, ADL-20 |
| 19 | P0 track access/install/tools/evidence/reset | ADL-01, ADL-03, ADL-17, ADL-19 |

### Bản cắt issue độc lập trước khi giao implement

Các ADL ở trên mô tả outcome, nhưng một vài outcome có hai mốc. Khi đưa vào tracker, tách các mốc sau để **mỗi issue chỉ có một definition of done**: `ADL-03a` P0 operator track/install và `03b` self-service participation; `ADL-13a` landing→draft và `13b` landing→paid; `ADL-18a` fail-closed allowlist/encryption và `18b` job-scoped secret integration; `ADL-19a` one-device reset/quarantine proof và `19b` fleet replacement/extension; `ADL-20a` UX prototype, `20b` KPI counters, `20c` pilot acceptance pack. Các mã `03a/b` v.v. là subdivision lúc tạo issue, vẫn trace được về ADL gốc. Không đóng ADL gốc nếu một milestone chưa đạt.

## 6. Thứ tự triển khai và release gates

```text
P0  ADL-01 real run → ADL-03 single-account track/install proof → ADL-19 reset/quarantine proof
P1  ADL-20 UX prototype → ADL-02 intake/scenario approval → ADL-13 landing
P2  ADL-04 service campaign → ADL-09 order/payment → ADL-14 complete wizard
P3  ADL-05 reservations + ADL-16 adapter + ADL-18 secrets → ADL-06 gate
    → ADL-07 schedule → ADL-08 dashboard + ADL-15 access/roles + ADL-19 operations
P4  ADL-17 evidence completeness + ADL-10 issues/retest → ADL-11 export/report
P5  ADL-12 14-day pilot + ADL-20 KPI/acceptance pack
```

**Lưu ý về phụ thuộc:** Bảng trên thể hiện deliverables theo phase của deck, **không** override `Blocked by` trong từng task: ADL-19 P0 chỉ chứng minh reset trên một máy, operator UI/replacement thuộc P3; ADL-20 prototype ở P1 và KPI/acceptance ở P5. Để P0 không phụ thuộc wizard P1, ADL-03a có intake tối thiểu do operator thực hiện sau ADL-01; khi user dùng self-service thì nối ADL-03b sau ADL-02. ADL-02 trong P1 dùng safe scenario được ADL-01 chứng minh. ADL-18a phải có trước ADL-16 customer execution; ADL-18b gắn secret reference sau khi ADL-16 chốt contract, ADL-06 chỉ mở Start với credentials khi ADL-18b đạt. P2/P3 có thể phát triển song song sau ADL-04, nhưng **paid service không start trước ADL-09**. Nếu giữ chuỗi phase P0→P1 nghiêm ngặt thì P0 sử dụng scenario/operator nhập tay đã có để chứng minh ADL-01 trước khi xây self-service.

**Đường găng theo issue nhỏ:** `01 → 03a → 19a` (P0); `20a → 02 → 04 → 09 → 14` (customer flow); `04 → 05`, `02 → 18a`, `04 + 18a → 16 → 18b`, `03a/03b + 05 + 09 + 18b → 06 → 07 → 08 → 10 → 11 → 12 → 20c`. `13a` sau `02`, `13b` sau `09`, `15/17/19b/20b` tham gia gate tương ứng theo acceptance. Không đánh dấu ADL-16 hoàn tất ở môi trường khách hàng chỉ vì contract đã viết; phải có secret integration và an toàn dispatch được chứng minh.

**Gate P0:** ADL-01/03 có track access + install/update + tool execution + screenshot/step evidence trên một thiết bị thực, reset/quarantine thử được trên một thiết bị. **Gate P1:** prototype người dùng đi landing → draft → review và hiểu ba progress. **Gate P2:** một order trả thành công duy nhất, failed readiness không start đồng hồ. **Gate P3:** một ngày 12 máy, không double booking, block/recovery, 12 slot có correlation. **Gate P4:** số report đối chiếu toàn bộ persisted rows, retest/build cũ còn nguyên. **Gate P5:** 14 ngày pilot và các case acceptance trang 18 được chứng minh. Các ước lượng task không cộng cơ học thành roadmap 23–34 ngày vì phụ thuộc thiết bị, tài khoản, Play release và provider thanh toán chưa xác minh.

## 7. Nguồn và cách đọc bằng chứng

- **[PRD]** [`AI_Device_Lab_Product_Presentation_Final.pdf`](./AI_Device_Lab_Product_Presentation_Final.pdf), đặc biệt trang 2–3 (claim), 7–8 (intake/readiness), 11–12 (plan/progress), 13–18 (report, data, safety, acceptance).
- **[G1]** Google Play Console Help, [App testing requirements for new personal developer accounts](https://support.google.com/googleplay/android-developer/answer/14151465), đọc lại 02/10/2026: điều kiện áp dụng, 12 opt-in/14 ngày liên tục, hồ sơ xin production và đánh giá engagement/feedback.
- **[G2]** Google Play Console Help, [Set up an open, closed, or internal test](https://support.google.com/googleplay/android-developer/answer/9845334), đọc lại 02/10/2026: danh sách/group, tester opt-in, published link, thời gian khả dụng và version/track behavior.
- **[S1]** Source checkout `backend/services/execution/epic06_capture_adapter.py`, `backend/services/execution/step_runner.py`, `backend/services/execution/capture_service.py`, `backend/api/routes/executions.py`, xem 02/10/2026; mức chứng cứ là **source only**.
- **[RB]** RepoOS repo-brain read-only: `repoos_artifacts:d03ec384-040b-472e-b85f-6be1fa31d3a1` và `repoos_artifacts:835774ac-00e0-441d-88f1-f6db1fed4e76`. Lần gọi thứ hai không nhìn thấy untracked `backend/`, nên chỉ dùng làm checklist rủi ro, không dùng xác thực layout hiện tại hay live behavior.

**Quy tắc khi bắt đầu implement:** check `git status` vì worktree đang chuyển `device_farm/` → `backend/`; trước khi sửa symbol phải chạy GitNexus `impact`, trước khi sửa API route chạy `api_impact`, trước commit chạy `detect_changes`. Với API thay đổi hãy sync OpenAPI và generated client, với UI chạy browser acceptance; mọi phone action phải có serial + scope được cho phép.
