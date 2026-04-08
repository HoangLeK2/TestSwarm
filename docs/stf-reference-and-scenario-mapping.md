# OpenSTF / STF — Tham chiếu kỹ thuật & map với Device Farmer

**PRD đầy đủ:** [docs/prd/stf-prd-v1.0.md](prd/stf-prd-v1.0.md)

Nguồn: [openstf/stf](https://github.com/openstf/stf), `README.md`, [doc/API.md](https://github.com/openstf/stf/blob/master/doc/API.md).

---

## 1. STF là gì

**STF** (Smartphone Test Farm) là **ứng dụng web** điều khiển **thiết bị Android** (và smartwatch/gadget tương thích) **từ trình duyệt**: stream màn hình, nhập liệu, cài APK, shell, logcat, `adb connect` từ xa, booking/partitioning, REST API OAuth2.

**Không phải** engine kịch bản: không có `repeat` / `if` trong server — automation gắn qua **ADB sau remoteConnect** hoặc **[Appium + STF](https://github.com/openstf/stf-appium-example)** (ví dụ upstream).

---

## 2. Trạng thái dự án (quan trọng)

README **OpenSTF org** ghi:

- Các repo **không còn phát triển tích cực** trong tổ chức OpenSTF.
- Phát triển tiếp nằm ở **[DeviceFarmer](https://github.com/DeviceFarmer)** — xem fork đang maintain.
- Bản cuối OpenSTF trên Docker Hub: **3.4.2**; npm: **3.4.1**.

Khi triển khai mới: ưu tiên **DeviceFarmer fork** hoặc stack khác (GADS, atxserver2, tự build).

---

## 3. Kiến trúc & stack (rút gọn)

| Thành phần | Ghi chú |
|------------|---------|
| **Nhiều process Node** | Thường tách systemd unit; dev có `stf local` |
| **RethinkDB** | ≥ 2.2 |
| **ADB** | Bắt buộc; production khuyến nghị **Linux** (README: macOS ADB kém ổn định) |
| **Trên thiết bị** | minicap, minitouch, minirev, STFService (`jp.co.cyberagent.stf`), … |
| **Node** | README yêu cầu **Node 8.x** (cũ) — fork mới có thể đã nâng |

---

## 4. “Node” / automation

| Khái niệm | Thực tế trong STF |
|-----------|-------------------|
| Điều khiển tay | UI web (FPS ~30–40 tùy máy, minicap) |
| **remoteConnect** | `POST /api/v1/user/devices/{serial}/remoteConnect` → URL kiểu `host:port` → **`adb connect`** |
| Test tự động | Bất kỳ tool dùng ADB/Appium sau khi connect; có **swagger.json** + ví dụ Appium |
| Loop / if | **Không** — nằm ở script test / CI |

---

## 5. REST API (khớp atxserver2 / mindset Device Farmer)

- **OAuth2**: token ở UI → `Authorization: Bearer …`
- **GET** `/api/v1/devices`, `/api/v1/devices/{serial}`
- **POST** `/api/v1/user/devices` — body `{ serial, timeout? }` (ms) — “Use”
- **DELETE** `/api/v1/user/devices/{serial}` — “Stop using”
- **POST** `/api/v1/user/devices/{serial}/remoteConnect` — lấy `remoteConnectUrl` cho ADB
- **DELETE** `.../remoteConnect` — ngắt remote debug

Chi tiết + shell example: [doc/API.md](https://github.com/openstf/stf/blob/master/doc/API.md).

---

## 6. So với Device Farmer

| STF | Device Farmer (repo) |
|-----|----------------------|
| Tập trung **fleet + browser control** | Fleet + **scenario JSON** + uiautomator2 executor |
| Android lab kinh điển (OpenSTF) | Android automation có **record flow** riêng |
| API reserve giống ý tưởng atxserver2 (OpenSTF-inspired) | Có thể học **token + reserve + remote ADB** |

---

## 7. Bảo mật (đọc README)

Thiết kế giả định **mạng tin cậy**; giao tiếp nội bộ **không mã hóa** đầy đủ; thiết bị **không reset sạch** giữa session — **không** coi là multi-tenant hostile-safe mặc định.

---

## 8. Liên kết

- [STF repo](https://github.com/openstf/stf)
- [DeviceFarmer org](https://github.com/DeviceFarmer) (fork maintain)
- So sánh farm khác: [gads-reference-and-scenario-mapping.md](./gads-reference-and-scenario-mapping.md), [atxserver2-reference-and-scenario-mapping.md](./atxserver2-reference-and-scenario-mapping.md)
