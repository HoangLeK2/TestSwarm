# DF-T-XX-NNN — [Ticket title ngắn gọn, mô tả deliverable]

> **Template version:** 1.0
> **Hướng dẫn sử dụng:** Copy file này khi tạo ticket mới. Đổi tên file theo quy ước `DF-T-<epic>-<seq>-<slug>.md`. Thay toàn bộ phần trong dấu ngoặc vuông `[...]`. Xoá block hướng dẫn này khi ticket sẵn sàng đưa vào backlog.

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-XX-NNN |
| **Title** | [Ticket title đầy đủ] |
| **Type** | `type:feature` / `type:bug` / `type:tech-debt` / `type:spike` / `type:doc` / `type:test` |
| **Epic** | DF-E-XX — Tên Epic |
| **Module** | DF-MOD-XX — [Tên module] |
| **Priority** | P0 / P1 / P2 / P3 |
| **Story Points** | 1 / 2 / 3 / 5 / 8 / 13 |
| **Status** | `Backlog` / `Ready` / `In Progress` / `In Review` / `Done` / `Cancelled` |
| **Labels** | `module:xxx`, `layer:backend`, `type:feature`, `platform:facebook`, `coverage:L2`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-XX-01, FR-XX-02 (tham chiếu đặc tả module) |
| **Truy vết — UC refs** | UC-XX-03 |
| **Reporter** | (placeholder, sẽ điền khi import vào tracker) |
| **Assignee** | (placeholder) |
| **Created** | YYYY-MM-DD |
| **Last updated** | YYYY-MM-DD |

## 2. Bối cảnh nghiệp vụ

[2-4 đoạn văn xuôi giải thích:
- Vì sao ticket này tồn tại — vấn đề nghiệp vụ nào đang chưa được giải quyết.
- Persona nào sẽ hưởng lợi và họ đang đau ở đâu.
- Ticket nằm ở vị trí nào trong luồng nghiệp vụ của module (dẫn lại sơ đồ luồng trong đặc tả module).
- Mức độ ưu tiên trong bối cảnh lộ trình (tham chiếu `99-roadmap-and-faq.md` nếu cần).]

## 3. Câu chuyện người dùng

> **Là** [persona — vd "Fleet Operator"]
> **Tôi muốn** [hành động — vd "tạo automation campaign chạy trên một cụm thiết bị theo schedule định trước"]
> **Để** [giá trị nghiệp vụ — vd "có thể vận hành hàng nghìn account mà không cần thao tác thủ công"]

Nếu ticket phục vụ nhiều persona, viết một user story chính + ghi chú các persona phụ ở dòng thứ hai.

## 4. Yêu cầu chức năng

[Liệt kê 5-10 FR cụ thể ở dạng bullet hoặc bảng. Mỗi item là một hành vi hệ thống quan sát được. Tránh diễn tả implementation; chỉ nói "hệ thống phải làm gì". Tham chiếu lại FR-XX-YY trong đặc tả module khi bullet này là một subset của FR đó.]

- Hệ thống PHẢI [hành vi 1] — trace FR-XX-YY.
- Hệ thống PHẢI [hành vi 2] — trace FR-XX-YY.
- Hệ thống NÊN [hành vi 3] — trace FR-XX-YY.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: [Tên scenario chính — luồng thành công]**

```
Given [bối cảnh / state ban đầu]
And [điều kiện bổ sung nếu có]
When [hành động người dùng hoặc trigger hệ thống]
Then [kết quả mong đợi]
And [side-effect mong đợi]
```

**AC-2: [Tên scenario thứ hai]**

```
Given ..
When ..
Then ..
```

**AC-3: [Tên scenario thứ ba]**

```
Given ..
When ..
Then ..
```

Tối thiểu 3 AC. Khuyến nghị 4-6 AC cho ticket P0/P1.

## 6. Ngoài phạm vi

[Danh sách rõ ràng những thứ ticket này KHÔNG bao gồm. Mỗi item ghi kèm lý do hoặc redirect sang ticket khác:]

- KHÔNG bao gồm [feature X] — sẽ xử lý trong ticket DF-T-YY-ZZZ.
- KHÔNG bao gồm [edge case Y] — đã được loại trừ trong đặc tả module mục Z.
- KHÔNG bao gồm [tích hợp Z] — sẽ được tính trong Epic DF-E-MM.

## 7. Kế hoạch triển khai

Chia checklist theo layer. Chỉ tích các layer áp dụng.

**Backend** (`layer:backend`)

- [ ] [Việc triển khai 1]
- [ ] [Việc triển khai 2]

**Frontend** (`layer:frontend`)

- [ ] [Việc triển khai 1]
- [ ] [Việc triển khai 2]

**Contract / API** (`layer:contract`)

- [ ] [Đặc tả endpoint / message schema mới hoặc thay đổi]
- [ ] [Cập nhật OpenAPI / proto / event schema]

**Database / Migration** (`layer:db`)

- [ ] [Migration mô tả]
- [ ] [Backfill / data validation]

**Infra / DevOps** (`layer:infra`)

