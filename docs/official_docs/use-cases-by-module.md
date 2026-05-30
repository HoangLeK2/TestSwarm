# Tổng hợp use case theo module

> **Nguồn:** `docs/official_docs/modules/*.md`
> **Cập nhật lần cuối:** 2026-05-27
> **Phạm vi:** Trích xuất từ mục `4.2 Bảng use case` của từng tài liệu module. File `docs/official_docs/modules/README.md` là tài liệu chỉ mục, không có bảng use case riêng.

## Tổng quan

| Module | Tên module | Số use case |
|---|---|---:|
| DF-MOD-01 | Nền tảng & Bảo mật truy cập | 10 |
| DF-MOD-02 | Thiết bị & Mặt phẳng điều khiển | 14 |
| DF-MOD-03 | Agent Boot & Relay | 11 |
| DF-MOD-04 | Campaign, Scenario & Execution | 13 |
| DF-MOD-05 | Lập lịch | 9 |
| DF-MOD-06 | Trích xuất nội dung & Artifact | 13 |
| DF-MOD-07 | Account & Account Group | 13 |
| DF-MOD-08 | Mở rộng nền tảng social | 10 |
| DF-MOD-09 | Thông báo & Analytics | 13 |
| DF-MOD-10 | Công cụ AI Agent qua MCP | 13 |
| DF-MOD-11 | Frontend & Dashboard | 15 |
| **Tổng** |  | **134** |

## DF-MOD-01 - Nền tảng & Bảo mật truy cập

