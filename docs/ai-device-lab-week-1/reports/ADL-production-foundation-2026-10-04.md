# AI Device Lab — production foundation status (2026-10-04)

## Trạng thái trung thực

`LOCAL_IMPLEMENTATION_COMPLETE — PRODUCTION_ACCEPTANCE_BLOCKED`.

Không task nào cần Play account thật, payment provider thật, video MP4, 14 ngày chronology, production deploy hoặc reviewer sign-off được đánh dấu `DONE` bằng mock/local test. Yêu cầu capacity 12 thiết bị đang được miễn tạm thời theo WVR-12; invariant 12 lane/168 slot vẫn giữ nguyên. Không commit, push, deploy, charge, reserve máy production hoặc đổi third-party resource.

## Ma trận hoàn thành ADL-01 đến ADL-21

`Local implementation` nghĩa là schema/domain/API/UI/worker/test cần thiết đã có và verification local đang xanh. `Production DoD` chỉ đạt khi evidence môi trường thật và reviewer/owner bắt buộc trong task đã xác nhận; local fixture không thay thế các bằng chứng đó.

| Task | Local implementation | Production DoD | Phần còn thiếu để đóng task |
|---|---|---|---|
| ADL-01 | `COMPLETE` | `PASS` (`APPROVED_EMULATOR`) | Không còn device blocker; emulator evidence đáp ứng contract đã sửa |
| ADL-02 | `COMPLETE` | `PENDING_REVIEW` | integration QA và independent review trên evidence pack |
| ADL-03a | `PARTIAL` | `BLOCKED` | Play account đã consent, closed-track enrollment/install thật và provenance |
| ADL-03b | `COMPLETE` | `PENDING_REVIEW` | review evidence thật của participant/operator workflow |
| ADL-04 | `COMPLETE` | `PENDING_REVIEW` | integration QA/reviewer record |
| ADL-05 | `COMPLETE` | `PENDING_REVIEW` | capacity/operator review; DB race proof đã PASS trên PostgreSQL tạm |
| ADL-06 | `COMPLETE` | `BLOCKED` | readiness replay với entitlement, secret và 12 Approved Device Targets |
| ADL-07 | `COMPLETE` | `BLOCKED` | một service day chạy trên 12 Approved Device Targets; 14-day chronology thuộc ADL-12 |
| ADL-08 | `COMPLETE` | `PENDING_REVIEW` | customer/operator review trên dữ liệu thật và signed URL thật |
| ADL-09 | `COMPLETE` | `BLOCKED` | chốt provider/currency/refund, sandbox webhook signature và approved live smoke |
| ADL-10 | `COMPLETE` | `PENDING_REVIEW` | retest lineage replay trên execution/evidence thật |
| ADL-11 | `COMPLETE` | `BLOCKED` | publish/download report trên private bucket thật và reconciliation review |
| ADL-12 | `NOT_RUN` | `TIME_GATED` | đủ 14 khoảng 24 giờ thật, 168 outcomes, 12-account continuity và final review |
| ADL-13a | `COMPLETE` | `PENDING_REVIEW` | production auth/analytics review |
| ADL-13b | `COMPLETE` | `BLOCKED` | verified provider payment/return/recovery evidence từ ADL-09 |
| ADL-14 | `COMPLETE` | `BLOCKED` | provider checkout và readiness replay thật |
| ADL-15 | `COMPLETE` | `BLOCKED` | owner/security ký DEC-07 và human security review |
| ADL-16 | `COMPLETE` | `PENDING_REVIEW` (`PASS_APPROVED_EMULATOR`) | runtime/fault/parity evidence đã PASS; còn distributed-systems/security/QA sign-off |
| ADL-17 | `COMPLETE` | `BLOCKED` | private bucket upload/re-sign/delete thật, live redaction và MP4 proof nếu video được cam kết |
| ADL-18a | `COMPLETE` | `PENDING_REVIEW` | security review trên configured production path |
| ADL-18b | `COMPLETE` | `BLOCKED` | key/secret provider, recovery/rotation/retention policy được security ký |
| ADL-19a | `COMPLETE` | `PASS` (`APPROVED_EMULATOR`) | Canary, wipe-data, quarantine/drain/clean API và PostgreSQL audit đã PASS |
| ADL-19b | `COMPLETE` | `BLOCKED` | replace/extend/cancel/expiry rehearsal trên fleet và billing thật |
| ADL-20a | `COMPLETE` | `PENDING_REVIEW` | independent participant/product/UX/accessibility review |
| ADL-20b | `COMPLETE` | `BLOCKED` | signed KPI definitions và real cohort measurement; fixture không được tính đạt threshold |
| ADL-20c | `COMPLETE` | `NO_GO` | real evidence pack, mọi blocker đã đóng và signed human go/no-go |
| ADL-21 | `COMPLETE` | `BLOCKED` | signed SLO/RPO/RTO, staging deploy, alert và restore/rollback/load; 12-target evidence đang WAIVED |

