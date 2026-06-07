# Device Farm Portal - Kịch bản thuyết trình cho người dùng

## Mục tiêu bài thuyết trình

Giúp người nghe hiểu rất nhanh: khi vào Device Farm Portal, user không phải nhìn một dashboard kỹ thuật rời rạc, mà đang đi theo một quy trình vận hành điện thoại thật:

1. Chuẩn bị tài nguyên: thiết bị, tài khoản, nhóm, kịch bản.
2. Chạy tự động: tạo chiến dịch, chọn thiết bị, phân phối lượt chạy.
3. Theo dõi và xử lý: xem tiến độ, ảnh bằng chứng, lỗi cần retry hoặc đóng.
4. Kiểm tra kết quả: dữ liệu thu thập, thông báo, lịch sử hoạt động, phân tích.

Thông điệp chính nên lặp lại trong lúc nói:

> Portal này biến một dàn điện thoại Android thật thành một hệ thống vận hành có kiểm soát: user chuẩn bị kịch bản một lần, chạy trên nhiều thiết bị, theo dõi được từng lỗi, và có bằng chứng sau mỗi lần chạy.

## Persona để thuyết trình dễ hiểu

Nên gọi người dùng là "operator" hoặc "nhân sự vận hành".

Người này có 4 câu hỏi chính:

- Hôm nay có bao nhiêu thiết bị sẵn sàng?
- Tôi cần chạy tác vụ gì trên thiết bị?
- Chạy xong thành công hay lỗi ở đâu?
- Kết quả và bằng chứng nằm ở đâu để kiểm tra lại?

Vì vậy, khi thuyết trình đừng bắt đầu bằng database, Temporal, relay hay MCP. Hãy bắt đầu bằng việc user vào portal để hoàn thành một công việc thực tế.

## Câu chuyện 30 giây mở đầu

"Device Farm Portal là web dashboard để vận hành nhiều điện thoại Android thật. Thay vì cầm từng máy, user vào portal để xem máy nào online, chuẩn bị tài khoản và kịch bản, chạy chiến dịch trên một hoặc nhiều thiết bị, rồi theo dõi kết quả bằng ảnh chụp, log bước chạy, hàng đợi lỗi và dữ liệu đã thu thập. Điểm quan trọng là hệ thống không chỉ bấm tự động, mà còn giúp operator biết khi nào cần can thiệp, retry hoặc đối soát kết quả."

## Slide 1 - Vấn đề trước khi có portal

Tiêu đề: Vận hành nhiều điện thoại thủ công rất khó kiểm soát

Nội dung slide:

- Mỗi điện thoại có trạng thái khác nhau: online, offline, đang bận, lỗi app.
- Một thao tác phải lặp lại trên nhiều máy.
- Khi lỗi, khó biết lỗi ở bước nào và có nên chạy lại không.
- Kết quả thu thập nằm rải rác, khó đối soát.

Script nói:

"Nếu chỉ cầm điện thoại hoặc dùng tool rời rạc, operator phải tự nhớ máy nào đang chạy, máy nào lỗi, tài khoản nào đang dùng, kết quả nào đã thu. Khi số lượng thiết bị tăng lên, vấn đề không còn là bấm nhanh hơn, mà là kiểm soát toàn bộ quy trình."

## Slide 2 - Device Farm Portal giải quyết gì?

Tiêu đề: Một portal cho toàn bộ vòng đời vận hành thiết bị

Nội dung slide:

- Xem và điều khiển điện thoại thật từ web.
- Ghi thao tác thành kịch bản có thể tái sử dụng.
- Gắn tài khoản, nhóm thiết bị, nhóm tài khoản.
- Chạy chiến dịch song song hoặc tuần tự.
- Theo dõi tiến độ, ảnh bằng chứng, lỗi và dữ liệu thu thập.

Script nói:

"Portal gom các việc user phải làm thành một luồng duy nhất: chuẩn bị, chạy, theo dõi, xử lý lỗi, kiểm tra kết quả. User không cần đi tìm log kỹ thuật trước; họ nhìn theo ngôn ngữ vận hành: thiết bị, kịch bản, chiến dịch, kết quả, lỗi cần xử lý."

## Slide 3 - User vào portal cần làm gì?

Tiêu đề: Luồng làm việc chính của user

Nội dung slide:

