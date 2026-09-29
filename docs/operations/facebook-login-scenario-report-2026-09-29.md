# Báo cáo lịch sử đăng nhập Facebook và chạy kịch bản

**Thời điểm chụp dữ liệu:** 17:08, ngày 29/09/2026 (UTC+7)  
**Nguồn:** production `greencloud-sing` / database `device_farm`  
**Phạm vi bằng chứng:** dữ liệu đã lưu trong PostgreSQL và trạng thái container. Không chạy kịch bản, không điều khiển phone, không đọc màn hình/hierarchy và không thay đổi server.

## Kết luận nhanh

- Có **114 execution đăng nhập** (`run_type=account_login`) cho **18 account** trên **16 phone** trong giai đoạn 16/09–29/09/2026.
- Kết quả tổng: **20 completed**, **85 failed**, **9 cancelled**.
- MH workspace có 73 execution: 9 completed, 55 failed, 9 cancelled. Hoang workspace có 41 execution: 11 completed, 30 failed.
- Có **15 execution đã đi qua trường mã xác thực/TOTP**; trong số đó **7 execution completed**. Việc có nhập mã không đồng nghĩa toàn bộ execution thành công.
- Có **1 account đang ở trạng thái `banned` do `facebook_account_locked`**, nhưng account này không có execution đăng nhập nào được lưu.
- Bảng `device_platform_login_attempts` hiện không có bản ghi. Lịch sử đăng nhập thực tế đang nằm trong `executions`, `execution_results` và `execution_steps`.

## Đối chiếu trực tiếp hai account trong mẫu

| Phone | Nhóm hiện tại | OS | VPN | Proxy | Root | Action before lock | Action đã lưu | Account | Challenge type | Facebook result |
|---|---|---:|---|---|---|---|---|---|---|---|
| P12 | crawl data | Chưa có dữ liệu | Chưa có dữ liệu | Không | Chưa có dữ liệu | Không có bằng chứng đã lưu | `login_if_needed` dừng vì không tìm thấy `password_field` | 61594350255855 | Chưa đến bước challenge | Failed lúc 15:32 29/09/2026 |
| — | — | — | Chưa có dữ liệu | Không | Chưa có dữ liệu | Không có bằng chứng đã lưu | Không có execution đăng nhập | 61594515849426 | Không có dữ liệu | Chưa có kết quả đăng nhập được lưu |

Điểm lệch so với mẫu thủ công: database hiện ghi account `61594350255855` được gán và chạy trên **P12**, không phải P7. Account `61594515849426` tồn tại nhưng đang `unassigned` và chưa có lịch sử chạy đăng nhập.

## Các lần đăng nhập gần nhất

| Thời gian | Phone | Account | Hành động/challenge quan sát được | Trạng thái execution | Kết quả chi tiết |
|---|---|---|---|---|---|
| 29/09 16:14 | MH2 | 61573952805721 | Chưa nhập thông tin; thiếu giá trị `account.password` | Failed | `if_variable: else branch failed`; nguyên nhân con là password chưa resolve |
| 29/09 16:13 | MH2 | 61573952805721 | Chưa nhập thông tin; thiếu giá trị `account.password` | Failed | Cùng nguyên nhân như lần 16:14 |
| 29/09 16:04 | P7 | Nhãn import “DỊCH VỤ: Acc Facebook Ngoại” | Không tìm thấy trường password | Failed | Chưa đi tới bước challenge |
| 29/09 15:32 | P12 | 61594350255855 | Không tìm thấy trường password | Failed | Chưa đi tới bước challenge |
| 28/09 09:32 | MH17 | 61577641716334 | Preflight dừng trước thao tác login | Failed | Facebook có vẻ ready nhưng provenance không khớp account |
| 28/09 09:30 | MH12 | 100094133661105 | Preflight dừng trước thao tác login | Failed | Facebook có vẻ ready nhưng provenance không khớp account |
| 28/09 09:28 | MH12 | 100094133661105 | Đã submit login và nhập mã xác thực/TOTP | Failed | Sau xử lý vẫn còn màn hình login (`login_surface_visible`) |
| 28/09 09:20 | MH12 | 100094133661105 | Đã submit login, nhập mã xác thực/TOTP và gate xác nhận login thành công | Cancelled | Facebook login đã được xác nhận, nhưng execution bị người dùng hủy ở step 6 |
| 28/09 09:17 | MH12 | 100094133661105 | Đã submit login và nhập mã xác thực/TOTP | Cancelled | Bị hủy trong vòng lặp trước khi có xác nhận cuối |
| 28/09 09:17 | MH12 | 100094133661105 | Preflight dừng trước thao tác login | Failed | Facebook có vẻ ready nhưng provenance không khớp account |

