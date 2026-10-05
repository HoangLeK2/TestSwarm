# ADL-17 — Evidence manifest, private storage và retention production

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED; video contract BLOCKED_DECISION |
| Owner / review | BE media/storage / security + QA + operator |
| Dependencies | 01, 16; 15 access rules; 18b capture privacy |
| Deliverable | Attempt/step manifest, retention workflow, authorized media access, MP4 proof nếu committed |

## 2. Source/gap
`backend/services/execution/{epic06_capture_adapter,capture_service,step_store}.py`, `backend/services/content/{artifact_service,extraction/retention}.py` cung cấp capture/ref/retention primitives. Live streaming không chứng minh MP4 export; object key/re-sign có code nhưng needs live proof.

## 3. Contract
- EvidenceItem(org, campaign, run_attempt, execution, step_path/index, step_attempt_index, kind, object_key, content_type, captured_at, checksum, capture_error, status, retention_until).
- Status available/unsupported/missing/expired/deleted; capture success requires stored object verified, not URL string. Dedup checksum không làm mất linkage của distinct attempts.
- Screenshot/log required evidence policy per step; raw hierarchy/PII capture có scope/retention riêng. Credentials screen capture deny/mask validated, không chỉ scrub text logs.
- Object storage private, authorization trước URL grant/proxy; signed URL TTL không là object retention. 410 semantics khi gone; 403/404 policy tránh cross-org enumeration.
- Retention floor từ report contract; legal/manual pin nếu có yêu cầu; cleanup idempotent và audit, không delete object còn referenced active report. Video committed → MP4 time/run identity and playback tested.

## 4. Bước làm
1. Product/security ký capture kinds/retention/video/PII policy; estimate capacity/size.
2. Manifest persistence và linkage tới steps/run attempts; capture/store error separation, checksum verification.
3. Media read endpoint auth/re-sign/error codes; no bytes in workflow/event payload.
4. Cleanup worker retention/pin/report dependency và deletion tombstone; restore/readback behavior.
5. Fault/TTL/retry/large media tests và Approved Device Target capture/playback proof.

## 5. Acceptance
- [ ] AC1: evidence đúng step/run/attempt/build, old refs immutable.
- [ ] AC2: storage/capture failure và unsupported video có explicit status.
- [ ] AC3: private scoped reads/re-sign after TTL, accurate gone response.
- [ ] AC4: retention cleanup không vi phạm report access contract.
- [ ] AC5: video committed và screenshot/login redaction được live review.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 17-T1 | Two fail steps + retries/build v2 | Distinct correct refs/checksum; old evidence intact |
| 17-T2 | Storage timeout/corrupt upload | Missing/error; available chỉ sau verified object |
| 17-T3 | Reopen after signed TTL, org B grant | Fresh authorized URL; org B denied |
| 17-T4 | Expire/pin/report-reference cleanup replay | Protected refs retained; gone status/tombstone consistent |
| 17-T5 | Secret canary screen/login capture | No readable canary; sensitive media policy denies/masks |
| 17-T6 | MP4 recorded trên supported Approved Device Target | Duration/job identity matches; private playback, no stream-as-video |

## 7. Review và DoD
Storage/media reviewer validates lineage/retention, security privacy/URLs, operator+QA live playback/capture. Evidence object metadata/checksums, cleanup logs, screenshots redacted, TTL test and recordings. Fail → mark missing/disabled capture path accurately, REWORK/rerun. DONE needs AC1–5; video decision chưa chốt không tự coi optional và bỏ task.
