# ADL-18b — Job-scoped secrets, ephemeral capability và revocation

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / BLOCKED_DECISION: provider/key recovery policy |
| Owner / review | BE security + runtime / security reviewer + QA |
| Dependencies | 18a, 16 schema/consumer contract; 15 role policy; 21 key recovery interface |
| Deliverable | Encrypted credential vault/reference API, scoped resolution, TTL/revoke/audit, leak proof |

## 2. Source/gap
`backend/common/crypto.py` mã hóa account password không cung cấp customer job capability/TTL. Execution variables/meta/AI prompt/workflow payload không được lưu raw secret. Key/provider decision phải ký trước code, không tự giả định dùng farm account table.

## 3. Contract
- SecretRecord org/campaign, encrypted value/provider handle, type, key_version, created/expiry/revoked_at và retention policy; reference opaque, cannot guess/expose value.
- JobCapability binds org/campaign/lane/run_attempt/device/allowed secret op + expires_at; only authenticated worker/relay principal đúng job resolve. One-time/bounded reuse policy explicit để retry không leak/cản job hợp lệ.
- Resolve just-in-time; no raw secret in browser/tool response/event/workflow durable state. Worker memory scope minimized, logs/errors/redaction and screenshots covered 17.
- Cancel/expiry revokes capability; deletion/rotation/key-recovery audited. Revocation không chứng minh secret đã nhập bị xóa trên Approved Device Target: hygiene 19a/b required.

## 4. Bước làm
1. Security sign storage/key recovery/TTL/retention/provider interface and threat boundary.
2. Implement create/update/revoke reference endpoints auth+encryption, worker resolve identity checks.
3. Integrate job references/capabilities in 16 and readiness 06; revoked/missing → blocker, no fallback plaintext.
4. Scrub runtime exceptions/debug/event/capture channels; deletion/revoke lifecycle and audit without value.
5. Canary leak tests, expiry/rotation/outage and Approved Device Target login media review.

## 5. Acceptance
- [ ] AC1: ciphertext/private handles only persisted; no raw secret through customer APIs.
- [ ] AC2: resolve matches exact worker/job/org/device/TTL scope.
- [ ] AC3: revoke/cancel/expiry denies future resolve and retention deletes correctly.
- [ ] AC4: rotation/provider outage fail closed/recoverable with reason.
- [ ] AC5: canary absent logs/events/workflow/artifacts/report and sensitive screens.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 18b-T1 | Authorized job resolve within TTL | Value only inside permitted runtime, audit ref only |
| 18b-T2 | Different org/device/attempt/worker | Denied, no raw error payload |
| 18b-T3 | Expired/revoked/cancelled capability | Resolve denied; retry does not resurrect |
| 18b-T4 | Crash/retry/provider timeout/key rotate | Explicit blocked/retry; no durable plaintext |
| 18b-T5 | Canary inspection DB/log/event/AI/media/report | No leakage in any channel |
| 18b-T6 | Retention delete + encrypted backup recovery | Policy compliant, recovery authorized/audited |

## 7. Review và DoD
Security signs worker identity/TTL/key policy and independently canary-scans outputs; QA replays boundary cases, operator verifies media/hygiene handoff. Evidence config validation sans keys, private audit refs, test logs and screenshot review. Leak → block credential jobs/REWORK/rerun full leakage suite. DONE needs AC1–5; missing provider decision stays BLOCKED.