Execution ID của bốn lỗi mới nhất:

- MH2 16:14: `cfee6826-a3e4-4bcb-9de9-1ac93eeb9a1b`
- MH2 16:13: `a2d8aff0-60db-4553-be9f-b6eb6d90d456`
- P7 16:04: `0b2e7166-8d89-490c-b12b-f1cd26c48849`
- P12 15:32: `6e07fc22-fec9-4534-be29-e322f48fd745`

## Tổng hợp theo account

Quy ước `C/F/X`: completed / failed / cancelled. Cột TOTP là số execution đã nhập mã / số execution completed sau khi nhập mã.

| Workspace | Phone | OS | Nhóm hiện tại | Account | C/F/X | TOTP | Trạng thái account hiện tại | Kết quả gần nhất |
|---|---|---:|---|---|---:|---:|---|---|
| MH | MH2 | — | — | 61573952805721 | 0/2/0 | 0/0 | assigned | Failed: thiếu `account.password` |
| Hoang | P7 | — | crawl data | Nhãn import “DỊCH VỤ: Acc Facebook Ngoại” | 0/1/0 | 0/0 | assigned | Failed: không tìm thấy `password_field` |
| Hoang | P12 | — | crawl data | 61594350255855 | 0/1/0 | 0/0 | assigned | Failed: không tìm thấy `password_field` |
| MH | MH12, MH17 | 9 | — | 61577641716334 | 1/6/3 | 3/1 | assigned | Failed: session/provenance không khớp |
| MH | MH12 | 9 | — | 100094133661105 | 0/3/3 | 4/0 | assigned, cần login | Failed: session/provenance không khớp |
| MH | MH4 | 12 | — | 100094389788226 | 3/0/0 | 2/2 | active, login confirmed | Completed |
| Hoang | MH14 | 9 | — | 61562229398839 | 3/7/0 | 1/1 | active | Completed |
| Hoang | MH10 | 9 | — | 61582693751453 | 0/9/0 | 0/0 | assigned, chưa có session verified | Failed: không đọc được hierarchy |
| Hoang | MH11 | 9 | — | 61580076957234 | 0/2/0 | 0/0 | assigned, chưa có session verified | Failed: session/provenance không khớp |
| Hoang | MH13 | 9 | — | 61593284826198 | 0/2/0 | 0/0 | assigned, chưa có session verified | Failed: session/provenance không khớp |
| Hoang | MH6 | — | — | 61582794091862 | 1/0/0 | 0/0 | active | Completed |
| Hoang | MH5 | 12 | — | 61562357428250 | 0/3/0 | 0/0 | assigned, chưa có session verified | Failed: session/provenance không khớp |
| Hoang | MH4 | 12 | — | 61581191995402 | 1/0/0 | 0/0 | active | Completed |
| Hoang | MH3 | 12 | — | 61583261069011 | 1/0/0 | 0/0 | active | Completed |
| Hoang | MH2 | — | — | 61577079665632 | 1/0/0 | 0/0 | active | Completed |
| Hoang | MH16 | 9 | — | 61565337765014 | 1/2/0 | 2/1 | hiện unassigned | Completed; account sau đó không còn gắn device |
| Hoang | MH15 | 9 | — | 61565972900499 | 1/3/0 | 2/1 | active | Completed |
| Hoang | MH1 | — | — | 61576271872104 | 2/0/0 | 1/1 | active | Completed |

Ngoài bảng trên, account `61586642714628` hiện là account duy nhất có trạng thái `banned` với lý do `facebook_account_locked` từ 00:51 ngày 15/09/2026. Account này không có execution `account_login`, vì vậy không thể kết luận hành động nào xảy ra trước khi bị khóa từ lịch sử execution.

