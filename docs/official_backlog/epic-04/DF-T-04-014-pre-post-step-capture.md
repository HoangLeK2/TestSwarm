# DF-T-04-014 — Pre/post step capture & artifact attachment

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-014 |
| **Title** | Pre/post step capture (screenshot + hierarchy snapshot) & artifact attach |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P1 |
| **Story Points** | 5 |
| **Status** | `Done` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:automation-builder`, `persona:social-data-operator` |
| **Truy vết — FR refs** | FR-04-14, FR-04-19 |
| **Truy vết — UC refs** | UC-04-11, UC-04-12 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

Đặc tả module mục 5.4 mô tả pre/post capture là **invariant** của step dispatch — không phải tuỳ chọn người dùng yêu cầu mỗi lần, mà default ON, chỉ tắt khi user explicit. Đây là khác biệt với công cụ test generic: Device Farm đảm bảo evidence audit ngay cả khi user không cấu hình.

Persona Social Data Operator UC-04-12 cần artifact attach để báo cáo cho khách hàng B2B. Automation Builder UC-04-11 cần screenshot tại điểm fail để debug nhanh.

KPI mục 9: "Tỷ lệ execution có pre/post capture artifact đầy đủ ≥ 99%". Ticket này hiện thực để đảm bảo KPI.

P1. Phụ thuộc DF-E-02 (device transport có lệnh screenshot + hierarchy_dump) và DF-E-06 (artifact store).

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** mỗi step trong execution có artifact pre và post capture (screenshot + hierarchy XML)
> **Để** truy vết được state device tại mỗi bước khi báo cáo khách hàng B2B hoặc khi debug step fail

Persona phụ: Automation Builder (debug khi UI nền tảng thay đổi).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI mặc định ON pre và post capture cho mọi step — trace FR-04-14.
- Hệ thống PHẢI cho phép step config tắt qua `pre_capture: false` / `post_capture: false`.
- Hệ thống PHẢI capture qua DF-E-02 transport: screenshot (PNG) + hierarchy (XML).
- Hệ thống PHẢI upload artifact vào DF-E-06 artifact store, lưu reference vào execution_step.
- Hệ thống PHẢI gán artifact metadata: execution_id, step_id, attempt_index, type (pre/post/fail), captured_at, device_state_summary.
- Hệ thống PHẢI capture ngay khi step fail (snapshot UI tại điểm fail — FR-04-19) — phục vụ debug DLQ.
- Hệ thống PHẢI thực hiện capture async (không block step dispatch chính) khi không phải fail-snapshot.
- Hệ thống PHẢI compress screenshot ≤ 200KB (quality vừa đủ) để giảm chi phí storage.
- Hệ thống PHẢI fail-soft: nếu capture lỗi, log warning nhưng KHÔNG fail step chính (trừ khi user config `require_capture=true`).
- Hệ thống PHẢI cho phép org-level config: throttle capture (vd chỉ capture mỗi 3 step) để giảm chi phí.
- Hệ thống NÊN dùng dedup khi screenshot không đổi (hash compare) — chỉ lưu reference tới snapshot cũ.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Default ON — luồng thành công**

```
Given step config không có pre_capture/post_capture (default)
When step chạy
Then 2 artifact tạo: pre và post
And artifact_ref lưu vào execution_step
And captured_at đúng
```

**AC-2: Tắt explicit**

```
Given step config { pre_capture: false }
When step chạy
Then chỉ post artifact tạo, không pre
```

**AC-3: Step fail — capture snapshot**

```
Given step S fail (element không tìm thấy)
When step fail
Then artifact type="fail" tạo trước khi mark step failed
And DLQ entry tham chiếu artifact này (DF-T-04-012)
```

**AC-4: Capture lỗi — fail-soft**

```
Given device temporarily không respond hierarchy_dump
When step chạy
Then step chính vẫn chạy bình thường
And artifact pre capture warning log, artifact_ref null
And metric capture.failure.count tăng
```

**AC-5: Require_capture=true**

```
Given step S config { require_capture: true }
And capture fail
When step chạy
Then step S fail với reason="capture_required_failed"
```

**AC-6: KPI 99% capture coverage**

```
Given chạy 1000 execution, mỗi 5 step
When đo
Then ≥ 99% step có cả pre và post artifact (trừ scenario tắt capture)
```

**AC-7: Org throttle**

```
Given OrgA config capture_throttle=3 (capture 1 trong 3 step)
When chạy execution 9 step
Then 3 artifact pre/post tạo (step 1, 4, 7), 6 step còn lại skip
And metric ghi rõ skipped_by_throttle
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm artifact storage implementation (S3/MinIO) — DF-E-06.
- KHÔNG bao gồm OCR/AI vision trên artifact — DF-E-06.
- KHÔNG bao gồm artifact viewer UI — DF-E-11.
- KHÔNG bao gồm video capture / screen recording — lộ trình.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `CaptureService.captureBeforeStep(execution, step)` / `captureAfterStep`.
- [ ] Async dispatch (post-step) trừ fail-capture (sync).
- [ ] Throttle logic.
- [ ] Dedup hash compare.

