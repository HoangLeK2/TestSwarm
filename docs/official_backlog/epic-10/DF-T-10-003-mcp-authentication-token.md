# DF-T-10-003 — Authentication: DEVICE_FARM_MCP_TOKEN + MCP_AUTH_TOKEN

## 1. Header

| Trường | Giá trị |
|---|---|
| **Ticket ID** | DF-T-10-003 |
| **Title** | Authentication MCP — hai loại token (device-scoped & user-scoped), validate & rotation |
| **Type** | `type:feature` |
| **Epic** | DF-E-10 — MCP Agent Tools (Preview) |
| **Module** | DF-MOD-10 — MCP Agent Tools |
| **Priority** | P3 |
| **Story Points** | 5 |
| **Status** | Backlog |
| **Labels** | `status:preview`, `module:mcp`, `layer:backend`, `layer:contract`, `type:feature`, `risk:auth`, `persona:ai-ops` |
| **Truy vết — FR refs** | FR-10-04, FR-10-05 |
| **Truy vết — UC refs** | UC-10-02 |
| **Reporter** | (placeholder) |
| **Assignee** | (placeholder) |
| **Created** | 2026-05-26 |
| **Last updated** | 2026-05-26 |

## 2. Bối cảnh nghiệp vụ

AI agent không được phép gọi tool tự do — phải có token và token phải mô tả rõ ràng phạm vi cho phép. Module 10 định nghĩa hai loại token: `DEVICE_FARM_MCP_TOKEN` (device-scoped — chỉ cho thao tác trên device đã pair) và `MCP_AUTH_TOKEN` (user-scoped — kèm ngữ cảnh tổ chức cho tool campaign / content / scenario). Không có ticket này thì mọi tool DF-T-10-004 → DF-T-10-009 không có cách phân quyền.

Persona chính là **AI Operations Supervisor (Preview)** — họ là người cấp token cho agent, quyết định scope hẹp tới mức nào. Vị trí trong luồng: sơ đồ "Xác thực và scope của token MCP" (module 10 mục 5.3).

> **Cảnh báo Preview:** Mô hình token này thuộc phần mở rộng nghiên cứu. Contract có thể đổi (ví dụ chia thành scoped token chi tiết hơn theo gợi ý trong open question). **KHÔNG dùng làm năng lực cốt lõi cho production-grade auth** — auth core của sản phẩm thuộc DF-E-01.

Ưu tiên P1 vì là rào chắn an toàn cho mọi tool sau.

## 3. Câu chuyện người dùng

> **Là** AI Operations Supervisor (Preview)
> **Tôi muốn** cấp DEVICE_FARM_MCP_TOKEN cho agent thao tác device cụ thể, hoặc MCP_AUTH_TOKEN cho agent cần ngữ cảnh tổ chức
> **Để** giảm rủi ro agent gọi tool ngoài phạm vi và để khi sự cố xảy ra có thể truy vết về token cụ thể.

## 4. Yêu cầu chức năng

- Hệ thống PHẢI hỗ trợ hai loại token có scope khác nhau: device-scoped và user-scoped — trace FR-10-04, FR-10-05.
- Hệ thống PHẢI validate token mỗi tool call; token sai / hết hạn / sai scope → reject với `df.permission_denied` hoặc `df.unauthorized` — trace FR-10-04, FR-10-05.
- Hệ thống PHẢI gắn token vào audit log entry (token id, không phải token plaintext) — trace FR-10-09 (chuẩn bị cho DF-T-10-011).
- Hệ thống PHẢI hỗ trợ rotation: revoke token cũ mà không restart server — trace FR-10-04.
- Hệ thống PHẢI ngăn token device-scoped gọi tool yêu cầu user scope (campaign / content / scenario), và ngược lại với tool admin-only — trace FR-10-04, FR-10-05.
- Hệ thống NÊN log cảnh báo khi cùng token được dùng từ nhiều agent runtime khác nhau trong thời gian ngắn (nghi sharing) — trace FR-10-09 + risks module 10.
- Hệ thống KHÔNG được log token plaintext ở bất kỳ chỗ nào — trace `risk:auth`.

## 5. Tiêu chí chấp nhận (Given / When / Then)

**AC-1: Token device-scoped gọi tool device-level OK, gọi tool user-level fail**

```
Given agent dùng DEVICE_FARM_MCP_TOKEN có scope cho device A12345
When agent gọi df_start_session với device A12345
Then thành công và session được persist
When cùng agent gọi df_campaign_create
Then bị reject với code df.permission_denied và message rõ scope mismatch
```

**AC-2: Token user-scoped giữ ownership theo organization**

```
Given agent dùng MCP_AUTH_TOKEN của user thuộc org X
When agent gọi df_content_query với collection thuộc org Y
Then bị reject với code df.permission_denied
And audit log ghi nhận attempt cross-organization
```

**AC-3: Token rotation không cần restart**

```
Given MCP server đang chạy với token T1
When admin gọi API revoke T1 và phát hành T2
Then mọi tool call dùng T1 sau thời điểm revoke bị reject trong < 10 s
And tool call với T2 thành công
And không cần restart MCP server
```

**AC-4: Token plaintext không xuất hiện trong log**

```
Given agent gọi tool bất kỳ với token T
When grep log file của MCP server và HTTP API
Then không tìm thấy plaintext token T
And chỉ thấy token id (hashed) trong audit log
```

## 6. Ngoài phạm vi

