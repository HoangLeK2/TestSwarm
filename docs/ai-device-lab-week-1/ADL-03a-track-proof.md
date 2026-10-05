# ADL-03a — Kiểm chứng Play account/track/install có provenance

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production evidence-source gate / NOT_STARTED |
| Owner / review | Operator + BE integration / product + QA |
| Dependencies | 00, 01; account consent, published release, test app được phép |
| Deliverable | Evidence protocol, một account proof thật, diagnosis matrix và privacy review |

## 2. Research/source
Google Help [requirements](https://support.google.com/googleplay/android-developer/answer/14151465) quy định opt-in liên tục; [testing tracks](https://support.google.com/googleplay/android-developer/answer/9845334) mô tả published link/version behavior. `edits.testers` chỉ quản lý Google Groups; không trả từng account opt-in continuity. `backend/db/models/account.py` không là evidence Play enrollment.

## 3. Contract kiểm chứng
- Evidence schema: pseudonymous_account_ref, org/package/track, source_type, source_ref, observed_at, event_type, reviewer, reviewed_at, confidence/status và limitations.
- Tách invited/group member, opted_in, installed, opened và Google production access; mỗi claim cần nguồn riêng.
- `operator_attested` là lời chứng có nguồn, không là Google official verified. Khoảng quan sát thiếu phải báo unknown/gap; không chứng minh continuity tuyệt đối chỉ từ hai screenshots.
- Đổi device không đổi account identity; opt-out/re-opt-in tạo continuity segment mới. Không thu Play Console password.

## 4. Bước làm
1. Chủ sở hữu xác nhận test account/track quyền truy cập và consent; ghi nguồn/giờ UTC, che email/token.
2. Quan sát người dùng/account tự opt-in, ghi evidence đúng account/package; chỉ API group membership không đủ.
3. Install/update từ Play, quan sát version thực tế và source, kiểm shadowing/internal-track exclusion.
4. Tái hiện invalid link/unpublished/wrong account/OTP; ghi blocker và next action, không tự bypass.
5. Khóa schema evidence để 03b persist; artifact operator là proof của task này, không thay model/API production 03b.

## 5. Acceptance
- [ ] AC1: một enrollment/install proof thật có package/account/source/time/reviewer.
- [ ] AC2: invitation/install không tự nâng opted-in status.
- [ ] AC3: lost/re-opt-in continuity rules có case và limitations rõ.
- [ ] AC4: account/email/PII được mask và scoped access.

## 6. Test matrix
| ID | Setup/action | Expected |
|---|---|---|
| 03a-T1 | Published closed track, account consent, self opt-in | Attested source; install version observed, không claim Google approval |
| 03a-T2 | Chỉ group member/email invite hoặc sideload | Unknown enrollment |
| 03a-T3 | Opt-out rồi re-opt-in | New segment; old evidence retained |
| 03a-T4 | Production/internal track có version cao hơn | Actual build mismatch rõ; no false closed-build claim |
| 03a-T5 | Wrong account/link delay/OTP | Needs attention + owner/next action; không pass |

## 7. Review và DoD
QA replay observations được phép, product ký claims và confidence semantics; security review redaction. Lưu evidence private, pseudonym refs, diagnosis records, consent reference; không commit secrets. Thiếu account/release → BLOCKED_INPUT; DONE chỉ khi AC1–4 PASS. Continuous 14-day acceptance thuộc 12, không suy từ một proof.