Ban đầu `adb devices -l` không trả về thiết bị nào. Sau đó AVD `galaxy_note10_plus` được chạy headless/read-only với serial `emulator-5580`; ATX/UIAutomator2/STFService bootstrap thành công. Profile `ADL-01-SIMULATOR` đã `PASS` đủ `SIM-AC1`–`SIM-AC5`: positive assertion, negative assertion, capability preflight, relay offline, recovery, retry/capture separation, URL re-sign, cross-org denial và capture-error integrity. Ba warm runs tuần tự đều pass với trung bình `2.049 s`. Xem [báo cáo simulator E2E](ADL-01-simulator-e2e-2026-10-04.md). Theo Approved Device Target contract, ADL-01 được đóng `COMPLETE/PASS`; Play/provider/staging và multi-device gates vẫn được nghiệm thu ở task riêng.

## Phần đã triển khai local

| Phạm vi task | Artifact chính | Bằng chứng local |
|---|---|---|
| ADL-02, 18a | Durable wizard intake/revision, provider generation operation, fail-closed operation policy, exact scenario approval | provider outage/retry, secret-context rejection, purchase/ambiguous/stale/tamper/nested-policy tests |
| ADL-03b | Pseudonymous participation identity, append-only continuity events và tenant-scoped evidence/review form | 12 distinct identities, duplicate/lost/rejoin/late event tests; API/browser E2E proves the raw pseudonymous reference is never returned or rendered |
| ADL-04, 07 | ServiceCampaign/Lane/Slot/Attempt, 168-slot materializer, quota ledger | idempotent retry/materialization/quota replay tests |
| ADL-05, 19a | 12-device reservation, PostgreSQL exclusion constraint, hygiene/quarantine/drain state | 12-or-zero, dirty exclusion, release/drain tests; real PostgreSQL concurrent overlap race commits exactly one row |
| ADL-06 | Versioned readiness snapshot/checks, operational dependency gate, bounded redacted dependency probes và atomic start intent | direct API paid-but-blocked/no-start E2E; full ready path proves approval + entitlement + 12 healthy verified-clean reservations + fresh operations assessment starts once and emits one final funnel step; fresh/stale/timeout/unconfigured probe tests, latest-target selection and global concurrency bound |
| ADL-08 | Tenant-scoped three-source progress API và API-backed EN/VI workspace; paged lane/slot/attempt/evidence detail và masked participation list | API E2E verifies 12 lanes/14 slots, tenant isolation and no raw pseudonymous account ref; browser verifies drill-down plus explicit missing/unsupported evidence |
| ADL-09 | Provider-neutral order/payment/refund ledger, durable checkout intent, fenced refund dispatch + payment reconciliation workers, and sanitized customer/operator view | multi-tab checkout reuses one server-owned order/idempotency key; timeout-after-provider-accept reconciles by durable lookup key; verified duplicate settlement, forged event, refund-before-late-paid, amount/currency conflict enqueue, idempotent refund policy/cutoff, dispatch→authoritative reconciliation→revoke, stale-worker fencing, retry/dead-letter, bounded concurrency and cross-tenant/no-provider-ref API/browser tests; provider adapters remain fail-closed |
| ADL-10 | Immutable build guard, issue/retest lineage, assertion/build-gated verdict và operator API/UI | idempotent retest and fixed verdict tests; tenant-scoped create/list/retest API plus browser payload E2E |
| ADL-11 | Immutable report manifest/cutoff/hash, deterministic bounded PDF renderer, fail-closed private-storage publication, bounded report summary list và on-demand five-minute signed download URL | 168-row snapshot, deterministic PDF excludes source identity lists, publish refuses unconfirmed storage, idempotency/hash mismatch rejection, cross-tenant 404 and browser download request |
| ADL-13a, 14, 13b | Server-persisted campaign draft plus API-backed App→Scenario→Review→Payment→Readiness wizard; append-only privacy-bounded funnel ledger; server owns revision, approval, checkout intent, payment blocker and readiness | browser retry reuses the same opaque journey and event IDs; client attribution is allowlisted and rejects PII-like values; server emits deduplicated `app_submitted`, `scenario_approved`, `payment_completed`, `readiness_started` from authoritative transitions; checkout return polls server truth and never trusts redirect state |
| ADL-15 | Existing Casbin permission dependency + tenant resource filters on new API; explicit 35-route permission inventory | owner API path, operator read including sanitized reconciliation/funnel state, 403 create/manage/execute/update and cross-org 404 E2E; signed role matrix remains external review |
| ADL-16 | Farm job/outbox/inbox schema, fenced lease/ack worker, bounded retry/backoff, lifecycle metrics, order-independent terminal reducer, Temporal/fallback terminal monitors, versioned bounded event contract và observed-build pin | fallback live trên emulator dùng exact approved snapshot/device/execution IDs và observed Settings build 15/35; Settings→assert→Home PASS, outbox/job/attempt/execution/slot đồng bộ terminal; public terminal forge bị chặn; crash/expired lease, stale-worker fencing, uncertain side effect, cancel drain, duplicate/reordered event và Temporal/fallback parity tests PASS |
| ADL-17 | Evidence manifest with storage verification, explicit missing/unsupported, private five-minute re-sign endpoint, report pin và lifecycle-managed retention worker | API/browser E2E covers available URL, unconfirmed bucket `503`, missing `409`, gone `410`, cross-org `404` and no object-key leak; object-delete failure stays retryable; bounded cross-tenant batch/concurrency and PostgreSQL retention index are verified |
| ADL-18b | Encrypted secret reference, exact worker/job/device/op capability, TTL/revoke/resolve limit | canary ciphertext/audit, cross-device/revoke tests |
| ADL-19b | Lane assignment history, replace/drain, paid extension, cancel, due-only expiry sagas và operator lifecycle console | idempotency payload guards, active-run drain, 24-slot extension, frozen-report preservation, expiry cleanup; browser validates replace→complete, consented extension và guarded cancellation payloads |
| ADL-20a | EN/VI responsive prototype/state coverage | Playwright state, keyboard, mobile and performance checks |
| ADL-20b | Versioned KPI definitions, frozen cohorts, assistance ledger và immutable snapshots | 1/2 onboarding, 1/2 trace, late-event reconciliation, fixture-only/no-threshold assertions |
| ADL-20c | Immutable acceptance manifest covering all 28 task IDs and fail-closed evaluator | complete fixture stays `no_go`; missing evidence/reviewer/owner blockers enumerated |
| ADL-21 | Signed target/readiness data model, bounded redacted HTTP probe runner and dependency gate; operations rehearsal runbook | invalid target/freshness/dependency tests, timeout/redaction/latest-target/global-concurrency probe tests; runbook explicitly remains `UNVALIDATED` |