- KHÔNG bao gồm vault credential — dùng env / config store hiện hành; vault thuộc lộ trình dài hạn.
- KHÔNG bao gồm SSO / OIDC cho người vận hành — DF-E-01.
- KHÔNG bao gồm scoped-token chi tiết theo từng tool family (chỉ "device" và "user" ở release này) — open question module 10.
- KHÔNG bao gồm UI cấp token — thuộc DF-E-11 (dashboard) ở ticket riêng.

## 7. Kế hoạch triển khai

**Backend** (`layer:backend`)

- [ ] Token validator middleware ở MCP server.
- [ ] Lookup token → scope (device list / user id / org id).
- [ ] Hash token cho audit log.
- [ ] Endpoint revoke / rotate token (admin only).
- [ ] Cache scope với TTL ngắn (5-10 s) để rotation kịp.

**Database / Migration** (`layer:db`)

- [ ] Bảng `mcp_tokens` (id, hashed_value, scope_type, scope_ref, owner_user_id, created_at, revoked_at).
- [ ] Index theo hashed_value.

**Contract / API** (`layer:contract`)

- [ ] Cập nhật OpenAPI thêm endpoint admin rotate token.
- [ ] Mã lỗi df.unauthorized, df.permission_denied trong contract DF-T-10-013.

**Documentation** (`layer:docs`)

- [ ] Hướng dẫn cấp / rotate / revoke token.
- [ ] Best practice: least-privilege token.
- [ ] Warning Preview rõ ràng.

**Test** (`layer:test`)

- [ ] Unit test validator.
- [ ] Integration test scope mismatch.
- [ ] Test rotation < 10 s.
- [ ] Test grep log không có plaintext token.

## 8. Test case nghiệp vụ

| Test ID | Loại | Tiền điều kiện | Bước thực hiện | Kết quả mong đợi |
|---|---|---|---|---|
| TC-DF-T-10-003-01 | Positive | Token device-scoped hợp lệ cho device A | Gọi df_start_session(device=A) | Thành công, audit log ghi token id |
| TC-DF-T-10-003-02 | Positive | Token user-scoped hợp lệ | Gọi df_campaign_create với owner = user mà token thuộc về | Thành công |
| TC-DF-T-10-003-03 | Negative | Token device-scoped | Gọi df_campaign_create | df.permission_denied |
| TC-DF-T-10-003-04 | Negative | Token đã bị revoke 30 s trước | Gọi tool bất kỳ | df.unauthorized trong < 10 s |
| TC-DF-T-10-003-05 | Edge | Token chuẩn bị hết hạn (còn 5 s) gọi tool kéo dài 30 s | Tool đang chạy thì token hết hạn | Tool đang chạy hoàn tất; tool call mới sau đó fail df.unauthorized |
| TC-DF-T-10-003-06 | Edge | Cùng token T dùng từ 3 IP/agent runtime khác nhau trong 1 phút | Quan sát log | Log warning "token possibly shared" nhưng không block (chỉ flag để supervisor review) |
| TC-DF-T-10-003-07 | Negative | Token user-scoped của org X gọi resource org Y | Gọi df_content_query collection org Y | df.permission_denied + audit log cross-org attempt |

## 9. Phụ thuộc & rủi ro

**Bị chặn bởi:** DF-T-10-001 (server scaffold), DF-T-10-002 (contract định nghĩa token_scope per tool).

**Chặn:** DF-T-10-004 → DF-T-10-009, DF-T-10-011.

**Phụ thuộc giữa Epic:**

- DF-E-01 — identity model (user / organization). Token MCP reference user_id và org_id từ DF-E-01.
- DF-E-07 — ownership account theo org.

**Rủi ro:**

- **Token plaintext leak qua log debug:** review log format, test grep CI.
- **Cache scope stale gây bypass:** TTL ngắn + revocation flush cache ngay.
- **Người vận hành cấp MCP_AUTH_TOKEN của admin cho agent (risk module 10):** doc khuyến nghị service account; cảnh báo khi token có quyền admin org được dùng từ MCP.
- **Preview contract thay đổi:** bump version, ghi changelog.

**Phụ thuộc bên ngoài:** Identity service DF-E-01.

## 10. Điều kiện hoàn thành

- [ ] Code merged và pass CI.
- [ ] Test coverage ≥ 80%.
- [ ] Test case TC-DF-T-10-003-* được map.
- [ ] Tài liệu kỹ thuật + nghiệp vụ cập nhật.
- [ ] Telemetry: metric "mcp_auth_failure_total" + label scope_mismatch / expired / revoked.
- [ ] Code review ≥ 1 approve owner module + 1 approve security reviewer.
- [ ] Release notes ghi rõ "MCP auth (Preview)".
- [ ] **Đã ghi rõ vào tài liệu nghiệp vụ rằng tool còn ở trạng thái Preview, có warning khi dùng từ AI agent bên ngoài.**
- [ ] Đã test rotation và revocation end-to-end.

## 11. Truy vết & tài liệu tham chiếu

- **Đặc tả module:** [10-mcp-agent-tools.md §5.3 + FR-10-04, FR-10-05](../../official_docs/modules/10-mcp-agent-tools.md).
- **Đặc tả module liên quan:** [01-platform-runtime-and-access.md](../../official_docs/modules/01-platform-runtime-and-access.md).
- **Nhóm người dùng:** AI Operations Supervisor (Preview).
- **Thuật ngữ:** MCP, Reservation, Organization.