**Contract / API** (`layer:contract`)

- [ ] Schema artifact_ref trong execution_step.
- [ ] Capture config schema (step-level + org-level).

**Database / Migration** (`layer:db`)

- [ ] Cột `artifacts_json` trong execution_step lưu array artifact_ref.

**Documentation** (`layer:docs`)

- [ ] Doc default capture behavior.
- [ ] Doc throttle config + cost guidance.

**Test** (`layer:test`)

- [ ] Unit test capture flow.
- [ ] Integration test với DF-E-02 transport mock + DF-E-06 store mock.
- [ ] KPI test: 1000 execution → ≥ 99% capture.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-014-01 | Positive | Step default config | Run step | 2 artifact pre/post lưu, metric coverage tăng |
| TC-DF-T-04-014-02 | Positive | Step pre_capture=false | Run step | Chỉ post artifact |
| TC-DF-T-04-014-03 | Positive | Step fail | Run | Artifact fail-type captured trước khi mark fail; DLQ ref artifact đúng |
| TC-DF-T-04-014-04 | Negative | Device không respond capture, require_capture=true | Run | Step fail "capture_required_failed" |
| TC-DF-T-04-014-05 | Negative | Artifact store trả lỗi 500 khi upload post-capture | Run step | Execution fail có mã lỗi rõ, không mark step success khi artifact bắt buộc chưa lưu |
| TC-DF-T-04-014-06 | Edge | Screenshot trùng hash với capture trước | Capture | Dedup — chỉ lưu ref tới artifact cũ, không upload duplicate |
| TC-DF-T-04-014-07 | Edge | 1000 execution KPI test | Run + đo | ≥ 99% coverage (loại trừ scenario tắt) |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-010 (runtime hook), DF-E-02 (screenshot + hierarchy command), DF-E-06 (artifact store API).

**Chặn:** DF-T-04-012 (DLQ artifact ref), DF-T-04-018 (preview cần artifact đầy đủ), DF-E-11 (UI artifact viewer).

**Rủi ro:**

- **Chi phí storage:** với fleet lớn, artifact phình → throttle + dedup; có thể cold storage cho execution > 30 ngày.
- **Capture chậm làm step delay:** async post-capture giảm tác động; pre-capture vẫn sync nên cần DF-E-02 trả nhanh.
- **Hierarchy XML có thể chứa PII:** DF-E-06 đảm nhiệm redaction; ticket này không xử lý trực tiếp.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] KPI test 99% coverage pass on staging với 1000+ execution.
- [ ] Doc capture behavior + throttle published.
- [ ] Telemetry: capture.success/fail/throttled count.
- [ ] Code review ≥ 1 approve + 1 review từ DF-E-06 owner.
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-14, FR-04-19, mục 5.4.
- **Module 06:** [06-content-extraction-artifacts.md](../../official_docs/modules/06-content-extraction-artifacts.md).
- **Module 02:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md).
- **Thuật ngữ:** Artifact.
