# Báo cáo sửa popup trong kịch bản đăng nhập Facebook

- Thời gian kiểm tra: 29/09/2026 (Asia/Ho_Chi_Minh)
- Môi trường: production `greencloud-sing`
- Workspace: Hoang le's Workspace
- Thiết bị xác minh: P12 (`ce031713b1cf44010c`)
- Kịch bản: Đăng nhập Facebook (Account Login)

## Hiện tượng

Kịch bản mở Facebook nhưng không đóng được bottom sheet của Google Password Manager có tiêu đề:

`Sign in to Facebook with your saved password`

Các lần chạy trước ghi nhận bước `dismiss_popup` đóng `0 popup`, sau đó luồng không tìm thấy màn hình đăng nhập Facebook.

## Nguyên nhân

Hierarchy thật trên P12 cho thấy nút X có các thuộc tính:

- `resource-id="com.google.android.gms:id/cancel"`
- `content-desc="Cancel"`
- class `android.widget.ImageView`

Runtime đã nhận diện đúng tiêu đề popup nhưng danh sách nhãn đóng chỉ có `Close`, `Dismiss` và `×`. Vì thiếu nhãn chính xác `Cancel`, runtime từ chối tap để tránh nhấn nhầm.

## Thay đổi local

- Bổ sung token chính xác `cancel` vào tập nhãn đóng dành riêng cho popup Google Saved Password.
- Vẫn yêu cầu đúng tiêu đề popup và đúng một ứng viên nút đóng trước khi tap.
- Thêm regression test dùng hierarchy được lấy từ P12.

File thay đổi:

- `device_farm/tasks/scenario/utils.py`
- `device_farm/db/seeds/scenario_templates.py`
- `device_farm/tests/test_dismiss_popup_stale_cache.py`
- `device_farm/tests/test_fb_login_popup_guard.py`

Kết quả kiểm thử:

- Test hierarchy thật thất bại trước sửa: `_auto_dismiss_popup(...)` trả `False`.
- Sau sửa: `tests/test_dismiss_popup_stale_cache.py` — 8 passed.
- Guard đăng nhập Facebook: `tests/test_fb_login_popup_guard.py` — 12 passed.
- `git diff --check` — passed.
- GitNexus `detect-changes` — 4 file, 3 symbol, 0 execution flow bị ánh xạ, mức rủi ro `low`.

## Triển khai production

Backend `farm` được dựng lại từ đúng image đang chạy, với matcher runtime đã sửa. Org scenario của workspace được cập nhật riêng trong DB để đưa Facebook về foreground sau khi đóng popup và trước session gate.

- Image cũ: `sha256:745f7a709937564a3fdb3651c7398765cffc6cbdcc403f1fceb786460408e6b2`
- Image mới: `sha256:400eb84fb60bccdb6921a43cb90145e966cea653030f805fa4702dfb6449d720`
- Rollback tag: `device-farm/farm:rollback-google-saved-password-20260929T115433Z`
- Backup: `/srv/device-farm/backups/google-saved-password-cancel-20260929T115433Z`

- Org scenario: `d7cc811d-ddb1-494f-a48b-d6077e51e359`
- Version: 1 → 2
- Bước mới: `facebook_preflight_relaunch`
- Thứ tự: `facebook_preflight_popups` → `facebook_preflight_relaunch` → `facebook_session_preflight`
- Backup DB trước/sau nằm trong thư mục backup nêu trên.

## Xác minh production

Lần chạy lại trên P12:

- Execution: `c2e3a63b-b78d-433f-809f-7b7b45b4ec00`
- Bước `facebook_dismiss_popups`: `dismiss_popup: dismissed 1 popup(s)`.
- Runtime log: `Google saved-password popup dismissed: content-desc='Cancel'`.
- Năm lượt dismiss tiếp theo đều đóng `0 popup`, xác nhận popup đã biến mất và không bị nhận diện lặp.

Kết luận cho lỗi được yêu cầu: **đã sửa và đã xác minh trên thiết bị thật**.

## Trạng thái tại lần xác minh popup Google đầu tiên

Sau khi đóng popup, kịch bản dừng ở bước kế tiếp:

`platform_session_gate preflight blocked: facebook_package_not_visible`

Vì vậy lần chạy này chưa hoàn tất đăng nhập Facebook. Sau lần chạy đó, org scenario đã được bổ sung bước đưa Facebook về foreground và cập nhật lên version 2. Kết quả chạy hoàn chỉnh mới nhất được ghi ở phần “Chạy xác minh sau triển khai” bên dưới.

