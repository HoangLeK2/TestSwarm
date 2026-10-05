# ADL-15 — Authorization matrix và audit production

## 1. Giao nhận
| Thuộc tính | Yêu cầu |
|---|---|
| Scope / status | Cross-cutting production mandatory / NOT_STARTED |
| Owner / review | BE security + FE / security reviewer + QA |
| Dependencies | 00; role contract thiết kế D1; integration 04/09 và từng API resource |
| Deliverable | Signed permission matrix, backend policy enforcement, audit schema/tests, UI access states |

## 2. Source/gap
Repo có auth/tenancy, `backend/api/routes/workspace_admin.py` và `backend/tests/test_execution_access.py`; service-specific order/reservation/report/participation actions cần khai báo policy, không mặc định superadmin là customer owner.

## 3. Matrix đề xuất phải owner duyệt trước code
| Action | Customer owner | Developer được phân quyền | Operator | Outside-org |
|---|---|---|---|---|
| Draft/scenario/build/issue | Allow trong org | Explicit grant | Support read tối thiểu | Deny |
| Approve/start/retest/cancel | Owner grant + policy | Explicit grant | Explicit delegated operation có reason | Deny |
| Pay/refund/extend | Owner pay/request | Billing grant | Finance/admin delegated grant, không mặc định | Deny |
| Reserve/replace/quarantine | Read own status | Read own status | Fleet grant + org scope + reason | Deny |
| Report/export/evidence | Org report grant | Explicit grant | Support redacted scope | Deny |
| Secret resolve/raw identity | Job capability riêng | Không lấy raw secret qua UI | Không mặc nhiên được đọc | Deny |

Matrix trên là thiết kế đề xuất; ghi role names theo auth repo sau review. Deny-by-default cho action chưa map. Every read/write/search/export/upload/signed URL grant kiểm tenant/resource ownership, không chỉ route root.

## 4. Bước làm
1. Inventory endpoints/actions/DTO fields và actual role model; owner ký matrix.
2. Enforce repository tenant scoping + object-level authorization; grant/revoke có audit.
3. Audit append-only org/actor/action/target/reason/request_id/time/outcome; redact payload, không full secret/request body.
4. UI hide/disable explanatory state phản ánh policy, không là boundary.
5. Test matrix roles/actions plus object substitution, report worker và artifact paths.

## 5. Acceptance
- [ ] AC1: mỗi action có explicit policy/role và negative test.
- [ ] AC2: cross-tenant access denied cho list/detail/mutation/download.
- [ ] AC3: operator không có raw customer secrets/identity mặc định.
- [ ] AC4: sensitive actions có audit đúng actor/reason/outcome.
- [ ] AC5: revoke chặn URL cấp mới; signed URL đã cấp còn tới TTL được policy mô tả, không hứa revoke ngay nếu chưa có proxy.

## 6. Test matrix
| ID | Action | Expected |
|---|---|---|
| 15-T1 | Cartesian role×action fixtures | Allow/deny đúng signed matrix |
| 15-T2 | Replace URL/body ID with org B resource | Deny trước side effect/URL grant |
| 15-T3 | Operator access secret/raw identity | Deny unless explicit audited capability |
| 15-T4 | Revoke role then new export/download | No new grant; existing bearer TTL/proxy rule tested |
| 15-T5 | Replace/refund/cancel denied/succeeded | Audit actor/outcome/reason, no plaintext |
| 15-T6 | Job/report worker scope wrong org | Deny internal association too |

## 7. Review và DoD
Security review repository+route coverage, QA chạy full matrix bằng direct API và browser hai roles. Evidence endpoint inventory, matrix approval, negative responses/audit SQL. Any unauthorized success → release-blocking finding, fix and rerun full boundary suite. DONE cần AC1–5; policy design sớm không chờ payment/UI hoàn thành.