## Lịch sử chạy kịch bản/campaign

### Tổng quan persisted runtime

| Loại run | Completed | Failed | Cancelled | DLQ open | Giai đoạn |
|---|---:|---:|---:|---:|---|
| `campaign_device` | 273 | 50 | 257 | 282 | 07/06–29/09/2026 |
| `campaign_run` (legacy) | 0 | 84 | 0 | 0 | 19/04–02/06/2026 |
| `preview` | 3 | 0 | 3 | 5 | 25/08–26/08/2026 |

### Hoạt động mới nhất

- 09:15 ngày 29/09: campaign **“Lướt random các bài newsfeed — chiến dịch”** completed trên P2, P3 và P18.
- 13:46 ngày 29/09: campaign **“Đăng bài Facebook rồi like/comment — chiến dịch”** trên MH17 chuyển sang `dlq_open`.
- DLQ mới nhất đang `pending`, retry count 0. Nguyên nhân đã lưu: sub-scenario không tìm thấy Facebook post candidate khớp keyword bắt buộc. Execution: `829eda0d-f37e-40ae-a42f-bc0d7b8ced59`.
- Campaign “Lướt random các bài newsfeed — chiến dịch” có tổng 43 run completed và 10 run `dlq_open` trong giai đoạn 17/09–29/09.

## Nhận định vận hành

1. `if_variable: else branch failed` chỉ là lỗi wrapper. Trong 61 execution mang lỗi này, cần đọc bước con mới thấy nguyên nhân thật như thiếu password, không tìm thấy locator, hoặc màn hình login vẫn còn sau submit.
2. Kết quả Facebook và kết quả execution cần tách riêng. Ví dụ execution 09:20 ngày 28/09 đã xác nhận Facebook login thành công nhưng trạng thái cuối của cả execution là `cancelled` vì bị hủy ở step 6.
3. `facebook_ready_without_matching_provenance` không chứng minh account mong muốn đã login. Nó chỉ cho biết app trông như đã sẵn sàng nhưng session không gắn đúng account đang chạy.
4. Không có bằng chứng persisted cho thao tác “xóa app” trong các execution đăng nhập. Chỉ có một số trace `stop_app`/`launch_app`; không nên ghi thành “xóa app”.
5. Không có dữ liệu để kết luận challenge “xác minh người thật” cho account `61594350255855`. Execution mới nhất dừng trước challenge vì không tìm thấy trường password.

## Giới hạn của báo cáo

- Phone name, nhóm, OS và proxy là trạng thái hiện tại trong database; hệ thống không lưu snapshot đầy đủ của các trường này tại thời điểm từng execution.
- Database chỉ lưu `accounts.proxy_id`; không có cột VPN hoặc Root. Các ô VPN/Root được để là “Chưa có dữ liệu”, không suy đoán thành “có/không”.
- Một số device chưa có `android_version`, gồm P7, P12, MH2 và MH6 trong các dòng liên quan.
- “Action before lock” không có trường sự kiện tương ứng. Không thể tái dựng chính xác nếu không có event/trace được lưu.
- Báo cáo này là bằng chứng persisted runtime trên production. Nó không chứng minh màn hình hiện tại của phone, không phải live-device E2E và không xác nhận bằng screenshot/hierarchy.
- Không sao chép password, TOTP secret/code, cookie, token, proxy credential, raw XML hoặc URL artifact vào báo cáo.

## Nhật ký kiểm tra an toàn

- Chỉ dùng `docker ps`, `docker compose ps` và các câu `SELECT` trong `BEGIN TRANSACTION READ ONLY` với `statement_timeout`; mọi transaction đều kết thúc bằng `ROLLBACK`.
- Không chạy scenario, không gọi API mutation, không `docker exec` vào backend để thực thi nghiệp vụ, không restart/recreate container, không thay đổi file/config/database trên server.
- Backend được quan sát ở trạng thái `healthy`; frontend, Redis, Temporal và PostgreSQL đều đang chạy tại thời điểm kiểm tra.
