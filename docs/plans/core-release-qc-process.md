# Core Release QC Process

Status: active
Last audited: 2026-05-25

Tài liệu này chốt quy trình QC phát hành cho **core release** của Device Farm.
Mục tiêu là giảm rủi ro user-facing theo thứ tự: đúng phạm vi tổ chức, điều khiển
thiết bị ổn định, chạy scenario bền vững, lưu content có truy vết, và dashboard
không đứt luồng vận hành.

## Scope

In-scope:

- `DF-MOD-01` Nền tảng & Bảo mật truy cập
- `DF-MOD-02` Thiết bị & Mặt phẳng điều khiển
- `DF-MOD-03` Agent Boot & Relay
- `DF-MOD-04` Campaign, Scenario & Execution
- `DF-MOD-05` Scheduling
- `DF-MOD-06` Content Extraction & Artifact
- `DF-MOD-07` Accounts & Account Groups
- `DF-MOD-08` chỉ cho **Facebook L2 Active**
- `DF-MOD-09` Notifications & Analytics
- `DF-MOD-11` Frontend & Dashboard

Out-of-scope:

- TikTok / Threads / Instagram ở mức L2
- Toàn bộ MCP / L3 preview
- `DF-MOD-10`
- Hardening roadmap chưa phải core gate: SSO, TLS gRPC relay, webhook retry riêng,
  offline mode, alert engine, export CSV/JSON đang refactor

## Rủi ro trọng yếu

| ID | Rủi ro | Bằng chứng trong docs | Kiểm chứng bắt buộc |
|---|---|---|---|
| R1 | Lộ dữ liệu cross-tenant hoặc sai auth boundary | MOD-01, MOD-07, MOD-11 yêu cầu ownership theo organization | Test âm cho JWT sai org, route admin, query account/content/campaign trái org |
| R2 | Mất độc quyền session hoặc relay flapping làm fail hàng loạt | MOD-02, MOD-03 nêu reserve exclusivity, heartbeat/reconnect, ưu tiên USB | Test reserve conflict, agent reconnect, device BUSY không nhận lệnh từ session khác |
| R3 | Execution core surface không đồng nhất hoặc fallback làm mất trạng thái | MOD-04, MOD-05 nêu risk ở preview/campaign/fallback và Temporal off | Test 1 flow chuẩn, 1 flow fail vào DLQ, 1 flow fallback có marker rõ |
| R4 | Content lưu thiếu traceability hoặc sai content type Facebook | MOD-06, MOD-08 yêu cầu `fb_post`/`fb_comment`, `parent_id`, `item_level` | Test save_extraction và query content/artifact từ execution |
| R5 | Legacy account fallback gây chạy sai account | MOD-07 ghi rõ đây không phải target contract | Test scenario có account intent và scenario thiếu account phải fail rõ, không auto-infer |
| R6 | Frontend drift với backend ở notifications / analytics / relay | MOD-01, MOD-09, MOD-11 đều cảnh báo parity gap | Smoke dashboard đúng route chính, unread count, relay page, activity history |

## Test Levels

| Level | Mục tiêu | Scope tối thiểu |
|---|---|---|
| L0 - Readiness | Xác nhận build phát hành đúng phạm vi core | OpenAPI/client sync, migration áp dụng, env bắt buộc, feature flag/out-of-scope claim |
| L1 - Module gate | Chặn lỗi contract ở từng module | Chạy checklist gate theo bảng module bên dưới |
| L2 - Integration | Chặn lỗi tại điểm nối module | Auth -> Frontend, Relay -> Device control, Campaign -> Content, Schedule -> Notification |
| L3 - E2E/UAT | Xác nhận luồng người dùng thật | 4 flow E2E/UAT bắt buộc |
| L4 - Release smoke | Quyết định go/no-go sau deploy | 10-15 phút, chỉ kiểm chứng đường sống còn |

## Module Acceptance Gates

