# ADL-21 — Production infrastructure, recovery và on-call readiness

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production G1/G3 mandatory / BLOCKED_DECISION: capacity/SLO/RPO/RTO |
| Owner / review | DevOps + DB/runtime maintainers / security + independent QA + operator |
| Dependencies | 00 layout; design D1; rehearsal 04/09/16/17/18b/19b integrated |
| Deliverable | Reproducible deploy/CI, dependency readiness, metrics/alerts, backup restore/rollback proof và runbooks |

## 2. Source/research boundary
Backend/Temporal/storage/relay/payment are runtime dependency surfaces documented in task source map; chưa kiểm deployment infrastructure hiện tại đủ production. D1 inventory actual config/CI/manifests/workers/network/storage backup và bổ sung paths/evidence trước thay đổi; không thiết kế cloud topology dựa đoán hoặc giữ status PASS chỉ vì có YAML.

## 3. Operational contract
- Product/ops sign supported concurrent campaigns/devices, jobs/minute, artifact size/retention, SLO endpoints/dispatch lag, RPO/RTO, alert thresholds và escalation rota. Numbers **UNVALIDATED** cho tới measured rehearsal.
- Immutable build/commit, schema version và config refs; secrets provider injection, no plaintext config/git/log. Deploy API/worker/relay compatible protocol versions, rollback support explicit.
- Health liveness khác readiness; new paid start/dispatch disabled khi encryption/provider/storage/worker health không đủ, existing jobs controlled drain/recovery.
- Backup DB + private artifact metadata/objects + authorized key recovery; verify restore matches manifests and financial/slot records.
- Metrics alerts: queue/dispatch lag, terminal failed/blocked/missed, claim leaks, farm/quarantine, uploads/signed URL failures, webhook inbox/reconciliation lag, report jobs and cleanup. Alert phải nhận được, có actionable runbook/owner.

## 4. Bước triển khai
1. Inventory topology/config/CI/quotas và staffing; sign operational targets/decision records.
2. CI tests/schema/client/i18n, reproducible staging deployment, migration runner locks và recovery plan.
3. Configure dashboards/alerts/redaction/retention/correlation; simulate trigger và confirm delivery.
4. Backup/restore copied production-like data, key authorization và object availability; measure RPO/RTO.
5. Rehearse rolling deploy/rollback with active outbox/payment inbox/claims; forward DB recovery nếu irreversible migration.
6. Load at signed capacity and 12-Approved-Device-Target day; on-call handover/runbooks, production config validation before launch.

## 5. Acceptance
- [ ] AC1: topology/capacity/SLO/RPO/RTO signed, measured vs target diff clear.
- [ ] AC2: repeat deploy/start/migration compatible and recoverable.
- [ ] AC3: dependency outage/readiness fail closed + alerts delivered to owner.
- [ ] AC4: backup restore/reconciliation và rollback giữ payment/slot/evidence history.
- [ ] AC5: load/12-device checks và on-call/runbooks readiness proven.

## 6. Test matrix
| ID | Action | Expected / evidence |
|---|---|---|
| 21-T1 | Clean deploy/migrate full service smoke | Version/config/schema known; endpoints/workers healthy |
| 21-T2 | Restart/replay after commit pending delivery/payment | One intent/grant; recovery no double side effects |
| 21-T3 | DB/queue/storage/relay/provider outage từng dependency | Controlled readiness/blockers, delivered alerts, recoverable state |
| 21-T4 | Backup→restore→DB/artifact/report comparison | Manifest/ledger/slot counts match; measured RPO/RTO |
| 21-T5 | Rollback API/worker với active jobs/schema change | Compatibility verified; no lost order/history; drain safe |
| 21-T6 | Load signed capacity + 12 Approved Device Targets | SLO result reported honestly; no starvation/claim leaks |
| 21-T7 | Missing key/provider prod config + cleanup expired objects | Reject unsafe readiness; retain report-protected evidence |

## 7. Review và DoD
DevOps/DB/runtime reviewers inspect rehearsal; QA/operator execute independently, security key/backup access, billing ledger recovery. Evidence build/deploy hashes, commands/exit codes, alert receipts, restore reconciliation/timing, load results and runbooks. Fail→REWORK/BLOCKED_TARGET and rerun affected recovery; G1/G3 locked. DONE needs AC1–5; config file existence alone insufficient.
