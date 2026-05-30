# Bảng thuật ngữ (Glossary)

> **Mã tài liệu:** DF-DOC-00-GLOSSARY
> **Phiên bản:** 1.0
> **Cập nhật lần cuối:** 2026-05-25
> **Trạng thái:** Approved
> **Đối tượng đọc:** Team Device Farm

Bảng thuật ngữ này tập hợp toàn bộ từ ngữ tiếng Anh chuẩn ngành xuất hiện trong bộ tài liệu Device Farm và mô tả ngắn ý nghĩa nghiệp vụ của chúng. Các thuật ngữ thuần kỹ thuật triển khai (ví dụ tên thư viện, framework) chỉ được đưa vào khi việc đọc các tài liệu phía sau yêu cầu hiểu chúng ở mức cơ bản.

Quy ước trình bày: cột **Thuật ngữ (EN)** là dạng tiếng Anh canonical, **Định nghĩa nghiệp vụ** là mô tả ngắn bằng tiếng Việt, **Ghi chú** liệt kê tài liệu nơi thuật ngữ xuất hiện chủ yếu hoặc các bí danh hợp lệ.

## A — Khái niệm tổng quan và nền tảng

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Device Farm** | Tên sản phẩm — nền tảng tự động hóa và thu thập dữ liệu social media trên fleet thiết bị Android thật, hỗ trợ ba chế độ vận hành: tự động, thủ công có giám sát, và AI-agent. | Toàn bộ bộ tài liệu |
| **Fleet** | Cụm thiết bị Android được Device Farm quản lý, theo dõi trạng thái, dispatch lệnh và thu artifact. | `02-devices-and-control-plane.md` |
| **Operator / Người vận hành** | Người trực tiếp tương tác với Device Farm để cấu hình, dispatch, giám sát và xử lý sự cố. Bao gồm Social Data Operator, Automation Builder, AI Operations Supervisor, Fleet Operator. | `02-personas-and-journeys.md` |
| **Organization** | Đơn vị multi-tenancy — một tổ chức khách hàng có nhiều thành viên, các thành viên dùng chung tài nguyên (devices, campaigns, content, accounts) trong phạm vi tổ chức. | `modules/01-platform-runtime-and-access.md` |
| **L1 / L2 / L3** | Ba cấp coverage năng lực Device Farm áp dụng cho mỗi platform social. L1 — kiểm soát phiên thiết bị độc lập; L2 — tự động hóa kịch bản; L3 — công cụ AI agent qua MCP. | `03-capability-matrix.md` |
| **Authored scenario flow** | Luồng kịch bản đã được người dựng cấu hình một cách tường minh — Device Farm thực thi chính xác theo cấu hình, không tự suy diễn nhánh phục hồi hay tự chọn account. | `modules/04-campaigns-scenarios-executions.md` |

## B — Tự động hóa và kịch bản

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Campaign** | Đơn vị công việc cấp cao — chứa một hoặc nhiều scenario, hướng đến một tập device hoặc device group, có vòng đời dispatch và execution. | `modules/04-campaigns-scenarios-executions.md` |
| **Scenario** | Định nghĩa workflow tự động hóa: chuỗi step có thứ tự, có thể biểu diễn dạng đồ thị (graph) với nhánh điều kiện, vòng lặp, và scenario lồng. | `modules/04-campaigns-scenarios-executions.md` |
| **Scenario version** | Phiên bản cụ thể của một scenario được lưu vào hệ thống. Một scenario có thể có nhiều version theo thời gian. | `modules/04-campaigns-scenarios-executions.md` |
| **Step** | Đơn vị thực thi nhỏ nhất trong scenario, ví dụ: tap, swipe, extract, branch, wait, set_variable. | `modules/04-campaigns-scenarios-executions.md` |
| **Step family** | Nhóm step theo loại: Navigation, Interaction, Input/Wait, Verification, Variables/Control flow, Composition, Extraction/Content, Platform-specific. | `modules/04-campaigns-scenarios-executions.md` |
| **UI-gated** | Đặc tính của step — chỉ thành công khi UI thiết bị đang ở trạng thái mong đợi. Mặc định mọi step social đều UI-gated; nếu state không khớp, scenario dừng trừ khi có nhánh phục hồi. | `modules/04-campaigns-scenarios-executions.md` |
| **Error policy** | Quy ước xử lý lỗi trong scenario. Hỗ trợ `ignore_error`, `on_error`. Mặc định: stop-on-failure. | `modules/04-campaigns-scenarios-executions.md` |
| **Retry policy** | Cấu hình tự động chạy lại step khi gặp lỗi có thể retry. | `modules/04-campaigns-scenarios-executions.md` |
| **run_scenario** | Step đặc biệt cho phép một scenario gọi scenario khác (nested composition) với giới hạn độ sâu. | `modules/04-campaigns-scenarios-executions.md` |
| **Scenario default config** | Tập biến mặc định gắn với scenario, dùng cho mọi device khi không có per-device override. | `modules/04-campaigns-scenarios-executions.md` |
| **Per-device context / override** | Cấu hình riêng cho một device trong một scenario run; ghi đè scenario default cho các key trùng. | `modules/04-campaigns-scenarios-executions.md` |
| **Account variable** | Biến account được resolve trong quá trình dispatch từ scenario config, device context, hoặc account group. | `modules/07-accounts-and-groups.md` |

