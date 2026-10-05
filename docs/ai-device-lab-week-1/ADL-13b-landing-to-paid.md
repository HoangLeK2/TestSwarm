# ADL-13b — Hành trình acquisition tới verified payment/readiness

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production mandatory / NOT_STARTED |
| Owner / review | FE + billing integration / product + QA |
| Dependencies | 13a, 09, 14, 06; analytics contract 20b |
| Deliverable | Full landing→auth→wizard→provider→readiness E2E, attribution/recovery evidence |

## 2. Source/gap
Landing/auth paths là 13a; payment authority thuộc 09, wizard 14. Task này nối journey/funnel, không tạo billing logic mới trong FE hoặc nhận redirect làm payment truth.

## 3. Contract
- Single creation intent/campaign/order xuyên journey; attribution nối bằng opaque event/campaign IDs, không email.
- Price/package/currency/refund/blocked-readiness policy hiển thị từ server snapshot; copy không lệch giá order.
- Funnel order `landing_view→start_click→app_submitted→scenario_approved→payment_completed→readiness_started`; payment/readiness events từ committed server transitions, event ID dedup.
- Failed/abandoned checkout có resume order, no new charge intent mặc định khi state uncertain; unreadiness giữ clock null.

## 4. Bước làm
1. Map UI states/callbacks tới server order state, giữ campaign intent qua auth/provider return.
2. Nối copy package/price snapshot và CTA; product approve messaging.
3. Emit/correlate funnel events, dedup browser retries và server callbacks.
4. Recovery abandoned/fail/timeout và multi-tab flow; safe auth return.
5. Full browser journey với provider sandbox; production activation check từ 09 trước mở CTA thu tiền.

## 5. Acceptance
- [ ] AC1: verified payment dẫn đúng campaign readiness, no duplicate order.
- [ ] AC2: abandon/error/uncertain callback recover không double charge.
- [ ] AC3: events source/IDs/counts khớp server committed state.
- [ ] AC4: customer hiểu price/limits/track truth, mobile/locale đúng.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 13b-T1 | Guest tới approved scenario→sandbox pay | One intent/order, paid event từ server, checklist đúng |
| 13b-T2 | Multi-tab double CTA/payment return | No duplicate charge/order/events |
| 13b-T3 | Redirect success trước webhook rồi webhook failed | Pending/failed chính xác, no start |
| 13b-T4 | Abandon rồi resume existing order | Same snapshot/ref, no implicit repurchase |
| 13b-T5 | Wrong org + funnel payload privacy | Denied; no PII/secret |

## 7. Review và DoD
QA kiểm full journey/funnel SQL, billing reviewer callback authority và product copy; evidence recording + provider refs + event dedup counts. Findings → REWORK/rerun checkout recovery; DONE cần AC1–4 và 09 production activation gate, không gọi sandbox là live charge.
