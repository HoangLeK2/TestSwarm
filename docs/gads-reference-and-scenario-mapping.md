# GADS (shamanec/GADS) — Tham chiếu kỹ thuật & map với kịch bản Device Farmer

**PRD cùng format Maestro:** [docs/prd/gads-prd-v1.0.md](prd/gads-prd-v1.0.md)

Nguồn chính: [GADS trên GitHub](https://github.com/shamanec/GADS), README, `docs/hub.md`, `docs/provider.md`, `docs/appium-credentials.md`.

---

## 1. GADS là gì (và không phải gì)

**GADS** (Go) là **self-hosted device farm**: Hub (web + API) + **Provider** (máy chủ gắn thiết bị) + **MongoDB** (log, đồng bộ cấu hình). Mục tiêu: remote control thiết bị thật, chạy **Appium**, tùy chọn **Selenium Grid 4** hoặc **experimental grid** tích hợp trong Hub.

**Không phải** engine kịch bản dạng graph/JSON step như Device Farmer (`scenario.steps` với `tap`, `repeat`, `if_element`, …). GADS **không định nghĩa** “node” loop/if trong product; phần đó nằm ở **client test** (Java/TestNG, Python, WebdriverIO, …) hoặc thao tác **thủ công** qua UI Hub.

**License:** code mở chủ yếu **AGPL-3.0**; thư mục `hub-ui` **proprietary** (build obfuscated — không fork/sửa UI theo policy upstream). Cần lưu ý khi tích hợp sản phẩm thương mại.

---

## 2. Kiến trúc thành phần

| Thành phần | Vai trò |
|------------|---------|
| **Hub** | UI, auth (JWT, workspace), proxy tới provider, stream video, **endpoint Appium per-device** `http://hub:port/device/{device-id}/appium`, grid thử nghiệm tại `/grid` |
| **Provider** | Cài phụ thuộc theo OS; khởi chạy Appium từng máy (optional); **iOS** qua fork [WebDriverAgent](https://github.com/shamanec/WebDriverAgent) (MJPEG/WebRTC, endpoint tap/swipe tối ưu); **Android** ADB + UiAutomator2; **Tizen/WebOS** driver Appium riêng |
| **MongoDB** | Log provider/device, file upload (WDA ipa, Selenium jar, …) |

---

## 3. “Node” trong ngữ cảnh GADS — map sang hành động thực tế

Dưới đây là **các lớp primitive** tương đương ý tưởng “bước/node” automation, không phải DSL có tên trong repo.

### 3.1 Remote control (Hub → Provider, không bắt buộc Appium)

Theo README: stream **MJPEG / WebRTC**; tương tác **tap, swipe, nhập text, clipboard, gõ phím**; **cài/gỡ app**; **screenshot**; **đặt chỗ (reservation)** thiết bị.

→ Gần với “manual QA + điều khiển”, không thay thế được scenario có cấu trúc trừ khi tự build lớp orchestration phía trên.

### 3.2 Appium (WebDriver) — đây là nơi có “find / click / assert / screenshot”

- Mỗi thiết bị một URL: `http://{hub}:{port}/device/{device-id}/appium`
- Auth: capability **`gads:clientSecret`** (OAuth2 client credentials — xem `docs/appium-credentials.md`). Không cần lặp `platformName`/`deviceName` trong caps vì device đã gắn vào URL.

**Primitive kiểu WebDriver** (client tự viết loop/if):

| Ý niệm “node” (tương đương DF) | Appium / client |
|-------------------------------|-----------------|
| Chờ element | `WebDriverWait` + expected conditions |
| Tap / click | `click()` trên element |
| Nhập text | `sendKeys`, `setValue` (iOS/Android khác nhẹ) |
| Scroll / swipe | `mobile: swipe`, W3C actions, hoặc driver-specific |
| **If / branch** | `if (driver.findElements(...).size() > 0) { ... } else { ... }` |
| **Loop** | `for`, `while`, TestNG `@DataProvider`, parallel classes |
| **Capture màn hình** | `driver.getScreenshotAs(...)` |
| **Capture cây UI** | `driver.getPageSource()` (XML hierarchy) — tương đương góc độ “quét UI” nhưng không phải bước `capture` có tên trong GADS |
| Assert | test framework (JUnit, TestNG, pytest) |

### 3.3 Grid & phân phiên

- **Experimental grid** Hub: `http://{hub}/grid` — session theo **UDID**, `platformName`, `appium:automationName`, lọc `appium:platformVersion` (hub.md).
- **Selenium Grid 4**: provider đăng ký node; khuyến nghị jar **4.13** (ghi chú upstream về relay Appium).

---

## 4. Loop, if, capture — trả lời thẳng câu hỏi “nó xài node gì”

| Khái niệm Device Farmer (DF-002, …) | Trong GADS có sẵn? | Làm thế nào thực tế |
|--------------------------------------|--------------------|----------------------|
| `repeat` / `repeat_until` | Không có DSL | Viết trong **test code** hoặc CI; hoặc orchestrator ngoài gọi Appium lặp |
| `if_element` / `if_variable` | Không có DSL | Điều kiện trong code + `findElements` / biến runtime |
| Capture ảnh | Có (screenshot Hub/Appium) | API screenshot; không có bước “capture” trong schema kịch bản GADS |
| Capture hierarchy (XML) | Qua Appium | `getPageSource()` — phí hơn, dùng có chừng mực |
| Biến scenario (`${VAR}`) | Không — thuộc test/build | Maven/Gradle env, `.env`, TestNG parameters |

**Node.js**: GADS **không** bắt phải automation bằng Node; chỉ cần **Node > 16** để **cài Appium** trên máy provider (`npm install -g appium`). Client có thể là Java, Python, JS (WebdriverIO), v.v.

---

## 5. Khả thi theo loại thiết bị & OS host

Tóm tắt từ README + provider.md:

| Host OS | Android | iOS | Smart TV (Tizen / WebOS) |
|---------|---------|-----|---------------------------|
| **macOS** | Đầy đủ | Đầy đủ (WDA fork, giám sát tùy chọn Apple Configurator) | Chỉ **automation test**, không remote control như mobile |
| **Linux** | Đầy đủ | Hạn chế: không `mobile: startPerfRecord` / thứ cần Xcode; cần `usbmuxd` | Tương tự TV |
| **Windows** | Đầy đủ | Hạn chế tương tự Linux cho tool Xcode; cần iTunes cho iOS | Tương tự TV |

**TV cụ thể:**

- **Tizen:** SDB, developer mode, Appium `appium-tizen-tv-driver` — **không video stream**; một số remote control hạn chế.
- **WebOS:** CLI `ares`, UDID dạng `IP:PORT`, Chromedriver 2.36 do GADS quản lý; **không video**; chủ yếu **web app**; Dev Mode giới hạn 1000 giờ.

**iOS:** WDA phải build/sign IPA (fork shamanec); iOS 16+ bật Developer Mode; có nhánh supervised pairing (Mac + `.p12`).

---

## 6. Use case gợi ý (khi nên dùng GADS)

1. **Lab thiết bị thật tập trung** — reservation, stream, nhiều provider.
2. **Chạy suite Appium/Grid** song song (TestNG parallel, v.v.) thay vì AWS Device Farm / FTL.
3. **QA thủ công từ xa** — tap/swipe qua Hub.
4. **TV automation** (Tizen/WebOS) trong phạm vi driver + hạn chế đã nêu.

Ít phù hợp nếu mục tiêu là **một schema kịch bản khai báo** (JSON/YAML) với `if`/`repeat` **native** như DF-002 — cần lớp riêng (chính Device Farmer executor hoặc Maestro/Appium script generator).

---

## 7. Bổ sung cho ticket kịch bản nội bộ (DF-002, DF-003, `flow.md`)

### 7.1 Đối chiếu nhanh

| Device Farmer | GADS |
|---------------|------|
| `scenario.steps` tuyến tính + (sau DF-002) `repeat`, `if_element`, … | Không có file spec step tương đương; logic trong **Appium client** |
| Executor Python + uiautomator2 trực tiếp | Có thể dùng chung **thiết bị** nếu bridge ADB/Appium; hoặc chỉ dùng GADS làm **portal** |
| Record flow → selector + fallback ratio | GADS UI record không được mô tả chi tiết trong tài liệu đã đọc; Appium thường dùng inspector / code |

### 7.2 Hướng tích hợp khả thi (ý tưởng kiến trúc)

- **Chỉ dùng Hub làm infrastructure:** Device Farmer worker vẫn ADB tới device; GADS phục vụ team khác (Appium).
- **Hybrid:** Một task “chạy test” gọi remote WebDriver tới `.../device/{id}/appium` với `gads:clientSecret`; scenario JSON nội bộ **compile** ra script hoặc nhánh code (speculation — cần RFC riêng).
- **Học hỏi sản phẩm:** reservation, workspace, OAuth Appium, multi-provider — có thể vào PRD tương lai; **không copy** hub-ui proprietary.

### 7.3 Primitive nên giữ trong Device Farmer (không expect GADS cung cấp)

- `repeat` / `repeat_until` / `if_element` / `if_variable` (DF-002)
- `run_scenario` / thư viện template (DF-003)
- `wait_element`, `wait_stable`, `dismiss_popup` (đã có trong `scenario_schema.py`)

---

## 8. Tài liệu upstream hữu ích

- [README](https://github.com/shamanec/GADS/blob/main/README.md)
- [Hub setup / experimental grid](https://github.com/shamanec/GADS/blob/main/docs/hub.md)
- [Provider / drivers / TV](https://github.com/shamanec/GADS/blob/main/docs/provider.md)
- [Appium client credentials](https://github.com/shamanec/GADS/blob/main/docs/appium-credentials.md)

---

## 9. Xem thêm (device farm khác)

- **atxserver2** (openatx, Tornado + RethinkDB, reservation + **uiautomator2** qua `atxAgentAddress`): [atxserver2-reference-and-scenario-mapping.md](./atxserver2-reference-and-scenario-mapping.md) — **upstream ghi nhận ngừng phát triển chính**, MIT.
- **OpenSTF / STF** (Node + RethinkDB, Android lab, API reserve + `remoteConnect` / ADB): [stf-reference-and-scenario-mapping.md](./stf-reference-and-scenario-mapping.md) — org OpenSTF **không maintain**; xem fork **[DeviceFarmer](https://github.com/DeviceFarmer)**.

---

*Tài liệu này do AI tổng hợp từ README/docs công khai của GADS; hành vi API chi tiết có thể thay đổi theo release — nên đối chiếu tag release khi tích hợp.*