## C — Thực thi và workflow

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Execution** | Lần chạy thực tế của campaign hoặc scenario, có vòng đời trạng thái: created → running → completed | failed | cancelled. | `modules/04-campaigns-scenarios-executions.md` |
| **Workflow** | Vỏ thực thi durable (bền bỉ) bao quanh execution, cho phép pause / resume / cancel mà không mất tiến độ. Hiện được hậu thuẫn bởi Temporal. | `modules/04-campaigns-scenarios-executions.md` |
| **Dispatch** | Hành vi đưa campaign hoặc scenario từ trạng thái "đã định nghĩa" sang "đang chạy" trên device thật. | `modules/04-campaigns-scenarios-executions.md` |
| **Checkpoint** | Điểm lưu tiến độ trong quá trình thực thi scenario, dùng để khôi phục hoặc theo dõi. | `modules/04-campaigns-scenarios-executions.md` |
| **DLQ (Dead Letter Queue)** | Hàng đợi chứa các execution đã fail, sẵn sàng cho thao tác retry hoặc close. | `modules/04-campaigns-scenarios-executions.md` |
| **Temporal** | Workflow engine nền tảng cung cấp tính durable cho campaign/schedule workflow. | `modules/04-campaigns-scenarios-executions.md` |
| **Activity** | Đơn vị công việc trong Temporal workflow — thường đại diện một bước gọi đến device runtime. | `modules/04-campaigns-scenarios-executions.md` |
| **Worker** | Process tiêu thụ activity từ Temporal queue. | `modules/04-campaigns-scenarios-executions.md` |
| **Artifact** | Bằng chứng (evidence) sinh ra trong quá trình thực thi: screenshot, hierarchy snapshot, log. | `modules/06-content-extraction-artifacts.md` |

## D — Thiết bị, phiên và điều khiển

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Device** | Một máy Android vật lý đã được đăng ký vào Device Farm. | `modules/02-devices-and-control-plane.md` |
| **Device serial** | Định danh do Android trả về cho thiết bị. Khác với ADB serial và khác với device id trong cơ sở dữ liệu. | `modules/02-devices-and-control-plane.md` |
| **Device key** | Khóa xác thực device dùng cho device-auth, khác với JWT của user. | `modules/01-platform-runtime-and-access.md` |
| **Pairing** | Quy trình kết nối ban đầu giữa device và backend để đưa device vào fleet. | `modules/02-devices-and-control-plane.md` |
| **Device session** | Khoảng thời gian một người vận hành hoặc một AI agent reserve riêng một device để thực hiện chuỗi thao tác có ngữ cảnh. | `modules/02-devices-and-control-plane.md` |
| **Reservation** | Hành vi reserve hoặc release device cho một session. | `modules/02-devices-and-control-plane.md` |
| **Device group** | Tập device được gom lại để dispatch theo lô. | `modules/02-devices-and-control-plane.md` |
| **Group action** | Action được fan-out tới nhiều device cùng lúc — là helper điều phối, không thay thế mô hình thực thi độc lập theo device. | `modules/02-devices-and-control-plane.md` |
| **Gesture** | Hành động vật lý mô phỏng người dùng: tap, swipe, long_tap, scroll, pinch, drag, double_tap, key. | `modules/02-devices-and-control-plane.md` |
| **Hierarchy** | Cây UI element của Android (tương tự DOM) — dùng để định vị element và verify trạng thái. | `modules/02-devices-and-control-plane.md` |
| **Selector** | Cách trỏ tới một UI element cụ thể qua text, resource-id, xpath, hoặc content-description. | `modules/02-devices-and-control-plane.md` |
| **Stream** | Luồng video realtime từ màn hình device về dashboard. | `modules/02-devices-and-control-plane.md` |

