# Device Farm — Business Core Release Checklist

> **Mã tài liệu:** DF-BL-CORE-CHECKLIST  
> **Cập nhật lần cuối:** 2026-05-26  
> **Mục tiêu:** gom scope release đầu theo happy path nghiệp vụ, tránh để technical foundation hoặc roadmap preview lẫn vào high priority.

## 1. Nguyên tắc ưu tiên

- **P0:** ticket end-user hoặc API consumer bắt buộc cần để chạy luồng `login -> fleet/device -> account -> campaign/scenario -> execution -> content/artifact`.
- **P1:** ticket hỗ trợ trực tiếp cho release đầu nhưng không phải bước tối thiểu của happy path, ví dụ export UX, onboarding mỏng, account-group UI hoặc feature flag Facebook pilot.
- **P2:** ticket hữu ích cho vận hành beta, failure handling hoặc visibility nhưng không chặn happy path, ví dụ DLQ UI, scheduling, notification inbox tối thiểu.
- **P3:** ticket technical hardening, optimize, observability sâu, multi-platform roadmap, AI/MCP Preview, quota/fairness, capacity planning.

## 2. Epic priority theo nghiệp vụ

| Epic ID | Business priority | Vai trò trong release đầu |
|---|---|---|
| DF-E-02 | High | Quản lý device, claim/release session và xem fleet là lõi sản phẩm. |
| DF-E-04 | High | Scenario, campaign và execution là workflow nghiệp vụ chính. |
| DF-E-06 | High | Content, artifact và export là output mà end-user cần nhận. |
| DF-E-07 | High | Account, account group và account resolution cần cho campaign social. |
| DF-E-11 | High | Dashboard là bề mặt end-user dùng để vận hành toàn bộ happy path. |
| DF-E-01 | Medium | Cần phần login, tenant, RBAC, member; hardening/foundation để sau. |
| DF-E-03 | Medium | Cần boot/control path tối thiểu để device thật online; parity/hardening để sau. |
| DF-E-05 | Medium | Scheduling có giá trị sau manual run; R1 chỉ cần run-now/history nếu kéo vào. |
| DF-E-08 | Medium | Chỉ lấy Facebook L2 reference bundle; multi-platform và L3 để sau. |
| DF-E-09 | Low | Notification/analytics là visibility phase sau; inbox tối thiểu giữ P2. |
| DF-E-10 | Low | MCP Preview không thuộc GA/happy path end-user. |

## 3. Release slice R1

Luồng R1 cần chứng minh được:

1. Admin đăng nhập, có tenant scope và RBAC đúng.
2. Fleet Operator pair device, thấy device online, claim/release session.
3. Social Data Operator tạo account, đưa vào account group và link device/account.
4. Automation Builder tạo scenario/campaign, bind device/account, chạy manual execution.
5. Hệ thống lưu content item, artifact và trace execution.
6. Social Data Operator xem content trên dashboard và export kết quả.

## 4. Ticket P0/P1 nên ưu tiên implement/test

| Epic ID | Ticket P0/P1 core |
|---|---|
| DF-E-01 | DF-T-01-002, DF-T-01-003, DF-T-01-004, DF-T-01-009, DF-T-01-007, DF-T-01-010, DF-T-01-011, DF-T-01-012 |
| DF-E-02 | DF-T-02-001, DF-T-02-002, DF-T-02-003, DF-T-02-004, DF-T-02-005, DF-T-02-006, DF-T-02-007, DF-T-02-009, DF-T-02-012, DF-T-02-015 |
| DF-E-03 | DF-T-03-001, DF-T-03-002, DF-T-03-003, DF-T-03-004, DF-T-03-005, DF-T-03-006, DF-T-03-008, DF-T-03-011, DF-T-03-012 |
| DF-E-04 | DF-T-04-001, DF-T-04-002, DF-T-04-004, DF-T-04-006, DF-T-04-007, DF-T-04-008, DF-T-04-009, DF-T-04-010, DF-T-04-011, DF-T-04-013, DF-T-04-014, DF-T-04-016 |
| DF-E-06 | DF-T-06-002, DF-T-06-003, DF-T-06-004, DF-T-06-006, DF-T-06-007, DF-T-06-008, DF-T-06-009, DF-T-06-012, DF-T-06-014, DF-T-06-016 |
| DF-E-07 | DF-T-07-001, DF-T-07-002, DF-T-07-003, DF-T-07-005, DF-T-07-007, DF-T-07-008, DF-T-07-010, DF-T-07-012 |
| DF-E-08 | DF-T-08-001, DF-T-08-004, DF-T-08-005, DF-T-08-006, DF-T-08-014 |
| DF-E-11 | DF-T-11-001, DF-T-11-002, DF-T-11-003, DF-T-11-004, DF-T-11-005, DF-T-11-006, DF-T-11-008, DF-T-11-009, DF-T-11-010, DF-T-11-011, DF-T-11-012, DF-T-11-016, DF-T-11-017 |

## 5. Ticket P2/P3 để phase sau

- **Technical hardening/foundation:** DF-T-01-005, DF-T-01-006, DF-T-01-008, DF-T-01-013, DF-T-03-007, DF-T-03-009, DF-T-03-010, DF-T-03-013, DF-T-03-014.
- **Optimization/capacity/advanced ops:** DF-T-02-010, DF-T-04-017, DF-T-05-007, DF-T-05-008, DF-T-05-012.
- **Failure handling ngoài happy path:** DF-T-04-012, DF-T-11-018.
- **AI/MCP/Preview:** DF-T-06-005, toàn bộ DF-E-10.
- **Multi-platform roadmap:** DF-T-08-008, DF-T-08-009, DF-T-08-010, DF-T-08-011, DF-T-08-012, DF-T-08-013, DF-T-08-015, DF-T-08-016, DF-T-08-017, trừ khi business chốt launch platform cụ thể ngoài Facebook.
- **Notification/analytics sâu:** DF-T-09-003 tới DF-T-09-014.

## 6. Gap đã bổ sung và gap để theo dõi

| Gap | Xử lý hiện tại |
|---|---|
| Content export job UX cho async export | Đã thêm DF-T-11-016. |
| First-run onboarding / empty-state CTA | Đã thêm DF-T-11-017. |
| DLQ resolution UI cho operator xử lý fail | Đã thêm DF-T-11-018 ở P2. |
| Rerun failed subset từ campaign result | Theo dõi trong DF-T-11-018; nếu backend cần contract riêng thì tách ticket DF-E-04 sau. |
| Device group + device tag manager UI | Chưa đưa vào R1; giữ phase sau cùng DF-T-02-008 và DF-T-02-009. |
| Notification settings UI | Chưa đưa vào R1; giữ phase sau cùng DF-E-09. |
| 2FA backend auth | Không thuộc R1; nếu vẫn muốn ship 2FA UI trong DF-T-11-015 thì phải tạo ticket backend riêng trong DF-E-01. |