| Module | Gate phải pass | Blocker nếu fail |
|---|---|---|
| `DF-MOD-01` | Login, refresh, JWT boundary, admin boundary, safe-mode status, WebSocket auth | Có route sai boundary, cross-tenant, login/refresh lỗi |
| `DF-MOD-02` | Pair/list device, reserve/release, gesture, hierarchy, screenshot, stream cơ bản | 1 device bị double-reserve, gesture/hierarchy/screenshot lỗi |
| `DF-MOD-03` | Agent lên online, heartbeat cập nhật, attach/detach phản ánh đúng, reconnect phục hồi | Agent mất kết nối không tự phục hồi hoặc toàn host offline kéo dài |
| `DF-MOD-04` | Scenario step tuần tự, graph branch, retry/error policy core, pause/resume/cancel, DLQ | Execution mất checkpoint, fail không vào DLQ, step stop-on-failure sai |
| `DF-MOD-05` | Create/update/toggle schedule, run-now, history, link execution, fallback marker | Tick không tạo run, run không link execution, toggle/run-now sai |
| `DF-MOD-06` | Hierarchy/OCR/AI extract core path, `save_extraction`, artifact, query content | Content lưu thiếu traceability, artifact không mở được |
| `DF-MOD-07` | CRUD/import account, account_group, round-robin, account resolve theo intent | Scenario chạy bằng account ngầm, cross-tenant account access |
| `DF-MOD-08` | Chỉ Facebook L2: `fb_posts`, `fb_comments`, `fb_post`, `fb_comment`, comment context step | Claim L2 cho platform khác hoặc Facebook content type/parent-child sai |
| `DF-MOD-09` | In-app notification, unread count, mark-read, webhook 1 lần, activity log, deep link | Event core không sinh notification/activity hoặc link hỏng |
| `DF-MOD-11` | Devices, relay-agents, campaigns, scenario-flow, accounts, content, schedules, notifications, activity-history | Dashboard đứt luồng core hoặc route chính 404/500 |

## E2E/UAT Bắt Buộc

### UAT-01: Fleet control căn bản

1. Đăng nhập bằng user của đúng organization.
2. Mở `devices` và `relay-agents`, thấy agent online và device online.
3. Reserve 1 device, mở live view, chụp screenshot, đọc hierarchy, release.

Pass:

- Không thấy dữ liệu organization khác.
- Session owner hiển thị đúng.
- Stream/hierarchy/screenshot phản hồi trong ngưỡng vận hành chấp nhận được.

### UAT-02: Facebook L2 crawl post/comment

1. Chọn scenario Facebook trong scope core.
2. Gán account intent tường minh hoặc account group hợp lệ.
3. Dispatch vào 1 device.
4. Step mở comment context, extract `fb_posts` hoặc `fb_comments`, `save_extraction`.
5. Mở content detail và artifact từ execution.

Pass:

- Content lưu với `fb_post` hoặc `fb_comment`.
- `fb_comment` có `parent_id` và `item_level`.
- Traceability đủ tới campaign, scenario, execution, device, collection, account nếu có intent.

### UAT-03: Failure path có evidence

1. Chạy scenario có chủ đích fail ở một step UI-gated.
2. Quan sát execution dừng đúng step.
3. Xác nhận artifact pre/post step, screenshot fail, hierarchy fail.
4. Xác nhận entry xuất hiện ở DLQ.
5. Thử retry hoặc close theo đúng policy.

Pass:

- Mặc định stop-on-failure.
- Không tự skip hay tự chọn account thay thế.
- Người vận hành debug được mà không cần vào DB.

### UAT-04: Schedule -> execution -> notification

1. Tạo schedule cho campaign Facebook core.
2. Chạy `run-now`, sau đó kiểm tra lịch sử run.
3. Kiểm tra execution con, notification panel, unread count, activity log.
4. Nếu có thể trong staging, tắt Temporal theo cách an toàn và xác nhận fallback marker hoặc banner.

Pass:

- Schedule run sinh execution thật.
- Notification và activity log có deep link đúng.
- Fallback, nếu dùng, phải được đánh dấu rõ; không được giả như durable mode.