Migrations mới: `140`–`163` cùng prerequisite `141b` nằm giữa `141` và `142`. `141b` bổ sung candidate key `(org_id, id)` mà approval foreign key cần; `157` bổ sung retention index; `158` bổ sung fenced farm lease; `159` bổ sung durable payment reconciliation queue; `160` bổ sung tenant candidate key cho refund cùng durable refund dispatch outbox, lease và delivery index; `161` bổ sung một checkout intent duy nhất cho mỗi order, trạng thái checkout đã sanitize và provider lookup key dùng để reconcile timeout-after-accept; `162` bổ sung funnel ledger append-only, unique event/campaign-step và index `(org, campaign, source_occurred_at)`; `163` version hóa farm event, bind execution và thêm index `(org, execution, occurred_at)`. Tất cả là forward migration, không sửa checksum migration đã có. Các migration giữ history bằng `RESTRICT`, append-only audit/event tables và immutable snapshots. OpenAPI được export từ `backend/swagger/openapi.json`, đồng bộ sang `front-end/generate/openapi.json`, rồi regenerate `DeviceFarmApi.ts`.

## Verification hiện tại

- Backend AI Lab focused suite chạy lại ngày 2026-10-04: `84 passed, 1 skipped, 2 warnings in 19.09s`; skip là PostgreSQL E2E opt-in trong lần chạy SQLite. Suite gồm API wizard/workspace/checkout/funnel, participation, issue/retest, private evidence/PDF, RBAC, retention, farm outbox + Temporal adapter, payment reconciliation/refund dispatch, operational probes, timeout lookup, fencing, authoritative snapshots và global batch/concurrency/tenant-redaction regressions. Readiness positive-path E2E chạy đủ 12 thiết bị fixture, retry cùng command và chứng minh chỉ một scheduling intent cùng một `readiness_started`. Adapter E2E chạy outbox tới existing `ScenarioWorkflow`, pin exact snapshot/device/execution, dùng deterministic workflow ID và reconcile duplicate start mà không tạo workflow thứ hai. App factory/hardening cùng AI Lab lifecycle focused suite `29 passed, 2 warnings in 2.11s`; broad app/lifecycle baseline trước đó `133 passed in 15.04s`.
- PostgreSQL thật trên database tạm cô lập chạy lại ngày 2026-10-04: `tests/test_ai_lab_postgres_e2e.py` PASS `1/1` trong `3.55s`; fresh dev bootstrap áp dụng `163` migration tổng, đủ `24/24` migration AI Lab, `5/5` core constraint cộng unique funnel event/step constraints, `11/11` immutable trigger, retention/farm-delivery/payment-reconciliation/refund-dispatch/funnel indexes và fenced/checkout columns; bootstrap lần hai idempotent. Test mô phỏng schema pre-157/pre-158, riêng pre-159, pre-160, pre-161 và pre-162 bằng cách bỏ index/cột/table/constraint/migration marker rồi chứng minh forward migrations tạo lại chúng. Hai transaction đồng thời giữ cùng thiết bị/khoảng thời gian cho đúng `1 committed + 1 rejected`, chỉ `1/1` row tồn tại; interval rỗng bị từ chối. Database tạm được xóa sau test.
- Toàn repo chưa hỗ trợ production migration-only từ database hoàn toàn rỗng: migration legacy `001_variable_system.py` giả định bảng `campaigns` đã tồn tại. Đây là baseline limitation có trước AI Lab; đường nâng cấp từ database hiện hữu đã được kiểm chứng riêng ở trên.
- App factory và lifecycle regression sau khi thêm retention + farm-delivery worker: `133 passed in 15.04s`.
- Browser E2E chạy lại ngày 2026-10-04: `11 passed in 28.0s`, gồm production wizard HTTP-boundary flow, acquisition retry giữ nguyên journey/event IDs, server-verified checkout return, paged lane/participation/report workspace, sanitized payment reconciliation queue, private evidence re-sign/open, participation evidence, issue/retest, lifecycle operations và prototype/regression flows.
- Android simulator E2E ngày 2026-10-04: profile `ADL-01-SIMULATOR` `PASS` đủ `5/5` tiêu chí. Capability preflight chặn đúng khi thiếu U2; positive scenario qua backend API → relay → emulator pass `2/2`; negative assertion và relay offline trả `success=false`; recovery pass sau reconnect; focused retry/capture/TTL/cross-org suite `10 passed`; ba warm-path runs đều pass với trung bình `2.049 s`, tối đa `2.607 s`. Bằng chứng này đóng ADL-01 device acceptance theo Approved Device Target contract.
- Browser performance sample mới: `454` DOM nodes, không horizontal overflow, navigation `266.6 ms`, transferred `6,368,049` bytes trên dev server. Transfer size vẫn cần theo dõi/tối ưu trên production build.
- TypeScript `pnpm typecheck`, i18n checks và Prettier source viết tay: PASS sau generated-client sync.
- JEV project brain: TypeScript PASS, `27/27` harness tests, `16/16` context eval; knowledge check PASS với `52` documents, `28` tasks, `10` flows và `68` chunks. Đây là kiểm chứng routing/provenance của knowledge harness, không thay bằng chứng product/runtime.
- Production Next build trên `15.5.24`: PASS; wizard route `144 kB` First Load JS, workspace route `193 kB`. Build còn warning OpenTelemetry dynamic dependency và lint warnings legacy ngoài AI Lab.
- Frontend production dependency audit sau targeted upgrades: `0 critical`, `36 high`, `49 moderate`, `8 low` (từ `2 critical`, `91 high`, `90 moderate`, `11 low`). Next `15.5.24`, Axios `1.20.0`, lodash-es `4.18.1`, nanoid `5.1.16`, PostCSS `8.5.18`, Sharp `0.35.4`, Swagger generator `13.12.2`, ESLint config `15.5.24`; cảnh báo còn lại đi qua cây Excalidraw/Flowgram/Sentry/Next/tooling và chưa được gọi là sạch.
- Python compile và `git diff --check`: PASS.
- Full backend sau các thay đổi hiện tại: `3110 passed, 4 skipped, 62 failed` trong `271.83s`. Failure ở các nhóm legacy/unrelated đã dirty trước scope (platform defaults, device install mocks, popup/capture/templates/node contracts, U2/XPath, workspace revoke và live typing); không có test AI Lab fail.
- GitNexus được clean rebuild trước batch UI/API cuối: `43,747 nodes / 97,080 edges / 1,489 clusters / 300 flows`. Impact riêng: `ScenarioGenerationOperation` là `CRITICAL` (24 importer trực tiếp/278 phụ thuộc, bị khuếch đại bởi base-class import graph), `DeviceReservation` là `HIGH` (7/190), bootstrap prerequisite là `HIGH` (2 caller trực tiếp/5 phụ thuộc), còn các migration 143–150 là `LOW` (0 caller). `detect_changes --scope compare --base-ref main` cuối báo `CRITICAL` cho toàn dirty worktree: 536 files, 1,727 symbols, 244 flows; kết quả aggregate này gồm lượng lớn thay đổi có trước AI Lab và không được dùng để khẳng định an toàn production.

