# DF-T-08-016 — Threads L2 Active readiness bundle

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-08-016 |
| **Title** | Threads L2 Active readiness bundle |
| **Type** | `type:feature` |
| **Epic** | DF-E-08 — Social Platform Extensions |
| **Module** | DF-MOD-08 — Social Platform Extensions |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:social-ext`, `layer:backend`, `layer:frontend`, `layer:test`, `platform:threads`, `coverage:L2`, `type:feature` |
| **Truy vết — FR refs** | FR-08-06, FR-08-11, FR-08-12, FR-08-14 |
| **Truy vết — UC refs** | UC-08-05 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Lộ trình quý hiện tại ưu tiên đưa Threads lên L2 Active. Các ticket draft hiện có mới tạo parser/handler nền, chưa đủ checklist Active trong đặc tả module: frontend node, scenario template/reference, test bốn tầng, ma trận năng lực, platform profile và release gate. Ticket này là bundle nghiệm thu cuối cho Threads Active.

Đọc nhanh cho dev: ticket này biến một requirement trong lộ trình thành phạm vi triển khai có thể nghiệm thu độc lập. Không gom thêm UI polish, draft platform hoặc refactor ngoài phạm vi; các phần backend, frontend và test phải bám trực tiếp vào `Tiêu chí chấp nhận` và `Test case nghiệp vụ` của ticket này.

## 3. Câu chuyện người dùng

> **Là** Platform Engineer  
> **Tôi muốn** đưa Threads từ Draft target lên L2 Active theo checklist artifact  
> **Để** lộ trình quý có platform usable thật, không chỉ có parser/handler draft

Persona phụ: Không.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI xác nhận parser và handler Threads đã chạy qua scenario executor chuẩn, không có runner riêng.
- Hệ thống PHẢI bổ sung frontend flow editor node Threads với labels và schema đúng naming canonical — trace FR-08-11.
- Hệ thống PHẢI bổ sung scenario template/reference cho workflow crawl tối thiểu.
- Hệ thống PHẢI đạt test bốn tầng: schema, executor, parser, persistence — trace FR-08-12.
- Hệ thống PHẢI content type platform-qualified `threads_post/threads_comment` được validate và query được.
- Hệ thống PHẢI cập nhật ma trận năng lực/platform profile từ Draft target lên L2 Active khi gate pass — trace FR-08-14.
- Hệ thống PHẢI document cảnh báo rủi ro account Meta dùng chung với Instagram/Facebook.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Threads Active gate pass**

```gherkin
Given parser/handler draft Threads đã merge
When chạy L2 readiness suite
Then toàn bộ schema/executor/parser/persistence test pass
And ma trận năng lực có thể chuyển L2 Active
```

**AC-2: Frontend node Threads**

```gherkin
Given generated client/schema Threads sẵn sàng
When Automation Builder mở flow editor
Then node platform-specific xuất hiện và lưu scenario hợp lệ
And scenario JSON dùng naming canonical
```

**AC-3: Scenario template tối thiểu**

```gherkin
Given pilot org bật feature flag
When user clone template platform
Then template chạy preview trên một device
And artifact/content item tạo đúng content type
```

**AC-4: Không có runner riêng**

```gherkin
Given codebase có platform implementation
When chạy contract audit
Then không phát hiện runner path ngoài scenario executor
And CI fail nếu có bypass
```

**AC-5: Known gap được chặn**

```gherkin
Given platform còn L3 guardrail chưa active
When user cố bật L3/MCP active flag
Then hệ thống chặn hoặc hiển thị Preview rõ
And không tuyên bố L3 Active
```

**AC-6: Regression UI mismatch**

```gherkin
Given app platform đổi UI fixture
When chạy parser readiness
Then test fail rõ với UI mismatch
And không persist content sai schema
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm L3/MCP guardrail Active — theo lộ trình dài hạn.
- KHÔNG bao gồm logic login/OTP/captcha — thuộc scenario/account workflow.
- KHÔNG bao gồm parser/handler core nếu chưa xong — thuộc ticket draft tương ứng.
- KHÔNG bao gồm mở default ON cho mọi organization — rollout do DF-T-08-014 kiểm soát.

## 7. Kế hoạch triển khai

**Implementation**

- [ ] Chuẩn hóa checklist artifact Threads L2 Active.
- [ ] Thêm frontend node và generated schema mapping cho Threads.
- [ ] Thêm scenario template/reference workflow tối thiểu.
- [ ] Thêm test bốn tầng và fixture UI phổ biến.
- [ ] Cập nhật platform profile và ma trận năng lực.
- [ ] Cập nhật feature flag rollout và release notes.

**Test**

- [ ] Unit test cho rule nghiệp vụ chính.
- [ ] Integration test cho API/event/schema liên quan.
- [ ] E2E hoặc manual evidence cho luồng người dùng nếu có UI.
- [ ] Map từng test case bên dưới vào automated/manual evidence.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-08-016-01 | Positive | Parser/handler draft đã merge | Chạy readiness suite | Toàn bộ gate pass |
| TC-DF-T-08-016-02 | Positive | Flow editor mở | Kéo node platform và lưu scenario | Scenario lưu đúng schema canonical |
| TC-DF-T-08-016-03 | Negative | Feature flag platform OFF | User pilot chưa được bật mở template | UI/API chặn rõ platform chưa Active cho org |
| TC-DF-T-08-016-04 | Negative | Content type generic `post/comment` | Parser persist content | Validation reject, không lưu generic type |
| TC-DF-T-08-016-05 | Edge | UI fixture biến thể locale/app version | Chạy parser regression | Không persist sai; báo mismatch rõ nếu không parse được |
| TC-DF-T-08-016-06 | Edge | Resource/account safety warning cần hiển thị | Mở profile/docs/release note | Known risk được document đúng và không bật L3 mặc định |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-08-010, DF-T-08-011, DF-T-08-014, DF-T-11-006.

**Chặn:** Lộ trình ngắn hạn platform L2 Active.

**Phụ thuộc giữa Epic:** DF-E-04 cung cấp scenario executor, DF-E-06 content persistence, DF-E-07 account resolution, DF-E-11 frontend flow editor.

**Rủi ro:**

- **R1 — Active giả khi chỉ có draft code:** Giảm thiểu: readiness ticket chỉ Done khi đủ frontend node, template, tests và docs.
- **R2 — UI platform thay đổi nhanh:** Giảm thiểu: fixture regression và clear UI mismatch error.
- **R3 — Account safety:** Giảm thiểu: warning theo platform, không tự bật L3 và không tự suy diễn account fallback.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Code/tài liệu merged và pass CI.
- [ ] Test case đã được map sang automated test hoặc manual evidence.
- [ ] API contract, event schema hoặc generated client cập nhật nếu thay đổi.
- [ ] Documentation trong `docs/official_docs` và ma trận năng lực cập nhật khi trạng thái coverage thay đổi.
- [ ] Telemetry/audit event cho path quan trọng đã có.
- [ ] Release notes/changelog ghi rõ impact và known limitation.

## 11. Truy vết & tài liệu tham chiếu

- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — ngắn hạn: Threads L2 Active.
- **Đặc tả module:** [08-social-platform-extensions.md](../../official_docs/modules/08-social-platform-extensions.md) — checklist Draft/Active và FR-08-11/12/14.
- **Platform profile:** [platforms/threads.md](../../official_docs/platforms/threads.md).
