# DF-T-11-018 — DLQ resolution UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-018 |
| **Title** | DLQ resolution UI — mở lỗi, replay và close failed execution item |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `module:campaigns`, `layer:frontend`, `layer:contract`, `type:feature`, `persona:automation-builder`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-11-09, FR-04-13, FR-04-14, FR-04-20 |
| **Truy vết — UC refs** | UC-04-03, UC-04-04, UC-11-03 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Execution monitor hiện có thể hiển thị tiến độ và log, nhưng operator vẫn cần một bề mặt rõ ràng để xử lý các item rơi vào DLQ. Nếu chỉ có backend open/replay/close mà không có UI, khi campaign fail một phần, end-user không thể tự hiểu item nào cần replay, item nào nên close, và vì sao không nên replay toàn bộ campaign.

Ticket này thêm UI xử lý DLQ ở mức vận hành: xem failed item theo campaign/execution/device/account, đọc lý do fail, replay item hợp lệ và close item với lý do. Đây là P2 vì phục vụ failure handling, không thuộc happy path tối thiểu, nhưng cần trước khi vận hành beta có volume thật.

## 3. Câu chuyện người dùng

> **Là** Automation Builder  
> **Tôi muốn** xem và xử lý DLQ item ngay trong execution monitor  
> **Để** có thể khôi phục một phần campaign fail mà không phải nhờ backend engineer can thiệp thủ công

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hiển thị danh sách DLQ item theo campaign, execution, device, account và error code.
- Hệ thống PHẢI cho phép mở chi tiết item để xem step, input snapshot, lỗi, số lần retry và artifact liên quan nếu có.
- Hệ thống PHẢI cho phép replay item khi backend đánh dấu item `replayable`.
- Hệ thống PHẢI cho phép close item với lý do bắt buộc khi operator quyết định không replay.
- Hệ thống PHẢI hiển thị trạng thái replay/close rõ ràng và cập nhật execution monitor sau thao tác.
- Hệ thống PHẢI chặn thao tác replay/close nếu user thiếu quyền hoặc item đã terminal.
- Hệ thống NÊN hỗ trợ chọn nhiều item cùng error code để replay theo batch nhỏ nếu contract backend cho phép.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Xem DLQ item từ execution monitor**

```gherkin
Given một campaign có execution item failed và được đưa vào DLQ
When tôi mở execution monitor của campaign đó
Then tôi thấy số lượng DLQ item
And có thể mở danh sách item để xem chi tiết lỗi
```

**AC-2: Replay item hợp lệ**

```gherkin
Given một DLQ item có replayable=true
And tôi có quyền vận hành campaign
When tôi chọn replay item
Then hệ thống gọi API replay
And item chuyển sang trạng thái replay requested hoặc running theo response backend
```

**AC-3: Close item cần lý do**

```gherkin
Given một DLQ item đang open
When tôi chọn close mà không nhập lý do
Then hệ thống không gửi request
And hiển thị lỗi yêu cầu nhập lý do close
```

**AC-4: Không replay item không hợp lệ**

```gherkin
Given một DLQ item có replayable=false
When tôi mở item
Then action replay bị disabled
And UI hiển thị lý do không thể replay
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm backend DLQ open/replay/close — thuộc DF-T-04-012.
- KHÔNG bao gồm retry policy/backoff engine — thuộc DF-T-04-011.
- KHÔNG bao gồm bulk rerun toàn bộ campaign — nếu cần sẽ tách ticket ở DF-E-04.
- KHÔNG bao gồm notification khi DLQ tăng cao — thuộc DF-E-09.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Thêm DLQ summary vào execution monitor DF-T-11-008.
- [ ] Thêm list/detail UI cho DLQ item.
- [ ] Thêm action replay và close theo quyền user.
- [ ] Thêm trạng thái optimistic update hoặc refetch sau thao tác.
- [ ] Thêm batch action chỉ khi contract backend hỗ trợ.

**Contract / API** (`layer:contract`)

- [ ] Đồng bộ generated client với API list/get/replay/close DLQ item.
- [ ] Map enum status, error code và replayability reason.

**Test** (`layer:test`)

- [ ] Viết e2e xem DLQ item và replay item thành công.
- [ ] Viết integration test close item cần lý do.
- [ ] Viết test unauthorized replay/close.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-018-01 | Positive | Campaign có 3 DLQ item open | Mở execution monitor | DLQ summary và danh sách item hiển thị đúng số lượng |
| TC-DF-T-11-018-02 | Positive | DLQ item replayable=true | Replay item | Item chuyển trạng thái theo response và log thao tác được cập nhật |
| TC-DF-T-11-018-03 | Negative | User thiếu quyền campaign operation | Bấm replay | Hệ thống từ chối, không gọi replay API hoặc API trả forbidden được hiển thị rõ |
| TC-DF-T-11-018-04 | Negative | Item đã closed | Mở chi tiết item | Replay/close action bị disabled |
| TC-DF-T-11-018-05 | Edge | DLQ item có artifact lỗi rất lớn | Mở chi tiết item | UI vẫn phản hồi, chỉ hiển thị preview/link artifact theo contract |
| TC-DF-T-11-018-06 | Edge | Replay request timeout | Replay item | UI hiển thị trạng thái chưa chắc chắn và cho phép refresh trạng thái |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-012, DF-T-04-013, DF-T-11-008.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** DF-E-04 cung cấp DLQ contract và execution event stream; DF-E-01 cung cấp RBAC.

**Rủi ro:**

- **Replay nhầm gây tác động platform:** UI phải dựa vào `replayable` và reason từ backend, không tự suy diễn.
- **Operator hiểu sai trạng thái item:** copy trạng thái phải thống nhất với enum backend và execution monitor.

**Phụ thuộc bên ngoài:** Không.

## 10. Điều kiện hoàn thành

- [ ] Execution monitor hiển thị DLQ summary.
- [ ] User xem được list/detail DLQ item.
- [ ] Replay và close hoạt động theo quyền và trạng thái item.
- [ ] Close bắt buộc có reason.
- [ ] Test case TC-DF-T-11-018-* được map sang test tự động hoặc manual evidence.
- [ ] Không tự suy diễn recovery ngoài contract DF-T-04-012.
- [ ] Release notes ghi rõ DLQ resolution UI ở mức P2/beta operation.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** `docs/official_docs/modules/11-frontend-dashboard.md` — execution monitor.
- **Đặc tả module:** `docs/official_docs/modules/04-campaigns-scenarios-executions.md` — DLQ, retry và execution event.
- **Nhóm người dùng:** `docs/official_docs/02-personas-and-journeys.md` — Automation Builder, Fleet Operator.