## Gate chưa thể đóng bằng code local

| Task/gate | Trạng thái | Bằng chứng còn thiếu |
|---|---|---|
| ADL-00 | `BLOCKED_INPUT` | maintainer xác nhận canonical layout/ownership và unrelated dirty files |
| ADL-03a | `BLOCKED_INPUT` | consented Play account + published closed track + enrollment/install observation |
| ADL-09 | `BLOCKED_DECISION` | provider/currency/refund policy, sandbox signature integration, approved live smoke |
| ADL-12 | `TIME_GATED` | 14 khoảng 24 giờ thật, 12 account continuity và final reconciliation |
| ADL-16 | `PENDING_REVIEW` | distributed-systems/security/QA/operator ký live fallback identity chain, uncertainty và supported-engine evidence |
| ADL-17 | `BLOCKED_DECISION` | xác nhận bucket private + live upload/re-sign/delete và video commitment/MP4 capture/playback trên thiết bị hỗ trợ |
| ADL-18b | `BLOCKED_DECISION` | secret provider/key recovery/retention policy được security ký |
| ADL-20a | `PENDING_REVIEW` | participant/product/UX/accessibility review độc lập |
| ADL-20c | `REVIEW_GATED` | real evidence pack và signed human go/no-go |
| ADL-21 | `BLOCKED_TARGET` | signed SLO/RPO/RTO, staging deploy, alert receipt và backup restore/rollback/load rehearsal; capacity 12 target đang WAIVED |

