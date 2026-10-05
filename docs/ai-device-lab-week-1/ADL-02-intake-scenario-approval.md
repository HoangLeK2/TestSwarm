# ADL-02 — Intake production, AI generation và approval bất biến

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production customer capability / NOT_STARTED |
| Owner / review | BE API/AI + FE / runtime + security + product + QA |
| Dependencies | 00, 01; 20a design decisions; enforce policy 18a trước customer execution |
| Deliverable | Persisted intake, AI-generated draft, versioned approval, API/UI/tests |

## 2. Source/gap
`backend/runtime/ai/ai_scenario.py` tạo steps qua LLM; `backend/db/models/campaign.py` có Scenario mutable; `backend/db/models/scenario_version.py` snapshot khi execution; chưa chứng minh approval pin trước dispatch. Dùng schema validators và generated client hiện có, không tạo client HTTP song song.

## 3. Contract
- Intake: org/owner/package/closed_track_link/test_goal/requested build/test_environment; syntax-valid link không là verified access.
- Generation request: input version/hash + operation ID + status pending/running/succeeded/failed; retries không tự overwrite bản người dùng đã sửa.
- Approval: scenario_version_id, content hash, policy_version, assertions, allowed operations/package, approved_by/at; payload không chứa credential.
- Edit sau approval → draft version mới; approval cũ không áp dụng version mới. Dispatcher chỉ nhận exact approved version/hash, không đọc mutable steps lúc chạy.
- Assertion phải mô tả expected observable condition, target selector/identity và timeout; LLM JSON valid không đủ để cho phép execution.

## 4. Bước triển khai
1. Review DTOs/migration/intake state và validation errors; pin shared interface với 04/16.
2. Nối goal→AI draft thật, timeout/retry/error rõ; validate schema/capability/assertion/policy sau output.
3. Implement save/edit/generate/approve authorization; concurrent edit/approval dùng version conflict, không last-write-wins ngầm.
4. Wizard App/Scenario và review view EN/VI, lưu draft server-side; show denied operations/unsupported assertions.
5. Generate API client; tests AI boundary, approval race, direct dispatch và browser.

## 5. Acceptance
- [ ] AC1: input persist org-scoped, refresh/back không mất draft.
- [ ] AC2: AI provider tạo draft có assertions đo được; manual fallback không đóng capability AI.
- [ ] AC3: version edit invalidates current approval; approved snapshot immutable.
- [ ] AC4: unsafe/unsupported/OTP bypass output bị server deny.
- [ ] AC5: direct API không dispatch unapproved hoặc altered version.

## 6. Test matrix
| ID | Action | Expected / evidence |
|---|---|---|
| 02-T1 | Save goal, generate AI, review/approve | Provider trace redacted + validated draft/version/approver persisted |
| 02-T2 | AI output purchase/ad click/injected XML instruction | Denied với policy code; no execution |
| 02-T3 | JSON hợp lệ nhưng không assertion/capability | Validation error; không Approved |
| 02-T4 | Edit và approve đồng thời | Version conflict; old approval không cover new content |
| 02-T5 | Direct dispatch altered/unapproved version hoặc org B ID | Reject, zero job |
| 02-T6 | Provider outage/timeout rồi retry | Visible failed/retry; no silent approval/duplicate version |

## 7. Review và DoD
Security ký policy, runtime ký primitive/assertion compatibility, product/QA kiểm browser và generated draft trên app được phép. Evidence: schema diff, provider/request ID redacted, approval rows, negative responses, browser recording. Findings → REWORK → rerun affected tests. DONE cần AC1–5 và real generation proof; quyền tool foundation vẫn là gate riêng 18a.
