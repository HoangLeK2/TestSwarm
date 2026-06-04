# Device Farm MCP Server

MCP (Model Context Protocol) stdio server, expose API device_farm dưới dạng tools cho Cursor / LLM.

> Preview / Experimental: `contract_version=df-mcp-preview-2026-06-01`. Contract có thể đổi giữa các release và không có GA SLA.

## Tools chính

- **Registry:** `tools/list`, `df_mcp_registry` — trả tool schema, route parity, token scope, Preview warning.
- **Session:** `df_start_session`, `df_end_session`, `df_get_session_info`, `df_device_claim` — bind session_id ↔ device, tránh conflict multi-user.
- **Lock:** `df_reserve_device`, `df_release_device` — trạng thái idle / reserved / running.
- **Device:** `df_device_list` / `df_list_devices` (có `usage_state`), `df_tap`, `df_swipe`, `df_shell`, `df_screenshot`, `df_hierarchy`, `df_tap_selector`, …
- **Scenario:** `df_run_scenario` — chạy chuỗi bước (tap_ratio, wait, input_text, …).
- **Task:** `df_enqueue_task`, `df_list_tasks`.
- **Campaign:** `df_campaign_create` / `df_create_campaign`, `df_campaign_run` / `df_run_campaign`, `df_list_campaigns`, `df_get_campaign`, `df_update_campaign_scenario`, `df_compile_campaign_scenario`, `df_add_devices_to_campaign`, `df_get_campaign_devices`, `df_update_campaign_status`, `df_delete_campaign`.
- **Content/account:** `df_content_query`, `df_save_extraction`, `df_account_list`.

Mọi tool dùng device đều nhận **device** (serial) hoặc **session_id** (sau khi `df_start_session`).
MCP server dùng một bearer env duy nhất: **MCP_AUTH_TOKEN**. Token `dfmcp_*` user-scoped gọi được cả tool device/session và campaign/content/account/scenario; token device-scoped chỉ gọi được tool device/session.

## Guardrails Preview

- Server từ chối khởi động nếu thiếu `MCP_AUTH_TOKEN`; chỉ dùng `DEVICE_FARM_MCP_ALLOW_UNAUTH=1` cho local contract test.
- Mọi `tools/call` ghi audit JSONL, mặc định tại `device_farm/mcp/mcp_audit_log.jsonl`; override bằng `DEVICE_FARM_MCP_AUDIT_LOG_PATH`.
- Audit redact các field nhạy cảm (`token`, `password`, `secret`, `cookie`) và chỉ lưu token hash prefix.
- API token/audit trên dashboard chỉ trả dữ liệu cùng tenant cho non-superadmin; token tạo từ dashboard dùng prefix `dfmcp_`, lưu hash-at-rest, và được backend auth chấp nhận như bearer token.
- Rate-limit baseline mặc định `120/minute`; override bằng `DEVICE_FARM_MCP_RATE_LIMIT` (ví dụ `60/minute`, `5/second`).
- Error trả về theo catalog `df.*` (`df.invalid_argument`, `df.unauthorized`, `df.permission_denied`, `df.rate_limited`, `df.internal`, ...), không trả traceback cho agent.
- `df_save_extraction` yêu cầu `artifact_refs` để gắn evidence trước khi persist dữ liệu extraction.
- Dashboard Preview surface: `/dashboard/mcp`, `/dashboard/mcp/tools`, `/dashboard/mcp/tokens`, `/dashboard/mcp/audit-log`, `/dashboard/mcp/sandbox`.

## Chạy MCP server

**Điều kiện:** Backend device_farm đang chạy (mặc định `http://localhost:8081`).

### Từ repo root (Mac/Linux)

```bash
./scripts/run_device_farm_mcp.sh
```

### Từ thư mục device_farm

```bash
cd device_farm
python -m mcp.server
```

### Cấu hình (.env)

MCP server tự load `device_farm/.env` khi chạy. Copy `device_farm/.env.example` → `device_farm/.env` và sửa:

- `DEVICE_FARM_URL` — URL backend (mặc định `http://localhost:8081`).
- `MCP_AUTH_TOKEN` — bearer token cho toàn bộ MCP server. Dùng token `dfmcp_*` user-scoped cho agent cần cả device/session và campaign/content/account/scenario; dùng token device-scoped nếu chỉ muốn cấp quyền device/session.
- `DEVICE_FARM_MCP_TOKEN_STORE` — optional path cho token tạo từ dashboard; token lưu dạng hash-at-rest.

## Tích hợp Cursor

Trong repo đã có `.cursor/mcp.json`:

- Server: `device-farm`
- Chạy qua `scripts/run_device_farm_mcp.sh`, env `DEVICE_FARM_URL=http://localhost:8081`

Sau khi thêm/sửa MCP config, **restart Cursor** để load lại.

Trên Windows có thể đổi trong `.cursor/mcp.json` thành:

```json
"device-farm": {
  "command": "device_farm\\.venv\\Scripts\\python.exe",
  "args": ["device_farm/mcp/server.py"],
  "env": {
    "PYTHONPATH": "device_farm",
    "DEVICE_FARM_URL": "http://localhost:8081"
  }
}
```

(Chạy từ workspace root.)