## Việc local còn phải hoàn thiện trước production candidate

1. Nối provider adapter thật sau quyết định billing và secret provider; giữ checkout/refund/reconciliation/credential jobs fail-closed tới khi có cấu hình hợp lệ, webhook signature sandbox và approved live smoke.
2. Production wizard, provider-neutral checkout/return, lane/attempt/evidence detail, masked participation evidence/review, issue/retest, operator lifecycle và report render/publish/list/download đã nối API. Prototype vẫn là acceptance spec cho các view cần external provider/device evidence.
3. Retention, farm-outbox, refund-dispatch, payment-reconciliation và operational-probe worker local đã có bounded batch/concurrency, tenant context, lifecycle shutdown, metrics, fenced ack và retry/backoff. Farm sink đã nối existing Temporal `ScenarioWorkflow`; fallback dùng cùng snapshot/policy/reducer và đã chạy live trên Approved Emulator Target. Còn independent review farm evidence, đăng ký payment/refund/probe adapters của môi trường đã chọn, xác nhận bucket policy private, chạy upload/re-sign/delete thật, xác nhận alert delivery và chạy deploy/restore/rollback/load rehearsal.
4. Hoàn tất explicit RBAC/audit matrix đã được owner ký và negative tests cho từng action nhạy cảm.
5. Trong thời gian WVR-12 còn ACTIVE, chạy pilot bằng Approved Device Target hiện có; 14-day chronology và acceptance pack vẫn chỉ dùng evidence refs đã kiểm chứng và reviewer thật.