1. Vào "Xem thiết bị" để kiểm tra máy nào đang online.
2. Vào "Điều khiển & ghi thao tác" nếu cần thao tác trực tiếp hoặc ghi lại bước.
3. Vào "Thư viện kịch bản" để tạo, kiểm tra, chạy thử kịch bản.
4. Vào "Danh sách tài khoản" và "Nhóm tài khoản" để chuẩn bị account chạy.
5. Vào "Nhóm thiết bị" để gom máy theo mục tiêu vận hành.
6. Vào "Chiến dịch chạy" để dispatch kịch bản lên thiết bị.
7. Vào "Theo dõi" để xem tiến độ, ảnh lần chạy và lỗi cần xử lý.
8. Vào "Kết quả thu thập", "Thông báo", "Lịch sử hoạt động", "Phân tích" để đối soát sau chạy.

Script nói:

"Đây là slide quan trọng nhất. User không vào portal để xem một dashboard chung chung. Họ vào để trả lời: tôi có thiết bị chưa, có kịch bản chưa, có tài khoản chưa, chạy trên nhóm nào, chạy xong ra sao, và kết quả nằm ở đâu."

## Slide 4 - Màn hình thiết bị: biết máy nào dùng được

Tiêu đề: Bước đầu tiên là kiểm tra fleet thiết bị

Màn hình demo nên mở:

- `/dashboard/device-farm` - Xem thiết bị.
- `/dashboard/devices` - Quản trị thiết bị.
- `/dashboard/relay-agents` - Máy kết nối điện thoại, nếu muốn nói về máy relay.

Nội dung slide:

- Xem danh sách điện thoại đang online/offline.
- Kiểm tra máy nào có thể nhận lệnh.
- Xem màn hình thiết bị khi cần xác nhận trạng thái thực tế.
- Quản trị thiết bị và kết nối qua relay agent.

Script nói:

"Trước khi chạy bất kỳ automation nào, operator cần biết thiết bị nào thực sự sẵn sàng. Portal hiển thị trạng thái thiết bị và cho phép mở màn hình máy. Đây là lớp kiểm tra thực tế, vì hệ thống đang chạy trên điện thoại thật, không phải giả lập logic."

## Slide 5 - Điều khiển & ghi thao tác: biến thao tác tay thành kịch bản

Tiêu đề: Từ thao tác thủ công sang automation tái sử dụng

Màn hình demo nên mở:

- `/dashboard/device-farm/control`

Nội dung slide:

- Chọn thiết bị online.
- Điều khiển màn hình từ portal.
- Ghi lại thao tác thành các bước kịch bản.
- Dùng khi cần dựng mới một luồng hoặc debug một bước đang lỗi.

Script nói:

"Khi chưa có kịch bản, operator có thể mở điện thoại trong portal, thao tác trực tiếp và ghi lại. Điểm mạnh là thao tác thật trên máy thật được chuyển thành kịch bản để chạy lại nhiều lần hoặc gắn vào chiến dịch."

Demo gợi ý:

1. Mở màn hình control.
2. Chọn một serial thiết bị.
3. Thực hiện một thao tác đơn giản như mở app, tap, nhập text hoặc kéo màn hình.
4. Nói rõ: "Phần này giúp user dựng hoặc sửa kịch bản mà không phải viết code."

## Slide 6 - Thư viện kịch bản: chuẩn hóa việc cần chạy

Tiêu đề: Kịch bản là tài sản vận hành

Màn hình demo nên mở:

- `/dashboard/org-scenarios`
- `/scenario-flow/org/<scenario_id>` nếu muốn demo flow editor.

Nội dung slide:

- Tạo kịch bản mới hoặc sao chép mẫu hệ thống.
- Nhập/xuất kịch bản bằng YAML/JSON.
- Kiểm tra kịch bản trước khi chạy.
- Chạy thử trên một thiết bị để giảm rủi ro trước khi dispatch rộng.

Script nói:

"Kịch bản là nơi chuẩn hóa quy trình. Thay vì mỗi người làm mỗi kiểu, tổ chức có thư viện kịch bản chung. Một kịch bản có thể là đăng nhập, crawl dữ liệu, mở bài viết, lấy bình luận, hoặc một flow kiểm thử app."

Điểm cần nhấn:

