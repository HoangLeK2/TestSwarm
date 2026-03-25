# Scenarios (kịch bản)

Các file JSON trong thư mục này là kịch bản mẫu cho campaign. Copy nội dung `scenario` vào campaign (API `PATCH /api/campaigns/{id}/scenario` hoặc giao diện "Kịch bản campaign") rồi chạy campaign.

## facebook_access.json

- **Mục đích:** Truy cập Facebook bằng `open_url` (mở link facebook.com → hệ thống mở app Facebook hoặc trình duyệt). Chờ 2s.
- **Lý do dùng open_url:** Không phụ thuộc package (com.facebook.katana / com.facebook.lite), thiết bị nào cũng mở được.

Cách dùng: mở campaign → Kịch bản → dán nội dung từ `facebook_access.json` (cả object: `instructions` + `steps`) → Lưu → Chạy campaign. Khi tất cả task xong, dashboard sẽ toast "Campaign đã chạy xong".
