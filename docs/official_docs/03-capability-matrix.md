# Ma trận năng lực (Capability Matrix)

> **Mã tài liệu:** DF-DOC-03-CAPABILITY-MATRIX
> **Phiên bản:** 1.0
> **Cập nhật lần cuối:** 2026-05-25
> **Trạng thái:** Approved
> **Đối tượng đọc:** Team Device Farm
> **Tài liệu liên quan:** [Product Overview](01-product-overview.md), [Platforms](platforms/README.md)

## 1. Mục đích tài liệu

Tài liệu này khai báo minh bạch mức năng lực hiện có của Device Farm theo từng platform social và từng cấp coverage L1/L2/L3. Mục tiêu là tránh kỳ vọng sai lệch khi đánh giá hoặc demo sản phẩm. Khi một ô trong ma trận ghi "Đang phát triển" hoặc "Draft", năng lực đó không được tuyên bố là đã sẵn sàng.

**Lưu ý quan trọng về L3:** L1 và L2 là core coverage levels. **L3 là cấp coverage experimental / preview, không bắt buộc cho trạng thái Active của một platform** — một platform được coi là "supported" khi đạt L2. L3 (MCP agent tools) được giữ trong ma trận để minh bạch về phạm vi nghiên cứu, không phải để bán như năng lực cốt lõi hiện tại.

Ma trận này được cập nhật trong cùng release với code. Khi có thay đổi trạng thái coverage, tài liệu sẽ ghi rõ ngày cập nhật ở header.

## 2. Quy ước trạng thái

| Ký hiệu | Trạng thái | Ý nghĩa |
|---|---|---|
| **Active** | Sẵn sàng dùng | Đã có code production, đã có test, đã document |
| **Foundation** | Có nền móng | Có khung contract, chưa có đầy đủ feature |
| **Draft** | Mục tiêu định hướng | Có profile target nhưng chưa có code đầy đủ |
| **N/A** | Không áp dụng | Không nằm trong scope sản phẩm |

## 3. Ma trận tổng quan: Platform × Coverage Level

Ma trận chính cho thấy **trạng thái coverage hiện tại** của bốn social platform mục tiêu giai đoạn đầu, theo ba cấp L1, L2, L3.

| Platform | L1 — Bulk manual control (Core) | L2 — Scenario automation (Core) | L3 — MCP agent tools (Preview / Optional) |
|---|---|---|---|
| **Facebook** | Active | **Active** | Foundation (preview) |
| **TikTok** | Active (qua primitive chung) | Draft | Draft (preview) |
| **Threads** | Active (qua primitive chung) | Draft | Draft (preview) |
| **Instagram** | Active (qua primitive chung) | Draft | Draft (preview) |

> **Ghi chú về L3:** L3 là cấp coverage experimental, không bắt buộc cho trạng thái Active. Một platform được khai báo "Active" khi đạt L2. Cột L3 được giữ để minh bạch phạm vi nghiên cứu AI agent qua MCP; không phải tiêu chí đánh giá platform support.

**Đọc bảng này thế nào?** Tất cả bốn platform đều có thể được điều khiển ở mức L1 thông qua các primitive chung của Device Farm — gesture, hierarchy, screenshot, stream. Ở mức L2 (scenario automation), chỉ Facebook hiện đã có scenario step và extraction strategy chuyên biệt — đủ để Facebook được coi là Active; ba platform còn lại vẫn ở trạng thái draft target và sẽ được đưa lên Active khi đạt L2. Ở mức L3 (MCP agent tools, preview), Facebook có nền móng (MCP tool generic đã expose), ba platform còn lại chưa có guardrail riêng cho platform đó; L3 không ảnh hưởng đến tuyên bố "supported" của một platform.

## 4. Ma trận chi tiết: năng lực cốt lõi theo platform

Ma trận chi tiết liệt kê 12 năng lực cốt lõi mà Device Farm cung cấp, và trạng thái của từng năng lực trên từng platform.

### 4.1 Năng lực điều khiển và quan sát thiết bị

| Năng lực | Facebook | TikTok | Threads | Instagram |
|---|---|---|---|---|
| Reserve và release device session | Active | Active | Active | Active |
| Gesture (tap, swipe, scroll, long_tap, ...) | Active | Active | Active | Active |
| UI hierarchy extraction | Active | Active | Active | Active |
| Screenshot và stream realtime | Active | Active | Active | Active |
| Attach/detach scrcpy | Active | Active | Active | Active |

Các năng lực này thuộc mặt phẳng L1 và độc lập với platform — vì vậy chúng có trạng thái Active đồng đều.

### 4.2 Năng lực thao tác platform-specific (L2)