- "Chạy thử" dùng thiết bị thật.
- Preview không phải sandbox tuyệt đối: nếu kịch bản có hành động thật như post/comment thì vẫn có side effect, nên phải dùng tài khoản test hoặc bật force có chủ ý.

## Slide 7 - Tài khoản và nhóm: chuẩn bị input cho chiến dịch

Tiêu đề: Automation cần biết dùng account nào và chạy trên máy nào

Màn hình demo nên mở:

- `/dashboard/accounts`
- `/dashboard/device-farm/account-groups`
- `/dashboard/device-groups`

Nội dung slide:

- Danh sách tài khoản theo nền tảng: Facebook, Instagram, TikTok, LinkedIn.
- Trạng thái tài khoản: hoạt động, cooldown, tạm khóa, đã cấm.
- Nhóm tài khoản để xoay vòng khi chạy nhiều thiết bị.
- Nhóm thiết bị để chọn đúng fleet mục tiêu.

Script nói:

"Một chiến dịch không chỉ là kịch bản. Nó còn cần input: account nào được dùng, nhóm account nào xoay vòng, và nhóm thiết bị nào sẽ chạy. Portal tách rõ phần chuẩn bị này để khi bấm chạy, operator không phải cấu hình lại từ đầu."

## Slide 8 - Chiến dịch chạy: dispatch công việc lên nhiều thiết bị

Tiêu đề: Từ một kịch bản thành nhiều lượt chạy có kiểm soát

Màn hình demo nên mở:

- `/dashboard/campaigns`

Nội dung slide:

- Tạo chiến dịch từ kịch bản đã sẵn sàng.
- Chọn nhóm thiết bị hoặc thiết bị cụ thể.
- Gắn tài khoản hoặc nhóm tài khoản.
- Chọn chạy song song hoặc tuần tự.
- Có thể tạm dừng, tiếp tục hoặc hủy luồng chạy.

Script nói:

"Chiến dịch là lúc user biến kịch bản thành công việc thật. Một chiến dịch có thể chạy trên một máy để kiểm thử, hoặc chạy trên nhiều thiết bị để tăng throughput. Portal cho user biết chiến dịch đang nháp, đang chạy, tạm dừng, hoàn thành hay thất bại."

Demo gợi ý:

1. Mở danh sách chiến dịch.
2. Chỉ vào nút tạo chiến dịch.
3. Chỉ vào phần chọn kịch bản, nhóm thiết bị, gắn tài khoản.
4. Nhấn mạnh: "Đây là nơi operator ra quyết định vận hành."

## Slide 9 - Theo dõi chiến dịch: biết lỗi ở đâu và xử lý thế nào

Tiêu đề: Không chỉ chạy tự động, mà còn có quy trình xử lý lỗi

Màn hình demo nên mở:

- `/dashboard/campaigns/<campaign_id>/monitor`

Nội dung slide:

- Xem workflow từng thiết bị.
- Xem ảnh lần chạy để biết thiết bị đã làm gì.
- Xem "Lỗi cần xử lý" khi retry tự động đã hết.
- Retry từ checkpoint, chạy lại từ đầu, đóng lỗi có lý do, hoặc bỏ qua.
- Tạm dừng, tiếp tục, hủy workflow khi cần.

Script nói:

"Điểm khác biệt lớn là khi lỗi xảy ra, user không bị bỏ mặc với log kỹ thuật. Portal đưa lỗi vào hàng đợi cần xử lý. Operator có thể xem thiết bị nào lỗi, lỗi ở bước nào, có ảnh chụp không, rồi quyết định retry từ checkpoint, chạy lại từ đầu hoặc đóng lỗi nếu đó là bug của kịch bản."

Quy tắc nói đơn giản:

- Lỗi tạm thời hoặc thiết bị mất mạng: retry từ checkpoint.
- UI app thay đổi hoặc trạng thái màn hình không chắc: chạy lại từ đầu.
- Kịch bản sai logic: đóng lỗi và ghi lý do.
- Nhiều máy lỗi giống nhau: xem một lỗi trước, sau đó bulk retry.

## Slide 10 - Kết quả và đối soát sau khi chạy

Tiêu đề: Sau khi chạy, user có dữ liệu, bằng chứng và audit

Màn hình demo nên mở:

- `/dashboard/content`
- `/dashboard/notifications`
- `/dashboard/activity-history`
- `/dashboard/analytics`

