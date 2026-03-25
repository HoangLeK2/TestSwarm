# Device Farm MCP Server

MCP (Model Context Protocol) stdio server, expose API device_farm dưới dạng tools cho Cursor / LLM.

## Tools chính

- **Session:** `df_start_session`, `df_end_session` — bind session_id ↔ device, tránh conflict multi-user.
- **Lock:** `df_reserve_device`, `df_release_device` — trạng thái idle / reserved / running.
- **Device:** `df_list_devices` (có `usage_state`), `df_tap`, `df_swipe`, `df_shell`, `df_screenshot`, `df_hierarchy`, `df_tap_selector`, …
- **Scenario:** `df_run_scenario` — chạy chuỗi bước (tap_ratio, wait, input_text, …).
- **Task:** `df_enqueue_task`, `df_list_tasks`.
- **Campaign (cần JWT):** `df_list_campaigns`, `df_get_campaign`, `df_create_campaign`, `df_update_campaign_scenario`, `df_compile_campaign_scenario`, `df_add_devices_to_campaign`, `df_get_campaign_devices`, `df_update_campaign_status`, `df_delete_campaign`, `df_run_campaign`.

Mọi tool dùng device đều nhận **device** (serial) hoặc **session_id** (sau khi `df_start_session`).  
Các tool campaign (trừ `df_run_campaign`) cần **DEVICE_FARM_MCP_TOKEN** hoặc **MCP_AUTH_TOKEN** = JWT (lấy từ POST /api/auth/login).

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
- `DEVICE_FARM_MCP_TOKEN` hoặc `MCP_AUTH_TOKEN` — JWT để gọi `/api/campaigns` (list, create, compile-scenario, …). Lấy từ `POST /api/auth/login`. Để trống thì chỉ `df_run_campaign` và các tool device/session dùng được.

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
