# atxserver2 (openatx) — Tham chiếu kỹ thuật & map với Device Farmer

**PRD cùng format Maestro:** [docs/prd/atxserver2-prd-v1.0.md](prd/atxserver2-prd-v1.0.md)

Nguồn: [atxserver2](https://github.com/openatx/atxserver2), `README.md`, `API.md`.

---

## 1. Trạng thái dự án (quan trọng)

README ghi rõ: **「项目已经不开发了。请选择别的平台吧。」** — coi như **không còn phát triển tích cực**; vẫn có chỉnh nhỏ (ví dụ 2026/3/23 đổi hướng dẫn chạy sang `uv run main.py`).

**License:** [MIT](https://github.com/openatx/atxserver2/blob/master/LICENSE) — khác GADS (AGPL + hub-ui proprietary).

Khi chọn nền tảng fleet mới, ưu tiên giải pháp đang maintain (GADS, STF fork, tự host Device Farmer, v.v.).

---

## 2. Kiến trúc

| Thành phần | Vai trò |
|------------|---------|
| **atxserver2** (repo này) | Web + REST API: user, danh sách thiết bị, **chiếm / giải phóng** máy, upload APK; **Tornado** + async |
| **RethinkDB** | DB mặc định (`localhost:28015`, đổi qua env `RDB_*`) |
| **atxserver2-android-provider** | Repo riêng: Python 3.6+ + **Node.js**; Docker image `codeskyblue/atxserver2-android-provider`; đẩy lên máy: **atx-uiautomator.apk, minicap, minitouch, atx-agent** |
| **atxserver2-ios-provider** | Repo riêng — xem README |

Triển khai: `docker-compose up` hoặc `uv run main.py` sau khi có RethinkDB.

Auth server: `--auth simple` (email), `openid`, `github` (cần cấu hình `settings.py`).

---

## 3. “Node” / automation thực tế

**atxserver2 không có DSL kịch bản** (không có `repeat` / `if` trong server).

Luồng điển hình:

1. UI web: remote control (README có GIF), chuột: **right-click = BACK**, **middle-click = HOME**.
2. Sau khi **POST chiếm thiết bị**, `GET /api/v1/user/devices/{UDID}` trả **`source`** — đây là chỗ nối automation:

### Android `source` (trích API)

| Field | Mục đích |
|-------|----------|
| `url` | URL **provider** — cold device, **cài APK** qua `POST $PROVIDER_URL/app/install?udid=...` |
| `atxAgentAddress` | **[uiautomator2](https://github.com/openatx/uiautomator2)** (HTTP tới atx-agent) |
| `remoteConnectAddress` | **`adb connect`** tới máy ảo hóa ADB qua mạng |
| `whatsInputAddress` | IME từ xa (WhatsInput) |
| `secret` | Dùng kết hợp với agent |

### iOS `source`

| Field | Mục đích |
|-------|----------|
| `url` | Provider (cài IPA tương tự APK) |
| `wdaUrl` | **WebDriverAgent** HTTP, ví dụ `http://host:9300` |
| Stream | WebSocket `${wdaUrl}/screen` — luồng ảnh màn hình |

**Loop / if / capture:**

- **Loop / if:** viết trong **Python uiautomator2** hoặc test framework khác — không có trong atxserver2.
- **Capture:** screenshot / dump hierarchy qua **u2** hoặc WDA — không phải “step type” của server.

**Node.js:** bắt buộc ở **android-provider** (stack deploy), không phải runtime chính của script test — test mẫu trong repo dùng **Python + uiautomator2** (`examples/android_test.py`).

---

## 4. REST API (khái niệm chính)

Tham khảo OpenSTF: [STF API](https://github.com/openstf/stf/blob/master/doc/API.md).

- Auth: `Authorization: Bearer <token>` (lấy tại `/user`).
- `GET /api/v1/devices` — filter `?platform=apple&usable=true`.
- `POST /api/v1/user/devices` — body `{ "udid", "idleTimeout"? }`; admin có thể gửi `email` để chiếm hộ.
- `GET /api/v1/user/devices/{UDID}/active` — refresh thời gian hoạt động (tránh auto-release).
- `DELETE /api/v1/user/devices/{UDID}` — trả máy.
- `POST /uploads` — upload APK (một phần ghi TODO trong doc).

Chi tiết: [API.md](https://github.com/openatx/atxserver2/blob/master/API.md).

---

## 5. Private / multi-tenant nhẹ

`atxserver2-android-provider`: `--owner=group` hoặc `--owner=email` — gán máy cho nhóm/cá nhân (Beta, README nói chỉ Android).

Quản lý group/token qua UI (thiếu “group member management” đầy đủ theo README).

---

## 6. So sánh nhanh với Device Farmer stack

| Khía cạnh | atxserver2 | Device Farmer (repo này) |
|-----------|------------|---------------------------|
| Automation UI | **uiautomator2** qua `atxAgentAddress` | Executor Python + **uiautomator2** trực tiếp trên worker — **cùng họ openatx** |
| Kịch bản khai báo | Không | `scenario.steps` JSON (`tap_selector`, `wait_element`, … + DF-002 sau này) |
| DB | RethinkDB | (stack DF — thường SQL/Postgres trong PRD) |
| Trạng thái | Ngừng phát triển chính | Active internal |

**Ý nghĩa:** ý tưởng **đặt chỗ máy → lấy endpoint u2** rất giống hướng “worker nhận serial và chạy scenario”; atxserver2 là **portal + reservation**, không thay schema scenario.

---

## 7. Khả thi thiết bị / host

- **Android:** provider Docker/USB — nền tảng chính được doc hóa.
- **iOS:** provider riêng + WDA URL; cần follow repo ios-provider.
- **TV / đặc thù khác:** không thấy trong README chính (khác GADS có Tizen/WebOS).

---

## 8. Tài liệu & repo liên quan

- [atxserver2](https://github.com/openatx/atxserver2)
- [API.md](https://github.com/openatx/atxserver2/blob/master/API.md)
- [atxserver2-android-provider](https://github.com/openatx/atxserver2-android-provider)
- [atxserver2-ios-provider](https://github.com/openatx/atxserver2-ios-provider)
- [uiautomator2](https://github.com/openatx/uiautomator2)

Tham chiếu song song với device farm khác: [gads-reference-and-scenario-mapping.md](./gads-reference-and-scenario-mapping.md), [stf-reference-and-scenario-mapping.md](./stf-reference-and-scenario-mapping.md) (API reservation tham chiếu [STF API](https://github.com/openstf/stf/blob/master/doc/API.md)).

---

*Tài liệu tổng hợp từ README/API công khai; hành vi có thể lệch nếu fork hoặc patch riêng.*