Nội dung slide:

- "Kết quả thu thập": dữ liệu/content/artifact sau mỗi lần chạy.
- "Thông báo": cảnh báo thiết bị, campaign, lịch chạy, lỗi.
- "Lịch sử hoạt động": ai làm gì, lúc nào, trên thiết bị/campaign nào.
- "Phân tích": tổng quan hiệu quả, tỷ lệ thành công/thất bại, xuất báo cáo/audit.

Script nói:

"Khi chiến dịch xong, công việc chưa kết thúc. User cần kiểm tra dữ liệu đã thu, xem cảnh báo, đối soát lịch sử thao tác và nhìn tỷ lệ thành công. Đây là phần giúp vận hành có trách nhiệm: có bằng chứng, có audit, có số liệu."

## Slide 11 - Quản trị: phân quyền, tổ chức, hạ tầng

Tiêu đề: Portal hỗ trợ nhiều vai trò, không phải ai cũng thấy mọi thứ

Màn hình demo nên mở:

- `/dashboard/settings/organization`
- `/dashboard/settings/organization/members`
- `/dashboard/settings/mcp`

Nội dung slide:

- Tổ chức và thành viên.
- Phân quyền theo vai trò và quyền thao tác.
- Relay agents để kết nối máy có ADB tới backend.
- MCP tokens cho tác nhân AI khi cần tích hợp automation.

Script nói:

"Phần quản trị dành cho admin hoặc lead. Operator tập trung vào thiết bị, kịch bản, chiến dịch và kết quả. Admin quản lý thành viên, quyền, máy relay và token MCP. Nhờ vậy portal có thể dùng trong tổ chức thật, không chỉ là tool local."

## Slide 12 - Tổng kết

Tiêu đề: Device Farm Portal là hệ điều hành vận hành điện thoại thật

Nội dung slide:

- Thiết bị thật: xem, điều khiển, kiểm tra trạng thái.
- Kịch bản: chuẩn hóa thao tác.
- Chiến dịch: chạy trên nhiều thiết bị.
- Monitor: theo dõi tiến độ và xử lý lỗi.
- Kết quả: dữ liệu, ảnh, thông báo, audit, phân tích.

Script nói:

"Nếu tóm gọn trong một câu: user vào Device Farm Portal để biến các thao tác trên điện thoại thật thành một quy trình vận hành có thể chạy lại, theo dõi được, xử lý lỗi được và kiểm chứng được."

## Flow demo 7 phút

Dùng flow này nếu bạn phải demo live thay vì chỉ nói slide.

### Phút 0-1: Mở vấn đề

Nói:

"Tôi sẽ demo theo vai trò operator. Operator không quan tâm đầu tiên đến backend chạy thế nào; họ quan tâm hôm nay có máy nào dùng được, cần chạy kịch bản nào, và kết quả ra sao."

### Phút 1-2: Kiểm tra thiết bị

Mở:

- `/dashboard/device-farm`

Nói:

"Đây là fleet điện thoại. Trước khi chạy, tôi kiểm tra máy nào online, máy nào đang bận hoặc offline. Nếu cần, tôi mở màn hình thiết bị để xác nhận trạng thái thật."

### Phút 2-3: Dựng hoặc sửa kịch bản

Mở:

- `/dashboard/device-farm/control`
- `/dashboard/org-scenarios`

Nói:

"Nếu chưa có kịch bản, tôi có thể điều khiển và ghi thao tác. Nếu đã có kịch bản, tôi vào thư viện để kiểm tra, chỉnh sửa, validate hoặc chạy thử trên một máy."

### Phút 3-4: Chuẩn bị tài nguyên

Mở:

- `/dashboard/accounts`
- `/dashboard/device-farm/account-groups`
- `/dashboard/device-groups`

Nói:

"Automation cần tài khoản và thiết bị mục tiêu. Portal cho phép quản lý account theo trạng thái, gom account thành nhóm xoay vòng và gom thiết bị thành nhóm chạy."

### Phút 4-5: Tạo và chạy chiến dịch

Mở:

- `/dashboard/campaigns`

Nói:

"Ở màn chiến dịch, tôi chọn kịch bản, chọn thiết bị hoặc nhóm thiết bị, gắn tài khoản, rồi dispatch. Có thể chạy song song để tăng tốc hoặc tuần tự nếu cần kiểm soát."