- [ ] [Helm / IaC change]
- [ ] [Secret / config]

**Documentation** (`layer:docs`)

- [ ] Cập nhật `docs/modules/<mod>.md`
- [ ] Cập nhật `docs/official_docs/modules/<mod>.md` nếu có thay đổi nghiệp vụ
- [ ] Cập nhật changelog

**Test** (`layer:test`)

- [ ] Viết unit test cho logic mới
- [ ] Viết integration test cho AC-1, AC-2, AC-3
- [ ] Bổ sung e2e nếu phù hợp

## 8. Test case nghiệp vụ

Bảng dưới ghi case mức nghiệp vụ. Mã test: `TC-DF-T-XX-NNN-MM`.

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-XX-NNN-01 | Positive | [state] | [steps] | [expected] |
| TC-DF-T-XX-NNN-02 | Positive | [state] | [steps] | [expected] |
| TC-DF-T-XX-NNN-03 | Negative | [state] | [steps] | [expected — lỗi rõ ràng, không silent fail] |
| TC-DF-T-XX-NNN-04 | Negative | [state] | [steps] | [expected — bị từ chối với mã lỗi cụ thể] |
| TC-DF-T-XX-NNN-05 | Edge | [boundary state] | [steps tại giới hạn] | [expected — không crash, có graceful degrade] |

**Quy ước phân loại:**

- **Positive:** luồng thành công — input hợp lệ, người dùng có quyền, hệ thống ở state mong đợi.
- **Negative:** sai input / sai quyền / sai state / vi phạm quy tắc nghiệp vụ. Phải có ít nhất 2 case loại này.
- **Edge:** boundary value (0, 1, max), concurrency, retry exhaustion, timeout, disconnect, partial failure, idempotency.

Tối thiểu 5 test case cho ticket `type:feature`. Khuyến nghị 7-10 cho ticket P0.

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** [danh sách ticket ID phải xong trước, vd `DF-T-01-005`. Nếu không có ghi "Không".]

**Chặn:** [danh sách ticket ID đang chờ ticket này. Có thể bỏ trống nếu không rõ.]

**Phụ thuộc giữa Epic:** [nếu phụ thuộc Epic khác, ghi rõ Epic và lý do.]

**Rủi ro:**

- **[Risk 1 — vd "Race condition trên FSM device khi 2 campaign cùng claim"]:** [tác động] → [biện pháp giảm thiểu].
- **[Risk 2]:** [tác động] → [biện pháp].

**Phụ thuộc bên ngoài:** [API bên thứ ba, version Android, library version, ... nếu có.]

## 10. Điều kiện hoàn thành

Checklist phải tích đủ trước khi đóng ticket. Mặc định gồm DoD chung của bộ backlog (xem `README.md` mục 9) cộng với điều kiện riêng dưới đây:

- [ ] Code merged vào nhánh chính và pass CI.
- [ ] Unit test coverage ≥ 80% trên file thay đổi.
- [ ] Tất cả test case TC-DF-T-XX-NNN-* được map sang test tự động hoặc đã chạy manual và lưu evidence.
- [ ] Tài liệu kỹ thuật `docs/modules/<mod>.md` cập nhật.
- [ ] Tài liệu nghiệp vụ `docs/official_docs/modules/<mod>.md` cập nhật nếu có thay đổi nhìn thấy từ phía nghiệp vụ.
- [ ] Telemetry (log + metric) cho path quan trọng đã có.
- [ ] Code review có ≥ 1 approve từ owner module.
- [ ] Release notes / changelog đã được cập nhật.
- [ ] [Điều kiện riêng theo ticket — vd "Đã chạy thử trên 10 thiết bị thật ≥ 24h" cho ticket fleet ops]

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [docs/official_docs/modules/XX-mod-name.md](../../official_docs/modules/XX-mod-name.md) — mục 6 (Functional Spec), FR-XX-YY.
- **Ma trận năng lực:** [03-capability-matrix.md](../../official_docs/03-capability-matrix.md) — ô [Platform × Level].
- **Nhóm người dùng:** [02-personas-and-journeys.md](../../official_docs/02-personas-and-journeys.md) — [Persona name].
- **Thuật ngữ:** [00-glossary.md](../../official_docs/00-glossary.md) — [thuật ngữ liên quan].
- **Lộ trình:** [99-roadmap-and-faq.md](../../official_docs/99-roadmap-and-faq.md) — [milestone tham chiếu].

## 12. Ghi chú ngôn ngữ

- Nội dung ticket viết tiếng Việt trước; chỉ giữ tiếng Anh cho thuật ngữ product, code identifier, API, enum, metric, status, label và tên công cụ đã thống nhất.
- Khi nhắc ticket hoặc Epic khác, chỉ ghi ID dạng `DF-T-YY-ZZZ` hoặc `DF-E-YY`; không dùng markdown link tới ticket/Epic.
- Các nhãn section dùng đúng bộ từ trong template này; không trộn lại nhãn cũ bằng tiếng Anh trong phần mô tả nghiệp vụ.