## Smoke Checklist Sau Deploy

- `health`, login, refresh token hoạt động.
- Dashboard vào được các trang: devices, relay-agents, campaigns, content, schedules.
- Thấy ít nhất 1 relay online và 1 device online.
- Reserve/release 1 device thành công.
- Gesture đơn giản + screenshot + hierarchy thành công.
- Dispatch 1 scenario Facebook core trên 1 device thành công.
- Lưu được 1 content item Facebook đúng content type.
- Mở được artifact từ execution.
- Run-now 1 schedule thành công.
- Notification panel tăng unread count và mở đúng deep link.
- Activity history có event mới của release smoke.

## Regression Checklist

- Auth boundary: public, user-auth, admin-auth, device-auth.
- Multi-tenancy: accounts, campaigns, content, schedules, notifications không lộ chéo org.
- Session exclusivity: thiết bị BUSY không nhận lệnh từ session khác.
- Relay stability: attach/detach, reconnect sau mất mạng ngắn, USB ưu tiên hơn WiFi nếu có.
- Scenario semantics: step order, branch, retry, pause/resume/cancel, checkpoint, DLQ.
- Scheduling semantics: toggle on/off, run-now, history, link execution, fallback marker.
- Content semantics: content_type qualified, `raw_data`, `parent_id`, `item_level`, artifact retrieval.
- Account semantics: round-robin chỉ dùng account hợp lệ, thiếu account intent fail rõ.
- Notification semantics: unread count, mark-read/all-read, webhook result record, activity log bất biến.
- Frontend parity: notifications, analytics, relay pages không vỡ do generated client drift.

## Go / No-Go

Go khi:

- Toàn bộ UAT-01 tới UAT-04 pass.
- Không có P0/P1 ở `R1` tới `R6`.
- Không có lỗi cross-tenant, double-reserve, mất traceability content, hoặc deep link sai tài nguyên.
- Dashboard core route không có 404/500.
- Không có claim phát hành vượt scope: chỉ Facebook L2 Active, không tuyên bố TikTok/Threads/Instagram L2 hay MCP.

No-Go khi:

- Login/refresh/JWT boundary hỏng.
- Thiết bị bị double-reserve hoặc relay host không ổn định.
- Campaign core không dispatch hoặc fail không có DLQ/evidence.
- Content Facebook lưu sai `content_type` hoặc thiếu traceability.
- Schedule tạo run nhưng không ra execution/notification.
- Notification/activity-history route core bị vỡ do parity gap.

## Rollback Verification

Điều kiện trước rollback:

- Có release id, DB snapshot/migration plan, danh sách env thay đổi, và danh sách feature flag liên quan.

Sau rollback phải xác nhận tối thiểu:

1. Login và dashboard vào lại bình thường.
2. 1 relay online và 1 device reserve/release bình thường.
3. 1 scenario Facebook core chạy lại được trên môi trường đã rollback.
4. Content mới vẫn lưu và truy vết được tới execution mới sau rollback.
5. 1 schedule `run-now` tạo execution và notification mới.
6. Không còn bản ghi hoặc route UI mang schema nửa cũ nửa mới.

Rollback chỉ coi là hoàn tất khi:

- Luồng chuẩn sau rollback pass: login -> reserve -> dispatch Facebook -> content -> notification.
- Luồng lỗi sau rollback pass: step fail vẫn vào DLQ và mở được artifact.
- Điểm nối chính sau rollback pass: schedule -> execution -> notification deep link.

## Handoff QA

- P0: chạy đầy đủ UAT-01 tới UAT-04 trên build candidate trước khi mở production.
- P1: nếu có fallback mode, phải test riêng và gắn nhãn best-effort, không coi tương đương Temporal durable path.
- P1: nếu dùng Next API proxy cho notifications / analytics / relay, phải audit đúng schema release hiện tại.
- P2: ghi rõ trong release note các phần out-of-scope để tránh oversell platform coverage.