| Năng lực | Facebook | TikTok | Threads | Instagram |
|---|---|---|---|---|
| Step type platform-specific (action) | **Active** (`tap_fb_comment_button`) | Draft | Draft | Draft |
| Extraction strategy platform-specific | **Active** (`fb_posts`, `fb_comments`) | Draft (`tiktok_videos`, `tiktok_comments`) | Draft (`threads_posts`, `threads_comments`) | Draft (`ig_media`, `ig_comments`) |
| Content type platform-qualified | **Active** (`fb_post`, `fb_comment`) | Draft (`tiktok_video`, `tiktok_comment`) | Draft (`threads_post`, `threads_comment`) | Draft (`ig_media`, `ig_comment`, `ig_profile`) |
| Parser implementation | **Active** (`device_farm/tasks/fb_extract/*`) | Chưa có | Chưa có | Chưa có |
| Frontend flow editor support | **Active** (Facebook node) | Đang phát triển | Đang phát triển | Đang phát triển |

Trên thực tế, một triển khai Device Farm ngày hôm nay có thể:

Trên **Facebook** — chạy ngay các scenario automation crawl post, crawl comment, dispatch trên nhiều device, lưu content vào collection, debug qua artifact. Đây là use case "out of the box".

Trên **TikTok / Threads / Instagram** — vẫn dùng được Device Farm thông qua các step generic (`tap`, `tap_selector`, `swipe`, `extract` với strategy `screen_data`, OCR, AI vision). Tuy nhiên, các step và strategy platform-specific chưa có sẵn. Use case cần các bước platform-specific có thể phối hợp với team Platform Engineer để hoàn thiện theo contract Social Platform Extensions, hoặc đợi roadmap.

### 4.3 Năng lực hỗ trợ ngang (cross-cutting)

| Năng lực | Trạng thái sản phẩm chung |
|---|---|
| Campaign dispatch | Active |
| Scenario graph builder qua frontend | Active |
| Per-device variable override | Active |
| Account group rotation (round-robin) | Active |
| Schedule theo cron | Active |
| Schedule run-now và toggle | Active |
| Notification in-app | Active |
| Notification webhook | Active |
| Activity log | Active |
| Execution artifact (screenshot, hierarchy) | Active |
| Content collection và export | Active (export đang refactor — xem `99-roadmap-and-faq.md`) |
| OCR extraction | Active |
| AI vision extraction (OpenAI, Gemini) | Active |
| Temporal workflow durable | Active (có fallback dispatcher khi Temporal off) |
| DLQ retry | Active |
| MCP stdio server với df_\* tool | Active |
| MCP session lifecycle | Active |
| Multi-tenancy theo organization | Active |
| JWT user auth | Active |
| Device-auth qua device key | Active |

### 4.4 Năng lực AI và MCP theo cấp L3 (Preview)

> **Lưu ý:** Toàn bộ năng lực trong mục này thuộc nhóm preview / experimental. L3 không bắt buộc cho trạng thái Active của một platform; đây là phần mở rộng đang được nghiên cứu, không khuyến cáo dùng cho production-grade workflow.

| Năng lực L3 (Preview) | Facebook | TikTok | Threads | Instagram |
|---|---|---|---|---|
| MCP tool generic (device control, session) | Active (preview) | Active (preview) | Active (preview) | Active (preview) |
| MCP tool extract content | Active (preview) | Active (preview) | Active (preview) | Active (preview) |
| Platform-specific guardrail (allowed action, evidence requirement, handoff condition) | Foundation (preview) | Chưa có | Chưa có | Chưa có |
| Platform-specific handoff rule | Foundation (preview) | Chưa có | Chưa có | Chưa có |

L3 nghĩa là "AI agent điều khiển 1 device/session với guardrail phù hợp với platform". Hiện tại, các MCP tool generic đã sẵn sàng cho cả bốn platform ở dạng preview, nhưng **bộ guardrail riêng theo platform** (ví dụ "trên Instagram, AI không được follow quá X tài khoản/giờ", "trên TikTok, gặp captcha phải handoff") chưa được khai báo cho ba platform ngoài Facebook. Một platform không cần đạt L3 để được coi là "supported"; L3 chỉ phục vụ hướng nghiên cứu AI agent.

## 5. Ma trận năng lực theo persona

Đối với các persona đã định nghĩa trong [Personas & Journeys](02-personas-and-journeys.md), bảng dưới cho thấy năng lực phục vụ persona đó đã sẵn sàng đến đâu. Cột AI Ops Supervisor được giữ ở dạng (Preview) để phản ánh trạng thái experimental của module 10.