### Phút 5-6: Theo dõi và xử lý lỗi

Mở:

- `/dashboard/campaigns/<campaign_id>/monitor`

Nói:

"Khi chạy, tôi theo dõi từng workflow thiết bị. Nếu lỗi sau retry tự động, lỗi vào khu vực cần xử lý. Tôi xem ảnh, xem bước lỗi và chọn retry checkpoint, chạy lại từ đầu hoặc đóng lỗi có lý do."

### Phút 6-7: Kiểm tra kết quả

Mở:

- `/dashboard/content`
- `/dashboard/notifications`
- `/dashboard/activity-history`
- `/dashboard/analytics`

Nói:

"Cuối cùng, tôi xem dữ liệu thu thập, thông báo, lịch sử hoạt động và phân tích tỷ lệ thành công. Như vậy sau mỗi lần chạy, hệ thống có bằng chứng và số liệu để đối soát."

## Câu trả lời nhanh cho câu hỏi "user vào portal làm gì?"

User vào portal để:

1. Xem điện thoại nào đang sẵn sàng.
2. Điều khiển hoặc ghi thao tác trên điện thoại thật.
3. Tạo và kiểm tra kịch bản automation.
4. Chuẩn bị tài khoản, nhóm tài khoản, nhóm thiết bị.
5. Chạy chiến dịch trên một hoặc nhiều thiết bị.
6. Theo dõi tiến độ và xử lý lỗi.
7. Xem kết quả thu thập, ảnh bằng chứng, thông báo, audit và phân tích.

Nếu chỉ được nói một câu:

> User vào portal để vận hành nhiều điện thoại Android thật như một hệ thống: chuẩn bị kịch bản, chạy chiến dịch, theo dõi lỗi và kiểm chứng kết quả.

## Những điểm không nên nói quá sâu khi thuyết trình cho user

Không nên mở đầu bằng:

- Temporal, Redis, Postgres, gRPC.
- Chi tiết WebSocket, scrcpy, uiautomator2.
- MCP JSON-RPC, token internals.
- Schema database hoặc API routes.

Chỉ nhắc kỹ thuật khi người nghe hỏi. Cách nói ngắn:

"Phía sau portal có backend, relay agent và thiết bị Android thật. Nhưng với user, các khái niệm chính chỉ là thiết bị, kịch bản, chiến dịch, lỗi cần xử lý và kết quả."

## Mapping màn hình portal sang ý nghĩa user

| Màn hình | User hiểu là | Dùng khi |
|---|---|---|
| Xem thiết bị | Danh sách điện thoại thật | Kiểm tra máy online/offline |
| Điều khiển & ghi thao tác | Remote control + ghi bước | Dựng kịch bản hoặc debug |
| Thư viện kịch bản | Kho quy trình tự động | Tạo, nhập, validate, chạy thử |
| Danh sách tài khoản | Account chạy automation | Kiểm tra trạng thái account |
| Nhóm tài khoản | Pool account xoay vòng | Chạy nhiều máy/many accounts |
| Nhóm thiết bị | Fleet mục tiêu | Chọn nhóm máy cho campaign |
| Chiến dịch chạy | Job vận hành | Dispatch kịch bản lên thiết bị |
| Monitor campaign | Phòng điều khiển chiến dịch | Theo dõi, pause/resume/cancel, xử lý DLQ |
| Kết quả thu thập | Output và bằng chứng | Xem dữ liệu sau chạy |
| Thông báo | Cảnh báo vận hành | Biết sự cố/campaign xong |
| Lịch sử hoạt động | Audit ai làm gì | Đối soát thao tác |
| Phân tích | Số liệu hiệu quả | Xem success rate, export báo cáo |
| Settings/MCP | Quản trị và tích hợp AI | Admin tạo token/tổ chức/quyền |

## Kết bài gợi ý

"Điểm tôi muốn mọi người nhớ là Device Farm Portal không chỉ là màn hình xem thiết bị. Nó là quy trình vận hành hoàn chỉnh: từ chuẩn bị tài nguyên, tạo kịch bản, chạy chiến dịch, xử lý lỗi, đến kiểm chứng kết quả. Nhờ vậy team có thể mở rộng số lượng điện thoại mà vẫn giữ được kiểm soát, audit và chất lượng dữ liệu."
