# ADL-15 — route/permission inventory (2026-10-04)

## Phạm vi

Inventory này phản ánh policy đang chạy trong source. Đây chưa phải signed role
matrix của DEC-07 và không đóng ADL-15. Mọi route dưới đây dùng Casbin dependency
trực tiếp tại backend; tenant/resource lookup vẫn phải trả 404 cho object ngoài org.

## Route inventory

| Method | Route | Permission |
|---|---|---|
| POST | `/service-campaigns` | `campaigns:create` |
| GET | `/service-campaigns/{campaign_id}` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/funnel` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/wizard` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/payment-reconciliations` | `campaigns:read` |
| PUT | `/service-campaigns/{campaign_id}/wizard/app` | `campaigns:manage` |
| POST | `/service-campaigns/{campaign_id}/wizard/scenario/generate` | `campaigns:manage` |
| POST | `/service-campaigns/{campaign_id}/wizard/scenario/approve` | `campaigns:manage` |
| POST | `/service-campaigns/{campaign_id}/wizard/payment/checkout` | `campaigns:update` |
| POST | `/service-campaigns/{campaign_id}/start` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/slots/materialize` | `campaigns:execute` |
| GET | `/service-campaigns/{campaign_id}/progress` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/lanes` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/lanes/{lane_id}` | `campaigns:read` |
| GET | `/service-campaigns/{campaign_id}/participation` | `campaigns:read` |
| POST | `/service-campaigns/{campaign_id}/participation` | `campaigns:manage` |
| GET | `/service-campaigns/{campaign_id}/issues` | `campaigns:read` |
| POST | `/service-campaigns/{campaign_id}/issues` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/issues/{issue_id}/retests` | `campaigns:execute` |
| GET | `/service-campaigns/{campaign_id}/reports` | `campaigns:read` |
| POST | `/service-campaigns/{campaign_id}/reports/{report_id}/publish` | `campaigns:manage` |
| POST | `/service-campaigns/{campaign_id}/reports/{report_id}/download-url` | `campaigns:read` |
| POST | `/service-campaigns/{campaign_id}/evidence/{evidence_id}/download-url` | `campaigns:read` |
| POST | `/service-campaigns/{campaign_id}/lanes/{lane_id}/replace` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/operations/{operation_id}/complete-replacement` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/extend` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/cancel` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/expire` | `campaigns:execute` |
| POST | `/service-campaigns/{campaign_id}/operations/{operation_id}/complete-cancellation` | `campaigns:execute` |
| POST | `/kpi/definitions` | `campaigns:manage` |
| POST | `/kpi/cohorts` | `campaigns:manage` |
| POST | `/kpi/assistance-events` | `campaigns:execute` |
| POST | `/kpi/cohorts/{cohort_id}/snapshots` | `campaigns:manage` |
| POST | `/acceptance/candidates` | `campaigns:manage` |
| POST | `/acceptance/candidates/{candidate_id}/evaluate` | `campaigns:manage` |

## Seed policy hiện tại

| Role | `read` | `create` | `manage` | `execute` |
|---|---:|---:|---:|---:|
| `owner` | allow | allow | allow | allow |
| `admin` | allow | allow | allow | allow |
| `operator` | allow | deny | deny | deny |
| `member` | allow | deny | deny | deny |
| `supervisor` | allow | allow | deny | allow |

Automated direct-API proof hiện có:

- owner có thể tạo và thao tác campaign trong org;
- operator đọc được campaign nhưng nhận 403 cho `create`, `manage`, `execute`;
- resource org B trả 404 trước side effect hoặc signed URL;
- API không trả raw pseudonymous account reference, secret hoặc object key.
- checkout ngoài org trả 404; operator thiếu `campaigns:update` nhận 403; response
  chỉ chứa URL checkout đã kiểm allowlist và trạng thái an toàn, không chứa provider
  reference hoặc provider payload.

## Khoảng trống cần DEC-07 ký

Policy hiện dùng resource chung `campaigns`; chưa tách billing/refund, fleet,
report download, evidence, secret và acceptance thành action riêng. Đặc biệt,
`campaigns:read` hiện cho operator/member xin report download URL. Owner/security
phải quyết định support redaction, report grant, delegation/revoke và audit reason
trước khi đổi policy; không suy quyền production từ bảng đề xuất trong task.

Signed matrix còn phải xác định role thật, object-level grants, worker/report scope,
audit outcome/reason và quy tắc URL đã cấp khi role bị revoke. Sau khi ký, cần chạy
Cartesian role×action và browser replay bằng ít nhất hai role.