## E — Relay agent và transport

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **agent-boot** | CLI/process chạy trên máy host gắn vật lý các device Android, làm cầu nối giữa backend Device Farm và device. | `modules/03-agent-boot-and-relay.md` |
| **Relay agent** | Vai trò logic của agent-boot khi đã chạy: duy trì heartbeat, mở kênh điều khiển, watch device attach/detach. | `modules/03-agent-boot-and-relay.md` |
| **Relay serial** | Định danh do relay agent tự sinh ra. Khác với device serial. | `modules/03-agent-boot-and-relay.md` |
| **Bootstrap** | Bước chuẩn bị host và device: đẩy bundle phần mềm, cài u2/ATX, sẵn sàng nhận lệnh. | `modules/03-agent-boot-and-relay.md` |
| **Heartbeat** | Tín hiệu định kỳ relay agent gửi về backend để xác nhận còn hoạt động. | `modules/03-agent-boot-and-relay.md` |
| **FSM (Finite State Machine)** | Mô hình trạng thái device tại relay agent: UNKNOWN → CONNECTING → ONLINE ↔ BUSY → RECONNECTING → DEAD. | `modules/03-agent-boot-and-relay.md` |
| **ADB (Android Debug Bridge)** | Công cụ chuẩn Android để gửi shell command và quản lý package vào device. | `modules/03-agent-boot-and-relay.md` |
| **ADB serial** | Endpoint mà ADB nhận diện device — không nhất thiết trùng device serial. | `modules/03-agent-boot-and-relay.md` |
| **u2 / uiautomator2** | Thư viện open-source điều khiển UI Android (tap, swipe, hierarchy). | `modules/03-agent-boot-and-relay.md` |
| **scrcpy** | Công cụ stream màn hình và điều khiển Android qua máy tính, được Device Farm dùng cho live view. | `modules/03-agent-boot-and-relay.md` |
| **STF (Smartphone Test Farm)** | Hệ sinh thái remote control device Android — Device Farm dùng một số ATX helper từ STF. | `modules/03-agent-boot-and-relay.md` |
| **ATX** | Stack ATX/ATX-agent đi kèm STF và u2. | `modules/03-agent-boot-and-relay.md` |

## F — Nội dung, trích xuất và artifact

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **OCR (Optical Character Recognition)** | Trích xuất văn bản từ ảnh screenshot. | `modules/06-content-extraction-artifacts.md` |
| **AI vision** | Trích xuất dữ liệu qua mô hình AI (OpenAI, Gemini) đọc screenshot và trả về dữ liệu có cấu trúc. | `modules/06-content-extraction-artifacts.md` |
| **Hierarchy extraction** | Trích xuất dữ liệu từ cây UI element thay vì từ ảnh. | `modules/06-content-extraction-artifacts.md` |
| **Extraction strategy** | Chiến lược trích xuất gắn nhãn theo nền tảng và đối tượng dữ liệu, theo định dạng `<platform>_<data_object>` (ví dụ `fb_posts`, `tiktok_videos`). | `modules/08-social-platform-extensions.md` |
| **Content item** | Một bản ghi nội dung đã được chuẩn hóa lưu vào cơ sở dữ liệu. | `modules/06-content-extraction-artifacts.md` |
| **Content type** | Phân loại content. Với social, dùng dạng `<platform>_<object>`: `fb_post`, `fb_comment`, `tiktok_video`, `tiktok_comment`, `threads_post`, `ig_media`, `ig_comment`. | `modules/08-social-platform-extensions.md` |
| **Content collection** | Nhóm các content item theo dự án hoặc người sở hữu để dễ tổ chức và xuất dữ liệu. | `modules/06-content-extraction-artifacts.md` |
| **raw_data** | Trường JSON trong content item chứa các trường platform-specific không map vào cột chuẩn. | `modules/06-content-extraction-artifacts.md` |
| **parent_id / item_level** | Hai trường biểu diễn quan hệ cha–con trong content item, dùng cho cấu trúc comment-reply. | `modules/06-content-extraction-artifacts.md` |
| **save_extraction** | Step lưu kết quả trích xuất vào bảng content item. | `modules/06-content-extraction-artifacts.md` |

