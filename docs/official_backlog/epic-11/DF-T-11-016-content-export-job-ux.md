# DF-T-11-016 — Content export job UX

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-016 |
| **Title** | Content export job UX — tạo export, theo dõi trạng thái và tải file kết quả |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `module:content`, `layer:frontend`, `layer:contract`, `type:feature`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-11-11, FR-06-10, FR-06-11, FR-06-12 |
| **Truy vết — UC refs** | UC-06-01, UC-06-04, UC-11-04 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Social Data Operator không chỉ cần xem `content item` trên dashboard mà còn cần lấy dữ liệu ra file để kiểm tra, chia sẻ hoặc nhập vào quy trình phân tích khác. Backend export trong DF-T-06-016 chạy dạng `export job`, vì vậy nếu frontend chỉ có nút tải trực tiếp thì người dùng sẽ không biết job đang `queued`, `running`, `completed` hay `failed`.

Ticket này bổ sung UX cho luồng export kết quả: chọn collection/filter đang xem, tạo `export job`, theo dõi trạng thái, tải file khi hoàn tất và retry khi job fail. Đây là P1 vì nằm ngay sau happy path xem content; không chặn execution nhưng chặn release nếu mục tiêu R1 có “export CSV”.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator  
> **Tôi muốn** tạo export từ collection hoặc filter hiện tại và theo dõi trạng thái job  
> **Để** có thể lấy kết quả crawl ra file mà không phải chờ màn hình treo hoặc thao tác lại từ đầu

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép tạo `export job` từ collection hiện tại hoặc bộ lọc đang áp dụng — trace FR-11-11, FR-06-10.
- Hệ thống PHẢI hiển thị trạng thái job gồm `queued`, `running`, `completed`, `failed`, `cancelled` — trace FR-06-11.
- Hệ thống PHẢI hiển thị thời gian tạo, người tạo, số lượng `content item` dự kiến, định dạng export và filter snapshot.
- Khi job `completed`, hệ thống PHẢI hiển thị `download URL` còn hiệu lực và thời hạn hết hạn.
- Khi job `failed`, hệ thống PHẢI hiển thị lỗi nghiệp vụ dễ hiểu và cho phép retry nếu backend cho phép.
- Hệ thống PHẢI chặn user tải export của organization khác theo RBAC và tenant scope.
- Hệ thống NÊN deep link từ content browser tới lịch sử export liên quan đến collection đang xem.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Tạo export từ content browser**

```gherkin
Given tôi đang xem một collection có 120 content item
And tôi có quyền export content
When tôi chọn tạo export CSV cho filter hiện tại
Then hệ thống tạo một export job mới
And job hiển thị trạng thái queued hoặc running trong màn hình export
```

**AC-2: Tải file khi job hoàn tất**

```gherkin
Given export job của tôi đã completed
When tôi mở chi tiết job
Then tôi thấy nút tải file
And file tải về đúng định dạng và đúng organization
```

**AC-3: Job fail có lỗi rõ ràng**

```gherkin
Given export job chuyển sang failed
When tôi mở chi tiết job
Then tôi thấy lý do fail ở mức nghiệp vụ
And tôi có thể retry nếu backend trả retryable=true
```

**AC-4: Không được truy cập export của organization khác**

```gherkin
Given tồn tại export job thuộc organization khác
When tôi truy cập deep link tới job đó
Then hệ thống hiển thị trạng thái không có quyền truy cập
And không lộ download URL hoặc filter snapshot
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm backend export engine, job worker hoặc file storage — thuộc DF-T-06-016.
- KHÔNG bao gồm scheduled export hoặc recurring report — để phase sau.
- KHÔNG bao gồm BI dashboard hoặc warehouse export — ngoài phạm vi R1.
- KHÔNG bao gồm export mọi artifact binary thô — ticket này tập trung vào content data CSV/JSON theo contract DF-T-06-016.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Thêm action tạo export từ content browser DF-T-11-009.
- [ ] Thêm màn/list export jobs với filter theo collection, status và người tạo.
- [ ] Thêm detail drawer hoặc detail page cho export job.
- [ ] Thêm trạng thái loading, empty, failed, retryable và expired download URL.
- [ ] Thêm guard RBAC/tenant scope cho deep link export job.

**Contract / API** (`layer:contract`)

- [ ] Đồng bộ generated client cho API tạo job, list job, get job detail, retry job và lấy download URL.
- [ ] Map enum status từ backend sang label hiển thị thống nhất.

**Test** (`layer:test`)

- [ ] Viết integration test cho tạo job và xem status.
- [ ] Viết e2e happy path tạo export từ content browser rồi tải file completed.
- [ ] Viết regression test cho unauthorized deep link.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-016-01 | Positive | User có quyền export, collection có dữ liệu | Tạo export CSV từ filter hiện tại | Export job được tạo với filter snapshot đúng |
| TC-DF-T-11-016-02 | Positive | Export job completed | Mở chi tiết job và tải file | File tải được, status không đổi, download URL không lộ organization khác |
| TC-DF-T-11-016-03 | Negative | User không có quyền export | Bấm tạo export | Hệ thống từ chối bằng thông báo rõ ràng, không tạo job |
| TC-DF-T-11-016-04 | Negative | Export job failed và retryable=false | Mở chi tiết job | Không hiển thị retry action, lỗi hiển thị dễ hiểu |
| TC-DF-T-11-016-05 | Edge | Download URL đã hết hạn | Bấm tải lại file | Hệ thống yêu cầu tạo lại hoặc refresh URL theo contract, không crash |
| TC-DF-T-11-016-06 | Edge | Collection rỗng | Tạo export | Hệ thống cho biết không có dữ liệu để export hoặc tạo file rỗng theo policy đã thống nhất |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-06-016, DF-T-11-009, DF-T-01-002.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** DF-E-06 cung cấp export job contract; DF-E-01 cung cấp auth và tenant scope.

**Rủi ro:**

- **Contract export job chưa ổn định:** frontend phải dùng generated client và không tự đoán enum status.
- **File lớn gây timeout trình duyệt:** UI chỉ tải qua download URL, không stream file lớn qua React state.

**Phụ thuộc bên ngoài:** File storage và URL expiry policy từ backend export.

## 10. Điều kiện hoàn thành

- [ ] User tạo được export job từ content browser.
- [ ] User xem được danh sách và chi tiết export job với status đúng.
- [ ] User tải được file khi job completed.
- [ ] Unauthorized deep link không lộ dữ liệu.
- [ ] Test case TC-DF-T-11-016-* được map sang test tự động hoặc manual evidence.
- [ ] Generated client cập nhật và không có ad hoc fetch trong component.
- [ ] Tài liệu release note ghi rõ export job UX đã hỗ trợ trạng thái async.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** `docs/official_docs/modules/11-frontend-dashboard.md` — FR-11-11.
- **Đặc tả module:** `docs/official_docs/modules/06-content-extraction-artifacts.md` — FR-06-10, FR-06-11, FR-06-12.
- **Nhóm người dùng:** `docs/official_docs/02-personas-and-journeys.md` — Social Data Operator.
- **Lộ trình:** `docs/official_docs/99-roadmap-and-faq.md` — export content refactor.