Nguồn: [modules/01-platform-runtime-and-access.md](modules/01-platform-runtime-and-access.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-01-01 | Người vận hành (mọi vai trò) | Là người vận hành, tôi muốn đăng nhập bằng tên đăng nhập và mật khẩu để nhận JWT và truy cập dashboard của tổ chức tôi. | Must |
| UC-01-02 | Người vận hành | Là người vận hành, tôi muốn token đăng nhập tự gia hạn qua refresh token để không phải đăng nhập lại trong mỗi phiên làm việc dài. | Must |
| UC-01-03 | Admin tổ chức | Là admin tổ chức, tôi muốn mời thành viên mới vào tổ chức để họ chỉ thấy được tài nguyên thuộc tổ chức của chúng tôi. | Must |
| UC-01-04 | Admin tổ chức | Là admin tổ chức, tôi muốn vô hiệu hóa thành viên rời tổ chức để họ không truy cập được dữ liệu sau khi rời. | Must |
| UC-01-05 | Kỹ sư nền tảng | Là kỹ sư nền tảng, tôi muốn gắn route mới vào đúng auth boundary (public / user-auth / admin-auth / device-auth) để mỗi route được bảo vệ đúng mức. | Must |
| UC-01-06 | Kỹ sư nền tảng | Là kỹ sư nền tảng, tôi muốn frontend tự đồng bộ với backend qua OpenAPI để không phải duy trì hai bộ client thủ công. | Must |
| UC-01-07 | Thiết bị Android (qua agent) | Là thiết bị Android đã đăng ký, tôi muốn gọi runtime API bằng device key để gửi kết quả thực thi mà không cần JWT người dùng. | Must |
| UC-01-08 | Hệ thống giám sát hạ tầng | Là hệ thống giám sát, tôi muốn endpoint health luôn trả lời ngay cả khi database tạm tắt để phân biệt được sự cố database với sự cố toàn bộ ứng dụng. | Should |
| UC-01-09 | Dashboard frontend | Là dashboard, tôi muốn kết nối WebSocket để nhận stream và event realtime sau khi đã xác thực JWT. | Must |
| UC-01-10 | Admin tổ chức | Là admin tổ chức, tôi muốn xem trạng thái safe mode để biết khi nào toàn bộ chức năng nghiệp vụ đang bị treo do hạ tầng. | Could |

## DF-MOD-02 - Thiết bị & Mặt phẳng điều khiển

Nguồn: [modules/02-devices-and-control-plane.md](modules/02-devices-and-control-plane.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-02-01 | Fleet Operator | Là người vận hành fleet, tôi muốn pair một thiết bị Android mới vào hệ thống để đưa nó vào inventory và sẵn sàng nhận lệnh. | Must |
| UC-02-02 | Fleet Operator | Là người vận hành fleet, tôi muốn xem danh sách thiết bị trong fleet kèm trạng thái online/offline để biết thiết bị nào cần can thiệp. | Must |
| UC-02-03 | Fleet Operator | Là người vận hành fleet, tôi muốn gom các thiết bị thuộc cùng dự án vào một device group để dispatch theo lô. | Must |
| UC-02-04 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn reserve một thiết bị cho phiên làm việc thủ công để không bị scenario tự động hoặc người khác chiếm cùng lúc. | Must |
| UC-02-05 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn release thiết bị khi xong phiên để thiết bị quay lại pool dùng chung. | Must |
| UC-02-06 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn gửi gesture (tap, swipe, scroll, input_text, key, clipboard...) từ dashboard tới thiết bị đang reserve để thao tác thủ công có giám sát. | Must |
| UC-02-07 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn đọc UI hierarchy của thiết bị để xác định selector cho thao tác tiếp theo. | Must |
| UC-02-08 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn xem screenshot và mở stream realtime của thiết bị để giám sát thao tác từ xa. | Must |
| UC-02-09 | Automation Builder | Là người dựng kịch bản, tôi muốn override cấu hình per-device (account, target list, pacing) để cùng một scenario chạy khác nhau trên từng thiết bị. | Must |
| UC-02-10 | Fleet Operator | Là người vận hành fleet, tôi muốn fan-out một action (ví dụ "khóa màn hình", "mở app cụ thể") tới tất cả thiết bị trong group cùng lúc để chuẩn bị hàng loạt. | Should |
| UC-02-11 | Fleet Operator | Là người vận hành fleet, tôi muốn attach scrcpy cho live view của một thiết bị để giám sát trực quan; detach khi không cần để tiết kiệm tài nguyên. | Should |
| UC-02-12 | Fleet Operator | Là người vận hành fleet, tôi muốn xem device session đang active trên mỗi thiết bị, ai sở hữu session, để xử lý xung đột. | Should |
| UC-02-13 | Fleet Operator | Là người vận hành fleet, tôi muốn unpair một thiết bị khỏi fleet khi thiết bị đó được tái phân bổ hoặc loại bỏ. | Should |
| UC-02-14 | AI Operations Supervisor | Là người giám sát AI, tôi muốn AI agent reserve một thiết bị qua MCP và thực thi cùng các primitive gesture/hierarchy/screenshot mà người vận hành dùng. | Could |

## DF-MOD-03 - Agent Boot & Relay

Nguồn: [modules/03-agent-boot-and-relay.md](modules/03-agent-boot-and-relay.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-03-01 | Fleet Operator | Là người vận hành fleet, tôi muốn cài và khởi chạy agent-boot trên một máy host mới để host đó tham gia fleet. | Must |
| UC-03-02 | Fleet Operator | Là người vận hành fleet, tôi muốn agent-boot tự bootstrap thiết bị Android mới cắm vào (đẩy u2 và ATX khi cần) để thiết bị sẵn sàng nhận lệnh. | Must |
| UC-03-03 | Fleet Operator | Là người vận hành fleet, tôi muốn xem tất cả relay agent đang hoạt động tại trang `/dashboard/relay-agents` để biết host nào còn online. | Must |
| UC-03-04 | Fleet Operator | Là người vận hành fleet, tôi muốn agent tự reconnect khi mất kết nối tạm thời để không phải khởi động lại thủ công. | Must |
| UC-03-05 | Fleet Operator | Là người vận hành fleet, tôi muốn agent ưu tiên USB hơn WiFi để giảm sự cố do WiFi chập chờn. | Must |
| UC-03-06 | Fleet Operator | Là người vận hành fleet, tôi muốn biết FSM state của từng thiết bị (UNKNOWN, CONNECTING, ONLINE, BUSY, RECONNECTING, DEAD) để chẩn đoán nhanh tình trạng. | Must |
| UC-03-07 | Platform Engineer | Là kỹ sư nền tảng, tôi muốn agent-boot dùng được cả WebSocket và gRPC để có đường lui khi một transport gặp sự cố. | Must |
| UC-03-08 | Platform Engineer | Là kỹ sư nền tảng, tôi muốn heartbeat của agent định kỳ về backend để dashboard nhận biết agent còn sống. | Must |
| UC-03-09 | Platform Engineer | Là kỹ sư nền tảng, tôi muốn cập nhật bundle (u2/ATX) trên agent mà không gián đoạn các phiên đang chạy quá lâu. | Should |
| UC-03-10 | Fleet Operator | Là người vận hành fleet, tôi muốn nhận cảnh báo khi một relay agent rớt hoặc khi tỷ lệ thiết bị DEAD vượt ngưỡng. | Should |
| UC-03-11 | Platform Engineer | Là kỹ sư nền tảng, tôi muốn bootstrap hàng loạt thiết bị mới gắn vào một host qua một thao tác để giảm công đăng ký từng máy. | Should |

## DF-MOD-04 - Campaign, Scenario & Execution

Nguồn: [modules/04-campaigns-scenarios-executions.md](modules/04-campaigns-scenarios-executions.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-04-01 | Automation Builder | Là người dựng kịch bản, tôi muốn tạo một scenario gồm chuỗi step có thứ tự để diễn đạt workflow social mà tôi muốn lặp lại trên nhiều device. | Must |
| UC-04-02 | Automation Builder | Là người dựng kịch bản, tôi muốn biểu diễn scenario dạng graph với nhánh điều kiện và vòng lặp để xử lý các biến thể UI mà không phải duplicate scenario. | Must |
| UC-04-03 | Automation Builder | Là người dựng kịch bản, tôi muốn sử dụng step `run_scenario` để gọi một scenario con bên trong scenario cha nhằm tái sử dụng các đoạn flow phổ biến. | Must |
| UC-04-04 | Automation Builder | Là người dựng kịch bản, tôi muốn khai báo error policy (`ignore_error`, `on_error`) và retry policy ở cấp step để định nghĩa tường minh khi nào scenario được phép tiếp tục sau lỗi. | Must |
| UC-04-05 | Automation Builder | Là người dựng kịch bản, tôi muốn preview run scenario trên một device cô lập trước khi dispatch để xác minh từng step trước khi triển khai diện rộng. | Should |
| UC-04-06 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn tạo một campaign chọn scenario có sẵn, chọn fleet device hoặc device group, và dispatch trong một thao tác. | Must |
| UC-04-07 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn đặt biến per-device (per-device override) để cùng một scenario chạy với input khác nhau trên từng device. | Must |
| UC-04-08 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn theo dõi tiến độ campaign theo từng device với trạng thái running, completed, failed, và artifact đính kèm. | Must |
| UC-04-09 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn pause, resume, hoặc cancel một campaign đang chạy mà không mất tiến độ đã đạt được. | Must |
| UC-04-10 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn xem các execution fail trong DLQ, đọc screenshot tại thời điểm fail, và quyết định retry hoặc đóng. | Must |
| UC-04-11 | Automation Builder | Là người dựng kịch bản, khi một step UI-gated không tìm thấy element mong đợi, tôi muốn scenario dừng và báo step lỗi rõ ràng thay vì hệ thống "đoán" hành vi phục hồi. | Must |
| UC-04-12 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn artifact thu được (screenshot, hierarchy snapshot) đính kèm theo execution để truy vết khi báo cáo cho khách hàng B2B. | Must |
| UC-04-13 | Automation Builder | Là người dựng kịch bản, tôi muốn biến của campaign, scenario default, per-device override, account, và runtime được resolve theo thứ tự ưu tiên rõ ràng để tôi đoán được hành vi runtime. | Must |

## DF-MOD-05 - Lập lịch

Nguồn: [modules/05-scheduling.md](modules/05-scheduling.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-05-01 | Operator | Là người vận hành, tôi muốn tạo schedule cho một campaign theo cron expression để campaign chạy tự động đúng giờ mỗi ngày mà không cần tôi can thiệp. | Must |
| UC-05-02 | Operator | Là người vận hành, tôi muốn cập nhật cron expression hoặc đổi campaign đích của schedule khi nhu cầu thay đổi mà không phải tạo lại schedule. | Must |
| UC-05-03 | Operator | Là người vận hành, tôi muốn toggle bật/tắt schedule mà không phải xóa định nghĩa để khi cần bật lại tôi không phải nhập cron từ đầu. | Must |
| UC-05-04 | Operator | Là người vận hành, tôi muốn xóa schedule khi đã chắc chắn không dùng nữa để dọn danh sách schedule. | Should |
| UC-05-05 | Operator | Là người vận hành, tôi muốn trigger run-now một schedule ngoài lịch (ví dụ test ngay sau khi tạo) mà không phá lịch định kỳ. | Must |
| UC-05-06 | Operator | Là người vận hành, tôi muốn xem lịch sử các lần schedule đã chạy với trạng thái (đã trigger, thành công, thất bại) và id execution con để debug. | Must |
| UC-05-07 | Automation Builder | Là người dựng kịch bản, tôi muốn frontend cảnh báo cron expression không hợp lệ ngay trong form để tôi không phải đợi backend phản hồi. | Should |
| UC-05-08 | Operator | Là người vận hành, tôi muốn schedule tiếp tục hoạt động ở mức cơ bản khi Temporal tạm tắt để không mất tick quan trọng. | Should |
| UC-05-09 | Operator | Là người vận hành, tôi muốn biết khi nào hai schedule trùng giờ có khả năng chạy chồng để chủ động giãn cron. | Could |

## DF-MOD-06 - Trích xuất nội dung & Artifact

Nguồn: [modules/06-content-extraction-artifacts.md](modules/06-content-extraction-artifacts.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-06-01 | Automation Builder | Là người dựng kịch bản, tôi muốn chọn hierarchy extraction cho các phần UI ổn định để tiết kiệm chi phí và đạt độ chính xác cao nhất. | Must |
| UC-06-02 | Automation Builder | Là người dựng kịch bản, tôi muốn dùng OCR cho text nằm trong ảnh hoặc trong vùng không expose qua hierarchy. | Must |
| UC-06-03 | Automation Builder | Là người dựng kịch bản, tôi muốn dùng AI vision cho các trang social phức tạp có schema thay đổi liên tục, kèm prompt mô tả cấu trúc tôi cần. | Should |
| UC-06-04 | Automation Builder | Là người dựng kịch bản, tôi muốn gọi step `save_extraction` để lưu kết quả vào content store với content type platform-qualified. | Must |
| UC-06-05 | Automation Builder | Là người dựng kịch bản, tôi muốn các trường platform-specific không khớp cột chuẩn được giữ trong raw_data để không mất thông tin. | Must |
| UC-06-06 | Automation Builder | Là người dựng kịch bản, tôi muốn biểu diễn comment-reply qua parent_id và item_level để truy vấn theo cây hội thoại. | Must |
| UC-06-07 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn xem danh sách content item lọc theo content type, theo collection, theo campaign, theo khoảng thời gian. | Must |
| UC-06-08 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn tạo content collection để gom dữ liệu theo dự án phục vụ khách hàng B2B, không lẫn giữa các yêu cầu khác nhau. | Must |
| UC-06-09 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn truy vết một content item về campaign, device, scenario, execution, và account đã tạo ra nó. | Must |
| UC-06-10 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn mở artifact của một execution để xem screenshot và hierarchy snapshot tại từng step khi báo cáo cho khách hàng B2B. | Must |
| UC-06-11 | Automation Builder | Là người dựng kịch bản, tôi muốn gọi `/api/devices/{serial}/extract/{hierarchy|ocr|ai}` ngoài scenario để thử strategy mới trên thiết bị đang reserve. | Should |
| UC-06-12 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn dữ liệu trùng lặp tối thiểu trong cùng một collection để báo cáo không bị thổi số liệu. | Should |
| UC-06-13 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn nhìn rõ giới hạn ngân sách AI vision đã dùng để chủ động chuyển engine khi gần ngưỡng. | Could |

## DF-MOD-07 - Account & Account Group

Nguồn: [modules/07-accounts-and-groups.md](modules/07-accounts-and-groups.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-07-01 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn tạo một account với platform, username, status, tag và metadata để bắt đầu vận hành. | Must |
| UC-07-02 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn import danh sách account hàng loạt từ file để khởi tạo nhanh fleet account của một dự án mới. | Must |
| UC-07-03 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn cập nhật status account (active, suspended, retired) để phản ánh tình trạng thực tế và loại các account "đau" ra khỏi rotation. | Must |
| UC-07-04 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn gắn account vào device qua device_accounts link, có cờ primary để đánh dấu account chính cho device. | Must |
| UC-07-05 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn tạo account group và thêm account vào group để hệ thống cấp phát theo round-robin khi scenario chạy. | Must |
| UC-07-06 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn gọi endpoint round-robin để lấy account kế tiếp trong group khi cần dispatch không qua scenario hoặc khi tích hợp ngoài. | Should |
| UC-07-07 | Automation Builder | Là người dựng kịch bản, tôi muốn khai báo account intent trong scenario config (chọn account cụ thể hoặc reference tới account group) để runtime resolve khi dispatch. | Must |
| UC-07-08 | Automation Builder | Là người dựng kịch bản, tôi muốn account variable được resolve theo cùng cơ chế resolve biến của scenario (xem module Campaign) để hành vi runtime đoán được. | Must |
| UC-07-09 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn gắn proxy_id cho account để khi scenario chạy, các request mạng đi qua proxy phù hợp. | Should |
| UC-07-10 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn xem usage_counter của account để biết account nào đang dùng quá nhiều và cần nghỉ. | Should |
| UC-07-11 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn dữ liệu content item lưu được account id đã sinh ra dữ liệu để truy vết và báo cáo theo account. | Must |
| UC-07-12 | Automation Builder | Là người dựng kịch bản, khi scenario không khai báo account intent mà step lại cần login, tôi muốn scenario fail rõ ràng thay vì Device Farm tự chọn account thay tôi. | Must |
| UC-07-13 | Social Data Operator | Là người thu thập dữ liệu social, tôi muốn phân biệt account group với device group trong UI và tài liệu để không nhầm lẫn khi cấu hình campaign. | Must |

## DF-MOD-08 - Mở rộng nền tảng social

Nguồn: [modules/08-social-platform-extensions.md](modules/08-social-platform-extensions.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-08-01 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn có một checklist artifact rõ ràng để biết khi nào platform mới đã đủ điều kiện vào trạng thái draft hoặc active. | Must |
| UC-08-02 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn đặt tên step type và extraction strategy theo một quy ước thống nhất để mọi platform có cùng phong cách. | Must |
| UC-08-03 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn lưu các field platform-specific không map vào content_items chuẩn vào trường `raw_data` để không mất thông tin. | Must |
| UC-08-04 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn giữ legacy alias (vd `tap_fb_comment_button`) hoạt động cho scenario cũ trong khi triển khai naming canonical mới. | Must |
| UC-08-05 | Automation Builder | Là người dựng kịch bản, tôi muốn step Facebook, TikTok, Threads, Instagram có cùng cấu trúc khai báo trong scenario để tôi không phải học lại với mỗi platform. | Must |
| UC-08-06 | Automation Builder | Là người dựng kịch bản, tôi muốn `extract` luôn dùng kèm `strategy` theo dạng `<platform>_<data_object>` để dễ đọc và tra cứu. | Must |
| UC-08-07 | Automation Builder | Là người dựng kịch bản, tôi muốn content type luôn được qualified theo platform (vd `fb_post`, `tiktok_video`) để truy vấn dữ liệu sau này không cần đoán platform. | Must |
| UC-08-08 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn được cảnh báo nếu ai đó cố tạo runner platform riêng bên ngoài scenario step model. | Must |
| UC-08-09 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn khai báo L3 guardrail riêng cho platform (allowed action, evidence requirement, handoff condition) trước khi platform được tuyên bố L3 active. | Should |
| UC-08-10 | Platform Engineer | Là kỹ sư mở rộng nền tảng, khi đẩy platform từ draft sang active, tôi muốn capability matrix và roadmap được cập nhật trong cùng release. | Must |

## DF-MOD-09 - Thông báo & Analytics

Nguồn: [modules/09-notifications-and-analytics.md](modules/09-notifications-and-analytics.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-09-01 | Admin tổ chức | Là admin, tôi muốn tạo notification channel kiểu webhook (Slack, Telegram, custom) để event của tổ chức được đẩy ra hệ thống chat đang dùng. | Must |
| UC-09-02 | Admin tổ chức | Là admin, tôi muốn liệt kê, cập nhật, vô hiệu hóa, hoặc xóa notification channel khi cấu hình thay đổi mà không phải làm lại từ đầu. | Must |
| UC-09-03 | Operator (mọi vai trò) | Là người vận hành, tôi muốn thấy danh sách notification in-app trong dashboard với trạng thái đã đọc / chưa đọc rõ ràng. | Must |
| UC-09-04 | Operator | Là người vận hành, tôi muốn thấy unread count nổi bật trên thanh điều hướng để biết ngay có việc cần xử lý mà không phải mở panel. | Must |
| UC-09-05 | Operator | Là người vận hành, tôi muốn đánh dấu một notification đã đọc, hoặc đánh dấu đã đọc tất cả, để dọn dẹp danh sách sau khi đã xử lý. | Must |
| UC-09-06 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn nhận notification ngay khi campaign hoàn thành hoặc fail, kèm link tới execution để mở DLQ nếu cần. | Must |
| UC-09-07 | Operator | Là người vận hành, tôi muốn nhận notification khi schedule run thất bại để xử lý sớm thay vì phát hiện vào sáng hôm sau. | Must |
| UC-09-08 | Fleet Operator | Là người vận hành cụm thiết bị, tôi muốn nhận notification khi device đi offline kéo dài để chủ động kiểm tra phần cứng. | Should |
| UC-09-09 | AI Operations Supervisor | Là người giám sát AI, tôi muốn webhook đẩy ra Slack/Telegram khi MCP agent thực hiện hành động nhạy cảm để có cơ hội review nhanh. | Should |
| UC-09-10 | Operator / Admin | Là người vận hành, tôi muốn xem activity log của tổ chức trong dashboard, lọc theo loại event và khoảng thời gian, để truy vết "ai làm gì lúc nào". | Must |
| UC-09-11 | Admin tổ chức | Là admin, tôi muốn activity log không bị sửa hay xóa qua API thông thường để tin cậy được cho mục đích audit. | Must |
| UC-09-12 | Operator | Là người vận hành, tôi muốn xem analytics activity tổng hợp (số lượng event theo ngày, theo loại) để cảm nhận xu hướng vận hành. | Should |
| UC-09-13 | Admin tổ chức | Là admin, tôi muốn webhook delivery thất bại được ghi nhận để biết kênh ngoài đang gặp vấn đề và xử lý cấu hình. | Should |

## DF-MOD-10 - Công cụ AI Agent qua MCP

Nguồn: [modules/10-mcp-agent-tools.md](modules/10-mcp-agent-tools.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-10-01 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn đăng ký một MCP server Device Farm vào AI agent (Claude, GPT, Gemini) để agent có quyền truy cập các tool df_*. | Must |
| UC-10-02 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn cấp DEVICE_FARM_MCP_TOKEN cho một agent thao tác trên một device cụ thể, hoặc MCP_AUTH_TOKEN cho agent có ngữ cảnh tổ chức. | Must |
| UC-10-03 | Automation Builder | Là người dựng kịch bản dùng AI, tôi muốn agent đọc danh sách tool df_* qua tools/list để biết các thao tác khả dụng trước khi gọi. | Must |
| UC-10-04 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn agent reserve một device qua df_start_session để mọi thao tác sau đó được persist vào mcp_sessions. | Must |
| UC-10-05 | Automation Builder | Là người dựng kịch bản dùng AI, tôi muốn agent gọi tool gesture (df_tap, df_swipe, df_input_text) hoặc tool UI hierarchy (df_get_hierarchy) bằng device serial hoặc session_id. | Must |
| UC-10-06 | Automation Builder | Là người dựng kịch bản dùng AI, tôi muốn agent gọi df_run_scenario để vận hành một scenario có sẵn trên device đang reserve. | Must |
| UC-10-07 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn agent gọi tool content (df_save_extraction, df_list_content) để persist quan sát thành evidence. | Must |
| UC-10-08 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn mọi MCP action được ghi vào activity log để tôi review về sau và tái hiện chuỗi quyết định của agent. | Must |
| UC-10-09 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn ràng buộc L3: một agent chỉ điều khiển một device/session tại một thời điểm để giảm rủi ro tương tác chéo. | Must |
| UC-10-10 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn guardrail theo platform (allowed action, evidence requirement, handoff condition) được khai báo trước khi tuyên bố L3 active cho platform. | Should |
| UC-10-11 | AI Operations Supervisor | Là người giám sát AI vận hành, tôi muốn agent bàn giao điều khiển sang người vận hành khi gặp trạng thái mơ hồ (ví dụ CAPTCHA, OTP) thay vì agent đoán bừa. | Should |
| UC-10-12 | Automation Builder | Là người dựng kịch bản dùng AI, tôi muốn tool df_* wrap đúng HTTP route đã có để hành vi giữa MCP và HTTP nhất quán. | Must |
| UC-10-13 | Fleet Operator | Là người vận hành fleet, tôi muốn biết device nào đang bị một agent reserve qua MCP để không dispatch campaign chồng. | Must |

## DF-MOD-11 - Frontend & Dashboard

Nguồn: [modules/11-frontend-dashboard.md](modules/11-frontend-dashboard.md)

| ID | Persona | Mô tả | Mức ưu tiên |
|---|---|---|---|
| UC-11-01 | Mọi persona | Là người vận hành, tôi muốn đăng nhập dashboard và thấy navigation tới các domain (devices, campaigns, content, schedules, notifications, ...) tổ chức rõ ràng để định vị tính năng nhanh. | Must |
| UC-11-02 | Mọi persona | Là người vận hành, tôi muốn dashboard hiển thị bằng ngôn ngữ địa phương qua i18n routing `/[locale]/dashboard/...` để đội đa quốc gia làm việc thoải mái. | Must |
| UC-11-03 | Fleet Operator | Là người vận hành cụm thiết bị, tôi muốn mở trang `/dashboard/devices` để xem trạng thái online/offline, heartbeat gần nhất, và thông tin định danh của từng device. | Must |
| UC-11-04 | Fleet Operator | Là người vận hành cụm thiết bị, tôi muốn mở live view một device qua scrcpy stream để quan sát màn hình realtime khi cần can thiệp thủ công. | Must |
| UC-11-05 | Fleet Operator | Là người vận hành cụm thiết bị, tôi muốn xem dashboard `/dashboard/relay-agents` để biết relay agent nào đang hoạt động, mất kết nối, hoặc cần restart. | Must |
| UC-11-06 | Automation Builder | Là người dựng kịch bản, tôi muốn mở `/scenario-flow/{id}` để vẽ graph scenario gồm node và edge có nhánh điều kiện, lưu lại để campaign tiêu thụ. | Must |
| UC-11-07 | Automation Builder | Là người dựng kịch bản, tôi muốn thấy scenario template tại `/dashboard/scenario-templates` để tái sử dụng các đoạn flow phổ biến thay vì vẽ lại từ đầu. | Must |
| UC-11-08 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn dispatch campaign tại `/dashboard/campaigns` và theo dõi tiến độ từng device trong campaign đang chạy. | Must |
| UC-11-09 | Social Data Operator | Là người thu thập dữ liệu, tôi muốn mở `/dashboard/content` để duyệt content item theo collection, lọc theo platform và content type. | Must |
| UC-11-10 | Operator | Là người vận hành, tôi muốn cấu hình schedule tại `/dashboard/schedules` với cron expression, bật/tắt theo nhu cầu mà không phải xóa. | Must |
| UC-11-11 | Operator | Là người vận hành, tôi muốn mở panel notification và thấy unread count nổi bật trên thanh điều hướng để biết ngay có việc cần xử lý. | Must |
| UC-11-12 | Operator | Là người vận hành, tôi muốn mở `/dashboard/activity-history` để truy vết lịch sử hoạt động của tổ chức theo loại event và khoảng thời gian. | Must |
| UC-11-13 | Admin tổ chức | Là admin, tôi muốn cấu hình account và account group tại `/dashboard/accounts` và `/dashboard/device-farm/account-groups` để gán account vào device và scenario. | Must |
| UC-11-14 | Platform Engineer | Là kỹ sư mở rộng nền tảng, tôi muốn frontend tự đồng bộ với backend qua generated TypeScript client để không phải duy trì client thủ công. | Must |
| UC-11-15 | Platform Engineer | Là kỹ sư mở rộng nền tảng, khi backend có route mới chưa có trong generated client, tôi muốn dùng Next API proxy như một adapter tạm thời cho tới khi client được regenerate. | Must |
