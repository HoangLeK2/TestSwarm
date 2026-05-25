# Soạn kịch bản (ghi record và editor)

Tài liệu bổ sung cho `device-farm-features-overview.md`.

## Cách 1 — Ghi thao tác (record)

1. Mở trang **Điều khiển và ghi thao tác** (Control Record). Trong ứng dụng web, đường dẫn thường là phần `device-farm` rồi `control` dưới `dashboard` (có thể vào từ lưới thiết bị qua mục điều khiển một máy).
2. Chọn thiết bị đang online. Bật chế độ **Ghi** (Recording): mỗi lần chạm, vuốt hoặc gõ trên luồng màn hình được thêm vào danh sách như **một bước** của kịch bản. Bạn có thể chỉnh sửa từng bước sau khi ghi.
3. Chọn **Lưu**: chỉ định chiến dịch, rồi **cập nhật một scenario đã có** hoặc **tạo scenario mới** trong chiến dịch đó (biến và nhóm tài khoản tùy hộp thoại). Nếu các bước còn ảnh minh hoạ đang xử lý, giao diện có thể yêu cầu chờ trước khi gửi lưu.
4. Để **sửa tiếp** kịch bản đã lưu, mở lại Control Record từ trang chi tiết chiến dịch (liên kết chỉnh sửa scenario); URL thường kèm mã chiến dịch và mã scenario.

## Cách 2 — Soạn trong chiến dịch (editor)

1. Vào **Chiến dịch** (trang danh sách campaign dưới `dashboard`), mở một chiến dịch.
2. Thêm hoặc mở **scenario**: có tên, phần *instructions* (ghi chú cho người đọc, không bắt buộc khi máy thực thi), và danh sách **steps**.
3. Trong editor, thêm bước và chọn **loại** (`type`): chờ, chạm, vuốt, mở ứng dụng, đọc hoặc trích UI, lặp, rẽ nhánh, gọi kịch bản con (`run_scenario`), v.v. Các ô chữ có thể dùng biến dạng `${TEN_BIEN}`.
4. Có thể xuất phát từ **mẫu** (trang scenario-templates dưới `dashboard`), rồi chỉnh biến và đưa vào chiến dịch.
5. Gán **thiết bị** hoặc **nhóm thiết bị** (target group) cho chiến dịch trước khi chạy.

## Ghi chú

- Không có bước tự động sinh kịch bản bằng mô hình ngôn ngữ trong luồng sản phẩm hiện tại; phần *instructions* chỉ là tài liệu cho người.