## Sự cố cấu hình phát hiện khi restart

Lần recreate đầu tiên làm lộ drift giữa `DB_PASSWORD` trong `/srv/device-farm/deploy.env` và mật khẩu của PostgreSQL đang chạy, khiến API trả `503`. Giá trị đã được đồng bộ lại từ chính container PostgreSQL mà không in hoặc đưa secret ra ngoài server.

- Backup cấu hình trước sửa: `/srv/device-farm/backups/google-saved-password-cancel-20260929T115433Z/deploy.env.before-db-repair`
- Sau khôi phục: backend `running/healthy`; `/api/devices` không token trả `401` thay vì `503`.

## Bổ sung: popup “Dừng thiết lập trang cá nhân”

### Hiện tượng

Sau khi đăng nhập thành công, Facebook có thể mở màn hình `Tiếp tục thiết lập trang cá nhân`. Bước đọc profile không tìm thấy dữ liệu, chờ khoảng 10,7 giây rồi bấm Back. Facebook lúc đó hiện dialog:

`Dừng thiết lập trang cá nhân của bạn?`

Kịch bản kết thúc ngay sau thao tác Back nên dialog vẫn còn trên màn hình.

### Thay đổi

- Runtime chỉ bấm `DỪNG` khi hierarchy đồng thời có đúng tiêu đề dialog nêu trên và chỉ có một nút `DỪNG` có thể bấm. Nhãn `DỪNG` không được đưa vào matcher popup chung.
- Kịch bản nhận diện màn hình `Tiếp tục thiết lập trang cá nhân`. Nếu dialog chưa mở, kịch bản bấm Back rồi dọn dialog; nếu dialog đã mở, kịch bản dọn trực tiếp.
- Khi gặp màn hình thiết lập, kịch bản bỏ qua bước đọc profile chắc chắn thất bại.
- Timeout mở profile giảm `4 → 2 giây`; nhánh dự phòng giảm `2 → 1 giây`; timeout đọc profile giảm `12 → 6 giây`.
- Dọn popup preflight giảm từ `5 × 1 giây` xuống `3 × 0,5 giây`.
- Dọn popup post-confirm giảm từ `8 × 1 giây` xuống `5 × 0,5 giây`; delay ban đầu giảm `1 → 0,5 giây`.

### Kiểm thử local

- Test đỏ xác nhận bản cũ không bấm được `DỪNG` trên hierarchy mô phỏng đúng màn hình người dùng cung cấp.
- Có guard xác nhận nút `DỪNG` đứng một mình, không có đúng tiêu đề dialog, sẽ không bị bấm.
- Popup, login guard và graph compiler: **28 passed**.
- GitNexus không tìm thấy ba hàm private trong index nên trả `UNKNOWN`; kiểm tra thủ công giới hạn phạm vi ở matcher popup và template Facebook, không thay đổi engine `repeat` dùng chung.

### Triển khai production

- Backend image: `sha256:515d6c7626d106cff9c405d779e943e0de6c36b614b4b4ef0798c5465a817e00`
- Rollback tag: `device-farm/farm:rollback-profile-popup-20260929T124245Z`
- Backup: `/srv/device-farm/backups/facebook-profile-setup-popup-20260929T124245Z`
- Org scenario: `d7cc811d-ddb1-494f-a48b-d6077e51e359`
- Version hiện tại: **4**
- Body trong DB đã được so sánh semantic với artifact dự kiến: khớp; graph có 55 nodes và 33 edges.
- Backend sau recreate: `running/healthy`; `GET /api/health` trả `200`.

### Chạy xác minh sau triển khai

- Thiết bị: P10 (`244dd1c0bd1c7ece`)
- Execution: `71907092-e614-43cd-a5c0-db0c17578fb0`
- Trace: `scn-54971facdb`
- Kết quả: **success**, 10/10 bước cấp cao hoàn tất, tổng thời gian 24,3 giây.
- Preflight popup chạy 3 lượt trong 1,7 giây.
- Bước đọc profile hoàn tất trong khoảng 0,7 giây, so với khoảng 10,7 giây ở lần lỗi trước.

Lần xác minh này điện thoại không còn hiển thị màn hình thiết lập trang cá nhân, nên nhánh bấm `DỪNG` chưa được kích hoạt lại trên thiết bị thật. Nhánh đó đã qua regression test bằng hierarchy theo ảnh; cần lần chạy có đúng trạng thái màn hình này để có bằng chứng E2E trực tiếp.
