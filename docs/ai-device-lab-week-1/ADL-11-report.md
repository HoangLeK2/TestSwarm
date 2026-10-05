# ADL-11 — Report/PDF production: snapshot, provenance, completeness

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | BE reporting + FE / QA independent reconciliation + product + security |
| Dependencies | 07/08/10/17/15; contract có thể thiết kế ngay sau 04 |
| Deliverable | Versioned report snapshot/worker/API, private PDF download, count reconciliation |

## 2. Source/gap
`backend/services/execution_trace.py` max events 500/steps 2000 per request; task-log/UI page không là tổng report. Query nguồn RunSlot/RunAttempt/ExecutionStep/ExecutionEvent và evidence manifest; render worker là chức năng mới phải chứng minh.

## 3. Contract
- Report snapshot: org/campaign, schema_version, created_at/builder, cutoff, source revisions/IDs, inclusion rules và manifest checksum.
- Cutoff nhất quán: DB snapshot/repeatable-read hoặc manifest materialization transactional; paginate stable ordered keys, không vừa đọc vừa lấy counts thay đổi.
- Counts: planned slots=168 theo plan; attempted/terminal/missed riêng với attempts; evaluated/pass/fail/inconclusive từ assertions. Include retries, superseded builds, replacements, quota and issue verdicts theo definitions versioned.
- Play participation section riêng evidence grade/gaps; no Google approval/eligibility inferred. Missing/expired media accounting cho từng ref.
- PDF và API từ **cùng snapshot**, không query live lần hai; private immutable output/object key/checksum. Correction tạo version mới, old report còn audit; retention policy giữ artifact theo contract.

## 4. Bước làm
1. Chốt count/inclusion rules với 07/10/20b và schema manifest; viết fixtures vượt giới hạn UI.
2. Snapshot job idempotent keyed campaign+cutoff+schema/version; trạng thái queued/building/ready/failed rõ và retry không duplicate outputs.
3. Paginate source records, validate references/missing, render PDF EN/VI font/layout, checksum lưu private storage.
4. Authorized list/read/download cấp signed URL lúc đọc; expiry/revoked role không cấp URL mới.
5. Independent SQL reconciliation và PDF visual QA; cancellation/outage/missing object tests.

## 5. Acceptance
- [ ] AC1: toàn bộ counts reconcile source rows ở cutoff, không truncate theo UI.
- [ ] AC2: report và PDF cùng manifest/hash; snapshot immutable.
- [ ] AC3: thiếu evidence/unknown participation hiện đầy đủ, không false claims.
- [ ] AC4: private scoped downloads, no secrets/PII trong output.
- [ ] AC5: worker retries/correction/version/retention có audit và recovery.

## 6. Test matrix
| ID | Setup/action | Expected / evidence |
|---|---|---|
| 11-T1 | >500 events/>2000 steps + 168 slots/retries | SQL vs manifest all rows/counts match |
| 11-T2 | Concurrent run terminal trong lúc snapshot | Consistent cutoff; PDF/API không khác counts |
| 11-T3 | Missing/deleted/expired artifact | Explicit missing count/refs; not fabricated media |
| 11-T4 | Worker crash/upload retry | One stable output/version or visible failed state |
| 11-T5 | Org B/revoked role download | Reject before URL grant |
| 11-T6 | Render EN/VI long text/pages + injected secret | No truncation/overflow/secret; QA page review |
| 11-T7 | Correction sau freeze | New version; old checksum/counts unchanged |

## 7. Review và DoD
QA reviewer độc lập chạy SQL, product kiểm truthful claims, security download/redaction; render reviewer xem PDF từng page. Lưu fixture/count diff, snapshot refs/hash, PDF QA, job logs và commands. Fail → report version chưa publish, REWORK/rebuild/new version nếu already published. DONE cần AC1–5; report cuối kỳ cohort thật thuộc 12/20c.
