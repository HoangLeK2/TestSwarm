# DF-T-04-008 — Campaign-device binding & fan-out

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-04-008 |
| **Title** | Campaign-device binding & fan-out (device-group → execution per device) |
| **Type** | `type:feature` |
| **Epic** | DF-E-04 — Campaign, Scenario & Execution |
| **Module** | DF-MOD-04 — Campaign, Scenario & Execution |
| **Priority** | P0 |
| **Story Points** | 5 |
| **Status** | `Backlog` |
| **Labels** | `module:campaigns`, `layer:backend`, `layer:contract`, `type:feature`, `persona:social-data-operator`, `persona:fleet-operator` |
| **Truy vết — FR refs** | FR-04-10, FR-04-11 |
| **Truy vết — UC refs** | UC-04-06, UC-04-07 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

FR-04-10 yêu cầu campaign run được phát tới "một danh sách device cụ thể hoặc tới một device group". FR-04-11 yêu cầu "cùng một scenario chạy độc lập trên từng device với effective config riêng". Hai FR này định nghĩa **fan-out** từ campaign → nhiều execution.

Hiện tại team chưa có cấu trúc thống nhất cho việc này. Ticket này định nghĩa: cách campaign bind tới target (device list / device group), cách per-device override variable được lưu, và cách dispatch service fan-out tại thời điểm trigger campaign.

Persona: Social Data Operator chọn fleet ở UI; Fleet Operator quản lý device group. Cả hai cần luồng dispatch ổn định, không leak state giữa device.

P0, SP 5. Phụ thuộc DF-E-02 cung cấp device entity và device_group entity + device claim/release contract.

## 3. Câu chuyện người dùng

> **Là** Social Data Operator
> **Tôi muốn** chọn campaign chạy trên một danh sách device cụ thể hoặc trên một device group, và đặt per-device override variable
> **Để** cùng scenario chạy với input khác nhau trên từng device mà không phải copy scenario

Persona phụ: Fleet Operator (quản trị device group).

## 4. Yêu cầu chức năng

- Hệ thống PHẢI cho phép campaign bind tới target theo 2 cách: `device_ids: [...]` (explicit) hoặc `device_group_ids: [...]` (resolve tại dispatch time).
- Hệ thống PHẢI snapshot danh sách thành viên device_group tại thời điểm dispatch — thay đổi membership sau đó KHÔNG ảnh hưởng campaign đang chạy.
- Hệ thống PHẢI cho phép `per_device_overrides`: map `{device_id: {var_name: value}}` lưu cùng campaign.
- Hệ thống PHẢI fan-out tạo 1 execution record per device tại dispatch.
- Hệ thống PHẢI validate trước khi dispatch: device tồn tại, device thuộc cùng org, device online (hoặc capacity offline OK theo policy), device có app cần thiết (gợi ý — không enforce vì test scenario có thể bao gồm install).
- Hệ thống PHẢI claim device qua API của DF-E-02 trước khi execution start — claim fail thì execution của device đó vào trạng thái `failed` ngay với reason `device_claim_failed`.
- Hệ thống PHẢI release device sau execution terminal (qua DF-E-02).
- Hệ thống PHẢI reject dispatch nếu target_count=0.
- Hệ thống NÊN cho phép `dispatch_strategy`: `parallel` (default — fan-out tất cả) hoặc `sequential` (chạy 1 device xong mới sang device kế tiếp).

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Fan-out theo device_ids — luồng thành công**

```
Given campaign C có scenario S, target { device_ids: [D1, D2, D3] }
When dispatch
Then 3 execution record tạo (E1 cho D1, E2 cho D2, E3 cho D3)
And mỗi execution có cùng scenario+version nhưng device_id khác
And device claim được gọi cho D1, D2, D3
```

**AC-2: Fan-out theo device_group**

```
Given device_group G chứa D1, D2 lúc dispatch
When dispatch campaign C target device_group_ids=[G]
Then snapshot 2 device (D1, D2), tạo 2 execution
And nếu sau đó thêm D3 vào G, campaign đang chạy KHÔNG fan-out tới D3
And next dispatch sẽ thấy D3
```

**AC-3: Per-device override resolve**

```
Given campaign C scenario default {kw:"global"} và per_device_overrides {D1:{kw:"d1-kw"}}
When dispatch
Then execution E1 trên D1 có effective var kw="d1-kw"
And execution E2 trên D2 có effective var kw="global"
```

**AC-4: Reject empty target**

```
Given campaign C có device_group rỗng (không thành viên) hoặc device_ids=[]
When dispatch
Then 400 "EMPTY_DISPATCH_TARGET", campaign giữ status (không vào running)
```

**AC-5: Device offline + policy reject**

```
Given target có D1 (online), D2 (offline)
And policy "require_online=true"
When dispatch
Then 400 "DEVICE_OFFLINE" với list [D2] hoặc partial dispatch (tuỳ flag)
And mặc định: reject toàn bộ với policy strict; flag allow_partial=true thì tạo execution chỉ cho D1
```

**AC-6: Device claim fail**

