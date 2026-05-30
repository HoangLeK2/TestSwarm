# DF-T-11-014 — Notification center UI + unread count + deep link

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-014 |
| **Title** | Notification center UI — panel, unread count, deep link, mark-as-read |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P2 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:social-data-operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-11-13 |
| **Truy vết — UC refs** | UC-11-11 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Notification panel ở thanh điều hướng (mục 5.5 module 11) cho phép user thấy ngay khi có việc cần xử lý — campaign fail, device offline, schedule miss, account checkpointed. KPI: unread count refresh khoảng hợp lý; click notification mở deep link đúng tài nguyên gốc.

Lưu ý: route `/api/notifications/unread-count` hiện thuộc nhóm parity gap (mục 8 module 11) — có thể phải qua Next API proxy cho tới khi generated client cập nhật.

## 3. Câu chuyện người dùng

> **Là** mọi persona vận hành
> **Tôi muốn** thấy unread notification count nổi bật + panel list + click mở deep link
> **Để** can thiệp ngay khi có việc cần thay vì lướt log thủ công.

## 4. Yêu cầu chức năng

- Header dashboard PHẢI có icon notification kèm badge unread count — trace FR-11-13.
- Click icon mở panel list notification với: title, summary, severity, time, link target — trace FR-11-13.
- Unread count refresh ở khoảng hợp lý (10-30 s polling) — trace FR-11-13.
- Click notification PHẢI mark-as-read + mở deep link tới tài nguyên gốc (campaign, execution, schedule, device) — trace FR-11-13.
- Action "Mark all as read" PHẢI cập nhật UI ngay (optimistic) + đồng bộ backend — trace FR-11-13.
- Filter severity + time range trong panel.
- Nếu route chưa trong generated client, dùng Next API proxy có ghi chú lý do (FR-11-03).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Unread badge cập nhật**

```
Given org có 3 unread notification
When user login
Then badge hiển thị 3
When notification mới đến (polling refresh)
Then badge tăng kịp thời (< 30 s)
```

**AC-2: Click mở deep link**

```
Given notification "Campaign C1 failed on 5 devices"
When user click
Then chuyển sang /dashboard/campaigns/C1/monitor filter status=failed
And notification mark-as-read
```

**AC-3: Mark all as read optimistic**

```
Given badge = 10
When user click "Mark all as read"
Then badge → 0 ngay lập tức
And backend confirm trong < 2 s
When backend fail thì rollback badge + toast error
```

**AC-4: Next API proxy có comment**

```
Given route unread-count chưa trong generated client
When inspect app/api/notifications/unread-count/route.ts
Then file có comment "Reason: pending OpenAPI sync (issue #...)"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm push notification ngoài dashboard (email, Slack) — DF-E-09.
- KHÔNG bao gồm bulk delete notification.
- KHÔNG bao gồm filter custom phức tạp.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Component badge + panel.
- [ ] Polling hook unread-count.
- [ ] Deep link mapper theo target_type.
- [ ] Optimistic update.

**Contract / API** (`layer:contract`)

- [ ] Generated client hoặc Next API proxy với comment.

**Documentation** (`layer:docs`)

- [ ] UX doc.

**Test** (`layer:test`)

- [ ] Test polling.
- [ ] Test deep link mapping.
- [ ] Test optimistic rollback.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-014-01 | Positive | 3 unread | Login | Badge=3 |
| TC-DF-T-11-014-02 | Positive | Notification campaign fail | Click | Deep link đúng + mark read |
| TC-DF-T-11-014-03 | Positive | Mark all read | Click | Badge=0 optimistic |
| TC-DF-T-11-014-04 | Negative | Mark all backend fail | Quan sát | Rollback + toast |
| TC-DF-T-11-014-05 | Edge | 1000 notification | Open panel | Lazy load, không freeze |
| TC-DF-T-11-014-06 | Edge | Polling khi user idle | Quan sát | Vẫn chạy nhưng tần suất chậm hơn (back-off) |
| TC-DF-T-11-014-07 | Negative | target_type không support | Click | Toast "Cannot open" thay vì broken link |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-001, DF-T-11-002.

**Chặn:** Không.

**Phụ thuộc giữa Epic:** **DF-E-09**.

**Rủi ro:**

- **Polling load:** back-off khi idle.
- **Proxy parity gap:** issue tracking + regenerate client.

**Phụ thuộc bên ngoài:** Service notification DF-E-09.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Mỗi proxy có comment + issue tracking.
- [ ] Telemetry: counter notification_click, badge_refresh_latency.
- [ ] Code review ≥ 1 approve.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-13, §5.5](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [09-notifications-and-analytics.md](../../official_docs/modules/09-notifications-and-analytics.md).
- **Nhóm người dùng:** Tất cả persona vận hành.
- **Thuật ngữ:** Notification.