## G — Account và rotation

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Account** | Tài khoản social platform được Device Farm quản lý (username, status, tag, metadata, proxy). | `modules/07-accounts-and-groups.md` |
| **Account group** | Nhóm account dùng để rotation. | `modules/07-accounts-and-groups.md` |
| **Round-robin** | Cơ chế xoay vòng đều khi cấp phát account. | `modules/07-accounts-and-groups.md` |
| **Primary account** | Account được đánh dấu là mặc định cho một device. | `modules/07-accounts-and-groups.md` |
| **device_accounts link** | Quan hệ gán account cho device. | `modules/07-accounts-and-groups.md` |

## H — Scheduling

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Schedule** | Lịch chạy campaign theo cron. | `modules/05-scheduling.md` |
| **Schedule run** | Một lần thực thi của schedule. | `modules/05-scheduling.md` |
| **Cron expression** | Cú pháp chuẩn để mô tả lịch chạy lặp lại theo thời gian. | `modules/05-scheduling.md` |
| **Run-now** | Thao tác trigger schedule ngay lập tức, không đợi tick. | `modules/05-scheduling.md` |
| **Toggle** | Thao tác bật/tắt schedule mà không xóa định nghĩa. | `modules/05-scheduling.md` |

## I — Notification, analytics, observability

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Notification** | Thông báo gửi tới người vận hành về sự kiện hệ thống (campaign hoàn thành, fail, schedule run). | `modules/09-notifications-and-analytics.md` |
| **Notification channel** | Cấu hình kênh phân phối: in-app hoặc webhook. | `modules/09-notifications-and-analytics.md` |
| **Unread count** | Số thông báo chưa đọc của một người vận hành. | `modules/09-notifications-and-analytics.md` |
| **Activity log** | Lịch sử hoạt động append-style cho mục đích audit. | `modules/09-notifications-and-analytics.md` |
| **Webhook** | Cơ chế đẩy event ra hệ thống bên ngoài qua HTTP callback. | `modules/09-notifications-and-analytics.md` |
| **Domain event** | Sự kiện cấp nghiệp vụ (ví dụ "campaign hoàn thành") được route qua activity logger và notification service. | `modules/09-notifications-and-analytics.md` |

## J — MCP và AI agent

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **MCP (Model Context Protocol)** | Giao thức chuẩn cho AI agent gọi tool từ một MCP server. | `modules/10-mcp-agent-tools.md` |
| **MCP server** | Process expose các tool điều khiển Device Farm cho AI agent. Device Farm vận hành một MCP server stdio. | `modules/10-mcp-agent-tools.md` |
| **MCP session** | Một phiên làm việc của AI agent với Device Farm — gắn với một device hoặc một device session. | `modules/10-mcp-agent-tools.md` |
| **df_\* tool** | Tiền tố chuẩn cho tên các tool Device Farm trong MCP server. | `modules/10-mcp-agent-tools.md` |
| **Guardrail** | Ràng buộc bảo vệ khi AI agent thao tác: action được phép, bằng chứng phải thu, điều kiện handoff cho người vận hành. | `modules/10-mcp-agent-tools.md` |
| **Handoff** | Hành vi chuyển quyền điều khiển từ AI agent sang người vận hành khi gặp trạng thái cần can thiệp. | `modules/10-mcp-agent-tools.md` |

## K — Bảo mật và truy cập

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **JWT (JSON Web Token)** | Token xác thực cấp cho user sau khi đăng nhập. | `modules/01-platform-runtime-and-access.md` |
| **Refresh token** | Token dùng để gia hạn JWT mà không cần đăng nhập lại. | `modules/01-platform-runtime-and-access.md` |
| **Device-auth** | Cơ chế xác thực qua device key — dùng cho device gọi runtime API. | `modules/01-platform-runtime-and-access.md` |
| **Public router** | Tập route không yêu cầu xác thực (ví dụ health, login). | `modules/01-platform-runtime-and-access.md` |
| **Safe mode** | Chế độ runtime guard khi cơ sở dữ liệu hoặc dependency tạm không sẵn sàng — chỉ phục vụ route public. | `modules/01-platform-runtime-and-access.md` |