```
Given target D1 online nhưng đã được claim bởi campaign khác
When dispatch
Then execution của D1 tạo với status "failed", reason="device_claim_failed"
And các execution device khác vẫn dispatch bình thường
And campaign aggregator (DF-T-04-007) tính D1 vào tổng để evaluate completed/failed
```

**AC-7: Cross-org device reject**

```
Given D5 thuộc OrgB
When OrgA campaign target [D5]
Then 400 "DEVICE_NOT_FOUND"
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm device claim/release implementation — DF-E-02.
- KHÔNG bao gồm device group CRUD — DF-E-02.
- KHÔNG bao gồm scheduling — DF-E-05.
- KHÔNG bao gồm capacity planning / load balancing — DF-T-04-017 metrics + ops manual.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] `CampaignDispatcher.fanOut(campaign)` → list of execution records.
- [ ] Device validator (online, owner, capacity).
- [ ] Snapshot device_group membership.
- [ ] Per-device override merge logic vào VariableResolver (DF-T-04-002).
- [ ] Wire vào DF-E-02 device-claim API.

**Contract / API** (`layer:contract`)

- [ ] OpenAPI cho `POST /campaigns/{id}/dispatch` body `{ target, dispatch_strategy, allow_partial }`.
- [ ] Mã lỗi: `EMPTY_DISPATCH_TARGET`, `DEVICE_OFFLINE`, `DEVICE_NOT_FOUND`, `DEVICE_CLAIM_FAILED`.

**Database / Migration** (`layer:db`)

- [ ] Bảng `campaign_targets` (campaign_id, kind, ref_id) — snapshot device list per dispatch.
- [ ] Cột `per_device_overrides` JSONB trên campaign.

**Documentation** (`layer:docs`)

- [ ] Diagram fan-out trong `docs/modules/campaigns.md`.
- [ ] Doc per-device override syntax.

**Test** (`layer:test`)

- [ ] Unit test fan-out logic.
- [ ] Integration test với DF-E-02 device service mock.
- [ ] Test snapshot không bị affect khi group thay đổi.
- [ ] Test concurrency: 2 campaign dispatch cùng device → claim conflict.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-04-008-01 | Positive | C target [D1,D2,D3] online | Dispatch | 3 execution tạo, 3 claim call |
| TC-DF-T-04-008-02 | Positive | C target device_group G={D1,D2} | Dispatch | 2 execution, snapshot G membership |
| TC-DF-T-04-008-03 | Positive | per_device_overrides={D1:{kw:"v1"}}, scenario default kw="g" | Dispatch | E1 effective kw="v1", E2 effective kw="g" |
| TC-DF-T-04-008-04 | Negative | target=[] | Dispatch | 400 "EMPTY_DISPATCH_TARGET" |
| TC-DF-T-04-008-05 | Negative | D5 thuộc OrgB | OrgA dispatch target [D5] | 400 "DEVICE_NOT_FOUND" |
| TC-DF-T-04-008-06 | Edge | D2 offline, policy strict | Dispatch | 400 "DEVICE_OFFLINE" list [D2] |
| TC-DF-T-04-008-07 | Edge | D1 đã claim bởi campaign khác | Dispatch | E1 status="failed" reason="device_claim_failed", D2/D3 vẫn dispatch |
| TC-DF-T-04-008-08 | Edge | Device_group G membership thay đổi giữa dispatch | Add D3 vào G sau dispatch | Campaign đang chạy không thêm D3; next dispatch thấy D3 |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-04-006, DF-T-04-007 (FSM dispatch trigger), DF-E-02 (device entity, claim/release API).

**Chặn:** DF-T-04-010 (execution runtime cần input từ fan-out).

**Phụ thuộc giữa Epic:** DF-E-02 phải cung cấp `device.claim(device_id, owner_token)` và `device.release()` API trước.

**Rủi ro:**

- **Snapshot group: implementation phải atomic:** dùng SELECT FOR UPDATE hoặc copy-on-dispatch snapshot.
- **Race condition device claim:** DF-E-02 chịu trách nhiệm idempotency claim; ticket này chỉ propagate fail.
- **Per-device overrides phình to:** giới hạn payload campaign ≤ 5MB.

## 10. Điều kiện hoàn thành

- [ ] Code merged, CI pass.
- [ ] Test coverage ≥ 80%.
- [ ] Integration test với device service mock pass.
- [ ] Doc fan-out diagram updated.
- [ ] Telemetry: metric `campaign.dispatch.targets.count`, `campaign.dispatch.claim_fail.count`.
- [ ] Code review ≥ 1 approve (kèm DF-E-02 owner review claim contract).
- [ ] Release notes.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [04-campaigns-scenarios-executions.md](../../official_docs/modules/04-campaigns-scenarios-executions.md) — FR-04-10, FR-04-11, mục 5.1 (sequence dispatch).
- **Module 02 spec:** [02-devices-and-control-plane.md](../../official_docs/modules/02-devices-and-control-plane.md) — device claim contract.
- **Thuật ngữ:** Dispatch, Device, Per-device override.
