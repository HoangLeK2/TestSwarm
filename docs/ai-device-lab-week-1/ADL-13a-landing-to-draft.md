# ADL-13a — Landing production, authentication và draft intent

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Production acquisition journey / NOT_STARTED |
| Owner / review | FE + BE auth / product + security + QA |
| Dependencies | 02, 20a; role/tenant rules 15 |
| Deliverable | Landing EN/VI, safe return-to-auth, idempotent draft CTA, funnel events |

## 2. Source/gap
`front-end/src/app/[locale]/page.tsx`, `auth/sign-in/page.tsx`, campaign features có app/auth shell; chưa chứng minh customer service CTA persist intent. Dùng existing locale/router/auth/generated client, không tạo auth token flow riêng.

## 3. Contract
- Landing nói rõ Android/12 device lanes/14 ngày/planned runs/evidence và participation nguồn riêng; Google approval không phải promise hệ thống.
- CTA guest giữ opaque creation intent, locale và allowlisted internal return route; không giữ credentials/PII trong query string.
- Draft creation idempotency key scoped authenticated org/user/intent; xác thực xong server resolve active org, không tin org_id client.
- Analytics landing_view/start_click/app_submitted có event ID/source timestamp/consent rule, không chứa goal/secret/email. Paid funnel nối 13b, không fake events.

## 4. Bước làm
1. Product ký copy/price entry và CTA destination từ 20a.
2. Implement auth return intent and repeated-submit behavior; block external redirects và stale/cross-org intent.
3. Draft create/read API mapping 02; refresh/back giữ draft qua server persistence.
4. Mobile/desktop/keyboard/error states, EN/VI; instrument events theo 20b schema.
5. Browser E2E guest/signed-in/multi-org/repeat; review redirect/query privacy.

## 5. Acceptance
- [ ] AC1: CTA đi tới draft đúng org qua auth, giữ locale/intent.
- [ ] AC2: repeated clicks/back không tạo duplicate draft/order.
- [ ] AC3: wording tách AI lanes và verified Play accounts.
- [ ] AC4: redirect/intent scoped và analytics không leak PII.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 13a-T1 | Signed-in click CTA | Persisted draft của active org |
| 13a-T2 | Guest→sign-in→callback | Resume đúng draft intent/locale |
| 13a-T3 | Double click/back/refresh + network retry | One draft per creation intent |
| 13a-T4 | External return URL/cross-org intent | Rejected/safe internal fallback |
| 13a-T5 | Mobile/keyboard/EN/VI + event inspect | Accessible CTA, no secret/PII query/event |

## 7. Review và DoD
Product review claims/user comprehension, security auth redirect, QA replay browsers. Evidence API IDs/events redacted/browser recordings và locale checks. Fail → REWORK → rerun affected auth flow. DONE cần AC1–4; acquisition paid journey chỉ hoàn chỉnh khi 13b cũng DONE.
