# ADL-20b — KPI production: event lineage, cohort và denominators

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE analytics + FE / product + independent QA |
| Dependencies | Schema design D1; integration 07/09/13a/13b/14/06 |
| Deliverable | Event dictionary, versioned KPI queries/API/UI, fixture reconciliation và cohort report |

## 2. Source/gap
Execution steps/outcomes có runtime source; funnel service/assistance/cohort chưa defined. Do not count bounded UI task-log; query persisted source rows. Không report ≥80%/≥95% nếu không đo denominator/cohort thật.

## 3. Measurement contract
- self_serve_onboarding numerator: unique eligible paid campaigns đạt readiness trong measurement cutoff không được operator hoàn tất required input/approval hộ; denominator: unique paid campaigns đủ input thuộc cohort/window đã freeze.
- run_with_trace numerator: unique terminal executions có persisted step log và terminal outcome; denominator: tất cả terminal executions trong cohort/window, bao gồm blocked/cancelled/error nếu dùng Execution terminal enum. Product ký inclusion/exclusion trước pilot.
- Assisted event có actor/type/reason; việc operator review evidence theo service policy khác “hoàn tất hộ onboarding”, classification phải explicit để không làm đẹp KPI.
- Window dựa server timestamps, cohort identity/list/cutoff versioned; event id dedup, late event reconciliation, zero denominator N/A. Hiển thị numerator/denominator, sample size, window, query version; thresholds không tự là proof thống kê.

## 4. Bước làm
1. Product ký event dictionary, eligible/cohort/assistance/terminal definitions và window timezone.
2. Emit server payment/readiness/outcome transitions transactionally; client navigation events optional/consent-scoped sans PII.
3. Implement dedup/reconciliation queries + fixtures tính tay; counters không lấy browser click làm conversion success.
4. API/UI KPI details, query version and data freshness/missing warnings.
5. Freeze protocol trước 12; collect real cohort, compare independent SQL.

## 5. Acceptance
- [ ] AC1: definitions/cohort/exclusions signed và versioned trước đo.
- [ ] AC2: exact numerator/denominator query reproducible, dedup đúng.
- [ ] AC3: missing logs/assisted users không counted như đạt chuẩn.
- [ ] AC4: late/window/tenant events handled và zero denominator N/A.
- [ ] AC5: dashboard/API phân biệt fixture và real cohort; measurement protocol/evidence handoff sang 12/20c, không hiển thị threshold đạt khi chưa đo.

## 6. Test matrix
| ID | Setup/action | Expected |
|---|---|---|
| 20b-T1 | 2 eligible paid, 1 assisted completion | Self-serve 1/2 theo classification signed |
| 20b-T2 | Terminal outcome missing step log | Excluded numerator, included denominator |
| 20b-T3 | Duplicate/replayed conversions | Unique counts unchanged |
| 20b-T4 | Late/boundary event + different org | Cohort/window correct, no cross-org rollup |
| 20b-T5 | Empty cohort + operator reviewer-only action | N/A; assistance classification đúng |
| 20b-T6 | Chưa có real cohort, chỉ fixture test | UI/API không claim real KPI đạt; protocol handed off 12/20c |

## 7. Review và DoD
Product ký definitions, QA tính tay fixtures+SQL source, security review event privacy. Evidence query version/cohort IDs private, counts diff and UI. Feature DONE after AC1–5 và T1–6 PASS; real cohort measurement chạy tại 12/20c, status chưa đo phải rõ, không tuyên bố threshold đã đạt.
