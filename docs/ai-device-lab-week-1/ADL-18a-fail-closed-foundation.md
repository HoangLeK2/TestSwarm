# ADL-18a — Production policy gate và encryption fail-closed

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production security foundation / NOT_STARTED |
| Owner / review | BE security/runtime / security reviewer + QA |
| Dependencies | 00, 02 intake/approval contract; implementation can start in parallel |
| Deliverable | Versioned operation policy, credential intake gate, executor enforcement, denial/leak tests |

## 2. Source/gap
`backend/common/crypto.py` plaintext fallback when key absent; `is_encryption_enabled` reports key presence, không tự xác nhận key/provider usable. `backend/runtime/ai/ai_scenario.py` JSON parser không là authorization. Review scenario validator/preflight/executor entry points, not only UI.

## 3. Contract
- Production credential intake requires validated encryption/secret-store capability; absence/invalid key/provider failure rejects before DB write. Không silently dev fallback ở customer path.
- Policy keyed org/campaign/app/scenario version + permitted primitive/target/action class; purchase/ad click/production mutation/OTP bypass deny. Generic tap không được coi safe chỉ vì type được whitelist: validate target/scope approved, runtime ambiguous screen block.
- Policy enforced generation validation, approval, dispatch và executor; untrusted UI/XML/tool text không mở quyền.
- Credential needed nhưng 18b chưa available → job blocked; no plaintext variables/debug LLM input. Existing dev behavior chỉ giữ nếu deployment fence rõ và tests prove production path deny.

## 4. Bước làm
1. Inventory dangerous/ambiguous primitives, dispatch paths và secret handling; security sign versioned policy.
2. Validate key/provider startup và credential writes; prevent sensitive logging/AI debug dumps.
3. Approval/dispatch/executor shared policy evaluation + reason codes; policy change invalidates stale unsafe approval.
4. Add tests injected screen/goal/tool args/direct API and canary secrets.
5. QA run safe and denied scenario on permitted app, correlate zero forbidden tool invocation.

## 5. Acceptance
- [ ] AC1: missing/invalid key rejects before plaintext write.
- [ ] AC2: server deny applies all dispatch/execution entry paths.
- [ ] AC3: ambiguous/forbidden target not executed, reason observed.
- [ ] AC4: UI prompt injection cannot increase capabilities.
- [ ] AC5: secrets absent DB plaintext/events/logs/AI/debug responses.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 18a-T1 | No key/invalid key/provider unavailable | Reject credential input, no DB plaintext |
| 18a-T2 | UI XML asks purchase/unlock permissions | Policy deny; zero forbidden tool commands |
| 18a-T3 | Direct dispatcher/API altered allowlist | Server deny independent of hidden UI button |
| 18a-T4 | Generic tap target purchase/unknown screen | Deny/block despite primitive type allowed |
| 18a-T5 | Secret canary in errors/debug/log path | No exposure; redacted fields/assertions |
| 18a-T6 | Policy version changes after approval | Revalidation required; stale approval rejected |

## 7. Review và DoD
Security independently reviews entry point coverage and canary outputs; runtime reviewer target ambiguity behavior, QA negative proof. Evidence policy matrix, invocation logs, sanitized storage inspections/test commands. Forbidden action/leak → stop customer dispatch, REWORK and rerun boundary suite. DONE needs AC1–5; ephemeral secret integration belongs 18b.
