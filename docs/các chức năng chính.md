# Giới thiệu hệ thống — dành cho người dùng

Tài liệu này mô tả **bạn có thể làm gì** với nền tảng quản lý và tự động hóa điện thoại Android (gọi tắt là *farm*).

---

## Hệ thống này dùng để làm gì?

Giúp tổ chức **quản nhiều điện thoại Android cùng lúc** trên một bảng điều khiển trên web: xem màn hình, điều khiển từ xa, chạy các thao tác lặp lại theo kịch bản, thu thập hoặc lưu nội dung, và theo dõi hoạt động — thay vì cầm từng máy và làm tay từng bước.

---

## Đăng nhập và làm việc theo tổ chức

- **Tài khoản cá nhân:** đăng ký, đăng nhập, đổi thông tin cơ bản.
- **Tổ chức (công ty / nhóm):** dữ liệu thiết bị, chiến dịch và báo cáo có thể được tách theo tổ chức để nhiều nhóm dùng chung một hệ thống mà không lẫn dữ liệu.
- **Nhóm tài khoản:** gom người dùng hoặc quyền theo nhóm khi tổ chức cần phân quyền rõ ràng.

---

## Thiết bị: xem, điều khiển, sắp xếp

- **Danh sách điện thoại:** trạng thái từng máy (online, đang bận, lỗi kết nối…).
- **Xem màn hình trực tiếp:** xem đang hiển thị gì trên điện thoại, thường dùng để giám sát hoặc hỗ trợ từ xa.
- **Điều khiển từ xa:** chạm, vuốt, gõ — tương tự cầm máy nhưng làm trên trình duyệt.
- **Nhóm thiết bị:** gom nhiều máy thành một nhóm để sau này chọn nhanh khi chạy chiến dịch hoặc lịch.

---

## Chiến dịch và kịch bản tự động

- **Kịch bản (scenario):** chuỗi bước cố định — ví dụ mở app, cuộn danh sách, chờ vài giây, chạm vào nút. Dùng để lặp lại công việc giống nhau trên một hoặc nhiều máy.
- **Mẫu kịch bản:** lưu kịch bản dùng lại nhiều lần, chỉnh sửa khi quy trình thay đổi.
- **Chiến dịch (campaign):** chọn kịch bản và chọn thiết bị (hoặc nhóm máy), rồi **chạy**; có thể theo dõi tiến độ, xem lần chạy thành công hay thất bại.

---

## Biến: global (chiến dịch), theo kịch bản, theo từng thiết bị

Tham số hóa bước bằng **`${TEN_BIEN}`** trong editor kịch bản. Thứ tự ưu tiên khi thay thế (cao → thấp):

1. **Runtime** — `set_variable`, kết quả extract, v.v. trong lúc chạy.
2. **Biến scenario** — mục *Biến / Variables* trên từng kịch bản.
3. **Biến campaign** — *global trong phạm vi chiến dịch* (chung mọi scenario/máy trừ khi bị ghi đè).
4. **Biến môi trường** — chỉ tên được admin cho phép (mặc định hạn chế, tránh lộ secret).
5. **Biến hệ thống** — `__DEVICE_SERIAL__`, `__DEVICE_MODEL__`, `__NOW__`, `__STEP_INDEX__`, … (menu *Chèn biến*).

**Theo từng thiết bị:** bật *ghi đè theo thiết bị* trên scenario và nhập key → value **per máy**; khi dispatch các giá trị này **ghi đè** biến trùng tên của kịch bản trên máy đó. Tài khoản nhóm / tài khoản chính có thể inject thêm `__ACCOUNT_*` (mật khẩu không đưa thẳng vào biến).

Chi tiết kỹ thuật: `docs/specs/DF-001-variable-system.md`.

---

## Tạo kịch bản

Xem thêm file device-farm-scenario-authoring.md trong folder docs.

Có hai cách chính trên web; kịch bản là **danh sách các bước (steps)** lưu trên server (tích hợp API thì gửi cùng cấu trúc đó).

