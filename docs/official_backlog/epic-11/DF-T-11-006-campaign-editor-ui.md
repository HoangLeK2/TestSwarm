# DF-T-11-006 — Campaign editor + scenario flow editor UI

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-11-006 |
| **Title** | Campaign editor + scenario flow editor — `/scenario-flow/{id}` graph builder |
| **Type** | `type:feature` |
| **Epic** | DF-E-11 — Frontend & Dashboard |
| **Module** | DF-MOD-11 — Frontend & Dashboard |
| **Priority** | P0 |
| **Story Points** | 8 |
| **Status** | Backlog |
| **Labels** | `module:frontend`, `layer:frontend`, `type:feature`, `persona:automation-builder` |
| **Truy vết — FR refs** | FR-11-08, FR-11-09 |
| **Truy vết — UC refs** | UC-11-06, UC-11-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đây là surface đặc biệt nhất của DF-E-11: scenario flow editor (`/scenario-flow/{id}`) — graph builder cho Automation Builder dùng vẽ scenario thành node + edge + nhánh điều kiện. KPI module 11: mở editor trung vị < 3 s. Yêu cầu nghiệp vụ then chốt (mục 5.3 module 11): graph phải tương thích `ScenarioModel` backend — không thêm field riêng.

## 3. Câu chuyện người dùng

> **Là** Automation Builder
> **Tôi muốn** mở `/scenario-flow/{id}` vẽ scenario thành graph với node, edge, nhánh điều kiện, undo/redo
> **Để** thiết kế và bảo trì scenario tái sử dụng cho nhiều campaign mà không phải viết JSON tay.

## 4. Yêu cầu chức năng

- Trang `/scenario-flow/{id}` PHẢI load scenario hiện tại (nodes, edges, steps) — trace FR-11-08.
- Editor PHẢI cho phép: kéo node mới, vẽ edge, sửa step config, xóa node/edge — trace FR-11-08.
- Editor PHẢI hỗ trợ undo/redo trong phiên — trace FR-11-08.
- Lưu PHẢI gọi PUT scenario với payload tương thích `ScenarioModel` backend — trace FR-11-08 + cảnh báo 5.3.
- Editor PHẢI có nhánh điều kiện (if_element, branch by variable) — trace FR-11-08.
- Editor PHẢI hỗ trợ preview run scenario trên 1 device cô lập (link DF-E-04) — trace FR-11-08.
- Editor PHẢI mở < 3 s trung vị — KPI module 11.
- Editor PHẢI có validation client-side: edge phải nối node hợp lệ, không cycle (trừ loop hợp pháp), step config bắt buộc field — trace FR-11-08.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Mở editor và vẽ graph**

```
Given scenario S1 có 5 node, 4 edge
When user mở /scenario-flow/S1
Then graph render đầy đủ trong < 3 s trung vị
And user kéo thêm node, vẽ edge, sửa step
And toolbar undo/redo hoạt động
```

**AC-2: Lưu graph tương thích backend**

```
Given user edit xong + click Save
When request PUT scenario gửi đi
Then payload có schema tương thích ScenarioModel (nodes/edges/steps)
And backend trả 200 + scenario version mới
```

**AC-3: Nhánh điều kiện**

```
Given user thêm node "if_element"
When config selector + 2 nhánh true/false
Then graph hiển thị 2 edge từ if node
And lưu xong vẫn render đúng
```

**AC-4: Preview run**

```
Given scenario draft chưa save
When user click "Preview run" + chọn device A1
Then execution preview chạy → chuyển sang execution monitor
And không tạo campaign mới
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm scenario diff version — open question module 11.
- KHÔNG bao gồm selector pattern library — open question.
- KHÔNG bao gồm scenario template browser — DF-T-11-007.

## 7. Kế hoạch triển khai

**Frontend** (`layer:frontend`)

- [ ] Feature folder `scenario-flow/`.
- [ ] Graph library tích hợp (vd ReactFlow).
- [ ] Hook undo/redo.
- [ ] Step config form theo step type.
- [ ] Validation client-side.
- [ ] Preview run action.

**Contract / API** (`layer:contract`)

- [ ] Consume generated client GET/PUT scenario.

**Documentation** (`layer:docs`)

- [ ] Doc step type catalog + UI hint.

**Test** (`layer:test`)

- [ ] Test load scenario lớn (100 node) < 3 s.
- [ ] Test save payload schema.
- [ ] Test undo/redo.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-11-006-01 | Positive | Scenario 5 node | Mở editor | Render < 3 s |
| TC-DF-T-11-006-02 | Positive | Add if_element + 2 branch | Save | Persist + reload đúng graph |
| TC-DF-T-11-006-03 | Negative | Edge nối node không tồn tại | Save | Validation fail rõ |
| TC-DF-T-11-006-04 | Negative | Backend reject schema | Save | Error rõ với hint field sai |
| TC-DF-T-11-006-05 | Edge | Scenario 100 node | Mở | Render < 3 s p95 |
| TC-DF-T-11-006-06 | Edge | Cycle hợp lệ (loop step) | Save | Pass validation; cycle illegitimate bị warn |
| TC-DF-T-11-006-07 | Positive | Preview run trên device A1 idle | Click | Execution chạy + chuyển monitor |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-11-005.

**Chặn:** DF-T-11-007.

**Phụ thuộc giữa Epic:** **DF-E-04** — scenario CRUD + preview run.

**Rủi ro:**

- **Schema drift gây scenario lưu xong không chạy được:** test schema CI; validate sớm.
- **Render lag với scenario lớn:** virtualization graph + lazy load.
- **Undo/redo state bug:** test stress sequence.

**Phụ thuộc bên ngoài:** Graph library, scenario engine DF-E-04.

## 10. Điều kiện hoàn thành

- [ ] Code merged + CI pass.
- [ ] Coverage ≥ 80%.
- [ ] Test case map.
- [ ] Tài liệu cập nhật.
- [ ] Telemetry: histogram editor_open_ms, counter save_success/fail.
- [ ] Code review ≥ 1 approve + owner Epic-04 review schema.
- [ ] KPI mở editor < 3 s trung vị.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [11-frontend-dashboard.md FR-11-08, §5.3](../../official_docs/modules/11-frontend-dashboard.md).
- **Module liên quan:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md).
- **Nhóm người dùng:** Automation Builder.
- **Thuật ngữ:** Scenario flow editor, Scenario.
