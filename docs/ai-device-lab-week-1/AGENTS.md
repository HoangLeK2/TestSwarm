# AI Device Lab — chỉ dẫn bắt buộc cho agent triển khai

- Đọc `PRODUCTION-CONTRACT.md`, `README.md` và task ADL đang nhận trước implement.
- Scope là **PRODUCTION đầy đủ**. Không tự gọi MVP/alpha hoặc hoãn tính năng vì target một tuần.
- Task một máy/prototype là gate kiểm chứng riêng; tất cả chức năng production còn lại vẫn bắt buộc. Đọc DELIVERY-REGISTER để phân biệt contract dependency với integration gate.
- Mỗi task một file; giữ acceptance/test/review, chỉ đánh DONE khi có evidence thực. Mock, manual fallback và sandbox không tự đáp ứng production release gate.
- Task thiếu dependency/input/capacity phải BLOCKED và ghi owner/reason; không bỏ requirement hoặc hạ test để đúng deadline.
- G1 functional candidate, G2 kiểm chứng 14 ngày, G3 launch là ba gate riêng. Google approval không do hệ thống này quyết định.
- Áp dụng impact/api_impact trước sửa code/routes theo AGENTS repo; không coi graph stale là proof an toàn; không đụng thay đổi migration người khác khi chưa xác nhận ownership.