## L — Frontend, API, tích hợp

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Dashboard** | Giao diện web Next.js cho người vận hành, builder, supervisor. | `modules/11-frontend-dashboard.md` |
| **Generated client** | Thư viện TypeScript được tự sinh từ OpenAPI spec để frontend gọi backend. | `modules/11-frontend-dashboard.md` |
| **Next API proxy** | Lớp adapter trong Next.js cho các route không có trong generated client. | `modules/11-frontend-dashboard.md` |
| **OpenAPI** | Spec chuẩn mô tả API, được sinh tự động từ backend. | `modules/01-platform-runtime-and-access.md` |
| **i18n** | Quốc tế hóa giao diện — dashboard tổ chức route theo `/[locale]/...`. | `modules/11-frontend-dashboard.md` |
| **WebSocket** | Giao thức kết nối hai chiều dùng cho stream và event realtime. | `modules/02-devices-and-control-plane.md` |
| **gRPC** | Giao thức RPC hiệu năng cao được dùng cho relay transport. | `modules/03-agent-boot-and-relay.md` |
| **MinIO / S3** | Object storage cho ảnh và artifact. | `modules/06-content-extraction-artifacts.md` |

## M — Platform profile

| Thuật ngữ (EN) | Định nghĩa nghiệp vụ | Ghi chú |
|---|---|---|
| **Platform profile** | Hồ sơ chuẩn cho một social platform — chứa product goal, supported data scope, step và strategy, content type, account requirement, completion criteria. | `platforms/*.md` |
| **Coverage profile** | Mức L1/L2/L3 được khai báo cho từng platform. | `03-capability-matrix.md` |
| **Platform-qualified content type** | Content type được đặt tên theo nền tảng để tránh nhầm lẫn (ví dụ `fb_post`, `ig_media`). | `modules/08-social-platform-extensions.md` |
| **Legacy alias** | Tên cũ được hệ thống vẫn chấp nhận để tương thích ngược (ví dụ `tap_fb_comment_button`). | `modules/08-social-platform-extensions.md` |

## N — Viết tắt thường gặp

| Viết tắt | Đầy đủ | Ghi chú |
|---|---|---|
| PRD | Product Requirements Document | Tài liệu yêu cầu sản phẩm |
| BRD | Business Requirements Document | Tài liệu yêu cầu nghiệp vụ |
| PO | Product Owner | Chủ sản phẩm |
| PM | Product Manager | Quản lý sản phẩm |
| BA | Business Analyst | Phân tích nghiệp vụ |
| QA | Quality Assurance | Đảm bảo chất lượng |
| UAT | User Acceptance Testing | Kiểm thử chấp nhận của người dùng |
| KPI | Key Performance Indicator | Chỉ số đo lường thành công |
| SLA | Service Level Agreement | Cam kết mức dịch vụ |
| SLO | Service Level Objective | Mục tiêu mức dịch vụ |
| MTTR | Mean Time To Recover | Thời gian phục hồi trung bình |
| DLQ | Dead Letter Queue | Hàng đợi xử lý lỗi |
| FSM | Finite State Machine | Máy trạng thái hữu hạn |
| MCP | Model Context Protocol | Giao thức tool dành cho AI agent |
| OCR | Optical Character Recognition | Nhận dạng ký tự quang học |
| ADB | Android Debug Bridge | Công cụ debug Android |
| STF | Smartphone Test Farm | Hệ sinh thái remote control Android |
| ATX | (tên riêng) | Stack đi kèm STF/u2 |
| u2 | uiautomator2 | Thư viện UI automation Android |
| JWT | JSON Web Token | Token xác thực |
| RBAC | Role-Based Access Control | Phân quyền theo vai trò |
| OTP | One-Time Password | Mã xác thực một lần |
| 2FA | Two-Factor Authentication | Xác thực hai yếu tố |

## Quy ước cập nhật

Bất kỳ thuật ngữ mới nào xuất hiện lần đầu trong các tài liệu module hoặc platform đều phải được bổ sung vào bảng này trong cùng một thay đổi. Trường hợp một thuật ngữ đã có nhưng định nghĩa lệch giữa các tài liệu, định nghĩa tại đây là chuẩn.