1. Vào **Chiến dịch** và mở một campaign (đường dẫn /dashboard/campaigns).
2. Thêm **một hoặc nhiều scenario** trong campaign: mỗi kịch bản có tên, phần *instructions* (ghi chú mô tả cho người đọc), và danh sách **steps**.
3. Trong editor từng bước, chọn **loại bước** (`type`) — ví dụ chờ, chạm, vuốt, mở app, đọc/trích UI, lặp, rẽ nhánh, gọi kịch bản con (`run_scenario`). Các ô văn bản có thể ghi `${TEN_BIEN}`.
4. (Tuỳ chọn) Dùng **mẫu** tại `/dashboard/scenario-templates`, rồi điều chỉnh biến và gắn vào campaign.
5. Gán **thiết bị** từng máy hoặc chọn **nhóm thiết bị** (target group) cho campaign.

---

## Chạy kịch bản và nhiều scenario

- **Chạy campaign** tạo **execution**; engine Temporal dùng **một workflow trên mỗi thiết bị** trong đợt chạy.
- **Trên một máy:** các scenario chạy **tuần tự** theo **`order`** trong DB (xong A rồi B…), tránh hai kịch bản tranh một màn hình.
- **Nhiều máy:** mỗi máy một workflow → **song song** giữa các máy; trên từng máy vẫn tuần tự như trên.

---

## Lịch chạy và nhắc việc

- **Lên lịch:** chọn kịch bản hoặc chiến dịch chạy vào giờ cố định (ví dụ mỗi đêm kiểm tra báo cáo).
- **Lịch sử chạy:** xem đã chạy lúc nào, trên máy nào, kết quả ra sao — hữu ích khi cần đối soát hoặc kiểm tra lỗi.

---

## Nội dung, hình ảnh và dữ liệu thu được

- **Kho nội dung:** xem, tìm và quản lý các mục đã được hệ thống hoặc kịch bản thu thập/lưu (tùy cách tổ chức đặt tên và phân loại).
- **Thu thập từ giao diện ứng dụng:** hệ thống có thể hỗ trợ đọc cấu trúc màn hình, chữ trên màn hình hoặc bước “trích xuất” trong kịch bản — phục vụ báo cáo, kiểm duyệt hoặc tự động hóa nhập liệu (tùy kịch bản do đội ngũ cấu hình).
- **Ứng dụng mạng xã hội:** có thể có sẵn các luồng chuyên biệt cho một số nền tảng.

---

## Theo dõi hoạt động và thông báo

- **Nhật ký / hoạt động:** ai làm gì, máy nào tham gia — giúp minh bạch và xử lý sự cố.
- **Thông báo:** có thể nhận cảnh báo hoặc tin nhắn trong ứng dụng khi chiến dịch xong, có lỗi, hoặc khi có sự kiện quan trọng (tùy cài đặt).

---

## An toàn và quyền riêng tư (ở mức người dùng)

- Chỉ người có **tài khoản** mới vào được bảng điều khiển.
- Thiết bị và chiến dịch thường gắn với **tổ chức** của bạn để tránh lộ dữ liệu sang nhóm khác.
- Khi máy đang chạy tác vụ quan trọng, hệ thống có thể **tạm chặn** thao tác tay để tránh hai người cùng điều khiển một lúc gây lỗi (hiển thị rõ trên giao diện khi có).

---

## Khi cần hỗ trợ

- Các tính năng **bật/tắt** hoặc giới hạn (lưu trữ đám mây, số máy tối đa, tính năng thử nghiệm, …) do **quản trị viên** quyết định — nếu bạn không thấy một mục trên menu, có thể do chưa được cấp quyền hoặc chưa bật trên máy chủ.
- Sự cố kết nối, cáp, hoặc cài app trên điện thoại: nhờ **đội IT** kiểm tra phía hạ tầng và thiết bị vật lý.

---

*Tài liệu mô tả trải nghiệm người dùng; chi tiết kỹ thuật dành cho đội phát triển nằm ở tài liệu kiến trúc và mã nguồn nội bộ.*