| Năng lực phục vụ persona | Social Data Operator | Automation Builder | AI Ops Supervisor (Preview) | Fleet Operator |
|---|---|---|---|---|
| Crawl dữ liệu social ở quy mô | Active cho FB / Draft cho TikTok, Threads, IG | N/A | N/A | N/A |
| Dựng scenario tái sử dụng | N/A | Active | N/A | N/A |
| Preview scenario trên 1 device | N/A | Active | N/A | N/A |
| Diff giữa scenario version | N/A | Đang phát triển | N/A | N/A |
| AI agent điều khiển 1 device | N/A | N/A | Active generic — preview / Foundation platform-specific — preview | N/A |
| Review hành vi AI sau session | N/A | N/A | Active activity log — preview | N/A |
| Dashboard health fleet | N/A | N/A | N/A | Active |
| Alert proactive về device sắp rớt | N/A | N/A | N/A | Đang phát triển |
| Bulk pair từ file | N/A | N/A | N/A | Đang phát triển |
| Báo cáo uptime tự động | N/A | N/A | N/A | Đang phát triển |

## 6. Ma trận tích hợp ngoài

Bảng dưới khai báo các tích hợp ngoài hiện có và trạng thái của chúng. Tích hợp được hiểu là khả năng Device Farm gọi ra hệ thống bên ngoài hoặc nhận lệnh từ bên ngoài.

| Tích hợp | Mục đích | Trạng thái |
|---|---|---|
| OpenAI API | AI vision extraction | Active |
| Gemini API | AI vision extraction | Active |
| Webhook ra ngoài (Slack, Telegram, custom) | Notification | Active |
| MinIO / S3 | Object storage | Active |
| Temporal Cloud / self-host | Workflow engine | Active |
| Tailscale | Network overlay cho relay agent | Active (xem `docs/operations/tailscale-setup.md`) |
| Prometheus | Metric scraping | Roadmap |
| OpenTelemetry tracing | Distributed tracing | Roadmap |
| SAML / OIDC SSO | Đăng nhập doanh nghiệp | Roadmap |
| Vault / Secret manager | Credential lưu trữ an toàn | Roadmap |

## 7. Khả năng mở rộng platform mới

Khi có yêu cầu hỗ trợ một platform thứ năm trở đi (ví dụ YouTube, LinkedIn, Reddit), Device Farm hỗ trợ qua contract Social Platform Extensions được mô tả tại [modules/08-social-platform-extensions.md](modules/08-social-platform-extensions.md). Một platform mới cần đáp ứng các tiêu chí sau để được coi là draft target, sau đó thành active:

Để vào trạng thái **draft target**, cần có: platform profile theo template tại `docs/product/platforms/README.md`; định nghĩa step type mới theo naming `<platform>_<verb>_<object>`; định nghĩa extraction strategy theo naming `<platform>_<data_object>`; định nghĩa content type theo naming `<platform>_<content_object>`; xác định account requirement và session requirement.

Để chuyển sang trạng thái **active**, cần có thêm: parser implementation; handler trong scenario executor; frontend flow editor node; test unit và integration; cập nhật documentation đầy đủ; ít nhất một campaign reference chạy thành công ở quy mô.

Thời gian ước tính chuyển một platform từ draft sang active: khoảng 2–4 tuần engineering, tùy độ phức tạp UI platform.

## 8. Cách dùng ma trận này trong demo và đánh giá

Khi Device Farm được đem đi demo hoặc đánh giá, ma trận này là tham chiếu chính thức để trả lời câu hỏi "có hỗ trợ X không". Các quy tắc trung thực:

Không gọi "Draft" là "Active". Khi một ô là Draft, demo trên platform đó phải dùng các primitive generic chứ không phải step platform-specific chưa tồn tại. Khi một ô là Foundation, demo có thể trình diễn năng lực sơ bộ nhưng phải nói rõ "chưa đầy đủ guardrail".

Khi có câu hỏi cụ thể (ví dụ "có crawl được story Instagram không"), tra cứu ma trận trước khi trả lời. Nếu không có ô tương ứng, tạo ô mới trong roadmap thay vì hứa miệng.

Ma trận này có thể được tách thành slide cho buổi pitch — kết hợp với [Product Overview](01-product-overview.md) là đủ cho buổi demo đầu.

## 9. Cập nhật và governance

Ma trận này được sở hữu bởi team Product. Mỗi lần có thay đổi trạng thái (Draft → Foundation → Active hoặc đổi platform mới), bảng được cập nhật và ghi rõ ngày trong header. Team Engineering báo cho team Product khi đẩy code thay đổi trạng thái coverage, để cập nhật trong cùng release.

Các thay đổi trạng thái lớn (ví dụ "Instagram L2 chuyển từ Draft sang Active") cần được công bố qua release note tới các pilot đang chạy.
