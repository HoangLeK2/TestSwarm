# Delivery register — dependencies, decisions và evidence

## 1. Cách giao task

Một task chỉ được giao IMPLEMENTING sau DESIGN_REVIEW và input/contract bắt buộc đã chốt. Mỗi file có owner **vai trò**, chưa có người nhận; D1 điền tên, estimate giờ design/build/test/review, thời điểm bắt đầu/kết thúc và capacity. Không mặc định một vai trò là một người hoặc 28 task chạy song song. Register này chưa phải lịch khả thi đã được duyệt.

Thiết kế chung D1: 04/10 schema build/run; 15 role matrix; 18a policy; 16 job/event; 17 capture/retention; 20b metric definitions; 21 topology/SLO. Có thể thiết kế đồng thời theo interface; không đóng integration khi component dependency còn missing.

## 2. Integration sequence (không phải ngày cố định)

| Gate | Tasks / đầu vào | Kết quả mới được bàn giao |
|---|---|---|
| A — Baseline | 00; 20a UX chạy độc lập | Canonical imports/test/migrations/client; reviewed screen/state spec |
| B — Foundation | 01 → 03a/19a; 01+20a → 02; 02 contract → 18a; 02+03a → 03b | Approved Device Target evidence, hygiene rule, intake/approval, policy, participation ledger |
| C — Domain và financial | 02 → 04; 04+19a → 05; 04 → 09; 15 design sớm, integrate với resources | Campaign/slot identity, atomic reservation, verified billing, authorized actions |
| D — Runtime capabilities | 01+04+05+18a → 16; 16+18a → 18b; 16 → 17 (credential privacy phải 18b) | Durable jobs/events, secrets capability, media lineage/retention |
| E — Start/lifecycle | 03b+04+05+09+18b+15 → 06; 06+16 → 07; 19a+05+07+09 → 19b | Atomic start/resume, 168-slot scheduler/quota, replace/extend/cancel/drain |
| F — Customer views | 02+20a → 13a; 02+04+09+06+13a → 14; 13a+09+14+06 → 13b; 03b+07+17+15 → 08 | Complete landing/wizard/payment, three-progress dashboard và attempt detail |
| G — Quality/report | 04/10 build schema đã chốt A/B; 07+08+17+09 → 10 integration; 07+08+10+17+15 → 11; 07+09+06+13/14 → 20b integration | Issue/retest/cost lineage, immutable report/PDF và audited KPI instrumentation |
| H — Production candidate | A…G + 21 deploy/restore/rollback/load | G1 functional/operational evidence, thiếu một task thì no candidate pass |
| I — Chu kỳ và launch | H + 20b protocol → 12 (14 ngày thật); 12 + mọi task → 20c | G2 cycle evidence rồi G3 signed launch decision |

Không có dependency `12 → 20c → 12`. Production billing activation cần live readiness/smoke của 09 trước paid launch; sandbox proof không bị gắn nhãn live. KPI đo thực cohort thuộc I; instrumentation tests thuộc G.

## 3. Decision register bắt buộc D1

| ID | Quyết định thiếu | Decision owner | Tasks bị chặn nếu chưa chốt |
|---|---|---|---|
| DEC-01 | Canonical migration/venv/import/OpenAPI ownership | Maintainer BE/FE | 00 và mọi code integration |
| DEC-02 | Provider/currency/refund/receipt và authorized live smoke | Product/finance | 09/13b/14/19b paid extension |
| DEC-03 | Account sourcing/consent/evidence confidence và freshness | Product/operator | 03a/03b/06/12 |
| DEC-04 | Service-day semantics/quota/retry/catch-up/retest pricing | Product/runtime | 04/07/10/19b/11 |
| DEC-05 | Video/capture/PII/retention và report access window | Product/security | 17/11/18b/21 |
| DEC-06 | Secret provider/key rotation/recovery/job capability TTL | Security/ops | 18a/18b/06/21 |
| DEC-07 | Role matrix, audit permissions và delegation | Product/security | 15 và mọi protected resource |
| DEC-08 | Traffic/device capacity/SLO/RPO/RTO/on-call | Operations/technical lead | 21/G1/G3 |
| DEC-09 | KPI cohort/assistance/terminal inclusion/sample definitions | Product/QA | 20b/12/20c |

Decision record phải có option chọn, lý do, owner/time/version và tasks impacted. Bảng chưa có trạng thái approved; không suy approved từ proposal trong task.

## 4. Mẫu evidence dùng trong từng task

| Test ID / AC IDs | Commit / env / schema | Tester / executed_at | Expected / observed | Status | Evidence refs | Finding / owner / retest |
|---|---|---|---|---|---|---|
| Điền trước chạy | Không dùng “latest” mơ hồ | Tên người/agent thực hiện thật | Observable state/count/result | NOT_RUN/PASS/FAIL/BLOCKED | Private log/API/SQL/browser/device-target/provider refs | Fix version và reviewer |

Implementer phải map **từng AC tới test IDs** trước AUTO_TEST, bổ sung case nếu AC chưa covered. Acceptance markdown trong file task chỉ tick khi test/evidence và review đạt; không dùng số lượng checkbox làm tiến độ khi tests còn NOT_RUN.

Review record: design reviewer/date/findings → automatic test outputs → integration QA replay → independent reviewer quyết định → DONE hoặc REWORK/BLOCKED. Không tự ghi reviewer đã ký; thiếu người review giữ PENDING_REVIEW.

## 5. Báo cáo deadline

Cuối mỗi checkpoint: completed task IDs + evidence, in-progress, blocked decisions/dependencies, remaining estimated hours/critical path, capacity có thực, earliest integrated finish và owner xử lý. Target một tuần giữ scope production, nhưng ngày giao chỉ được confirm sau sizing. Real 14-day cycle bắt đầu khi G1 đạt và started_at hợp lệ; timestamp phải có evidence chứ không mặc định ngày 08/10.
