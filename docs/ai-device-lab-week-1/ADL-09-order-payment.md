# ADL-09 — Billing production: order, payment, entitlement và refund

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / BLOCKED_DECISION: provider/currency/refund chưa chốt |
| Owner / review | BE billing + FE / security + finance/product + QA |
| Dependencies | 00, 04; role contract 15; provider onboarding và chính sách ký D1 |
| Deliverable | Billing models/ledger/API, verified webhook, checkout/refund/reconciliation, sandbox + production readiness evidence |

## 2. Source/gap
Không thấy Order/Payment/Entitlement service models tại lần source inspection `backend/db/models/`. Không dùng Google Play purchases API để thu tiền dịch vụ web. Provider chưa chọn → webhook SDK/schema/signature phải research đúng provider sau decision; không giả lập để đóng integration.

## 3. Contract
| Record | Quy tắc |
|---|---|
| Order | org/campaign, amount **integer minor units**, currency, immutable package/quota/policy versions; server quyết giá |
| PaymentIntent | order/provider ref/idempotency key; one active checkout intent theo chính sách; amount/currency binding |
| PaymentEvent inbox | unique provider+event_id; signature verified raw body; recorded/source times và processing state; durable trước ack |
| Entitlement | unique fulfilled order/plan grant, active/revoked; không cấp từ browser redirect |
| Refund | unique request key/provider ref, amount/reason/actor; pending/succeeded/failed, ledger giữ lịch sử |

Webhook duplicate/out-of-order không dùng simple last-write-wins. Khi event mâu thuẫn, reconcile authoritative provider state; refunded không resurrect bởi late paid event. ACK chỉ sau durable accept; asynchronous handler retry idempotent. External timeout checkout có uncertain state → lookup by idempotency/ref, không tạo charge mới mù quáng.

Readiness fail sau paid: payment vẫn paid, campaign waiting/needs_attention, clock chưa start; policy refund/extension explicit. Secrets provider chỉ backend, webhook replay window và provider verification theo docs thật.

## 4. Bước làm
1. Product/finance ký provider, currency, tax/receipt nếu áp dụng, refund/cutoff/quota rules và production smoke budget.
2. DB migrations/constraints và service interface; review exact provider integration/docs, signature handling và money precision.
3. Checkout, webhook durable inbox, state reconciler và entitlement transaction; retry/refund command idempotent.
4. Customer order/payment view + operator reconciliation queue; direct permission kiểm server.
5. Sandbox fault/race E2E; validate production account/config/webhook, chạy approved low-value live smoke trước paid launch.

## 5. Acceptance
- [ ] AC1: order snapshot server-priced, integer money và currency validated.
- [ ] AC2: một verified settlement cấp một entitlement; duplicate events không cấp lại.
- [ ] AC3: out-of-order/refund/replay/uncertain timeout xử lý có reconciliation.
- [ ] AC4: preflight fail không start clock, policy handling hiển thị rõ.
- [ ] AC5: secrets/RBAC/audit đúng; production activation evidence có thật.

## 6. Test matrix
| ID | Action | Expected / evidence |
|---|---|---|
| 09-T1 | Sandbox checkout paid amount/currency server | 1 order/payment/grant; provider ref + SQL ledger |
| 09-T2 | Concurrent checkout + duplicate webhook | No double charge/grant; unique keys + provider readback |
| 09-T3 | Forged signature/redirect-only success | No entitlement, error recorded sans secret |
| 09-T4 | Refund then delayed paid event | Remains revoked/refunded; reconciler authoritative state |
| 09-T5 | Provider timeout after accepted charge | Lookup/retry same intent, không charge mới |
| 09-T6 | Paid but readiness blocked; org B order read | Clock null; reason/policy; cross-org denied |
| 09-T7 | Approved live smoke/refund/reconcile | Production credential/webhook valid; receipt/refund refs private |

## 7. Review và DoD
Finance/product ký policies, security ký signature/keys, billing reviewer transaction/inbox; QA replay T2–6 và operator witness T7. Lưu provider refs, sanitized webhook fixtures, ledger reconciliation, commands/version. Fail → disable checkout or pending state đúng, không giả grant; fix/rerun/review. DONE cần AC1–5; task development tests có thể PASS sandbox nhưng paid launch bị khóa nếu thiếu live readiness proof.
