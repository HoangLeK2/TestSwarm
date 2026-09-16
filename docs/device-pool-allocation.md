# Cấp phát device: Agent → Pool → Workspace

Tài liệu quy chuẩn cho tính năng phân bổ phone từ relay agent về workspace.
Đây là hợp đồng: backend, frontend và test đều code theo đúng những gì ghi ở đây.

## 1. Mô hình ba tầng

```
Activation token  ──phát từ──>  Workspace (pool hoặc tenant)
       │
       │ agent enroll bằng token
       ▼
  Relay agent (relay_agents.org_id = workspace của token)
       │
       │ agent báo cáo serial của phone cắm vào host
       ▼
  Device (devices.managed_by_relay_id = agent, managed_by_org_id = workspace sở hữu)
       │
       │ admin cấp phát
       ▼
  Workspace đang dùng (devices.org_id)
```

Số lượng:

- 1 Device → 1 Workspace tại một thời điểm.
- 1 Workspace → N Device.
- 1 Workspace có thể gom device từ nhiều Agent khác nhau.
- Workspace chỉ dùng được device đã được cấp cho nó (cô lập bởi `tenancy`).
- Chuyển device giữa hai workspace = unassign khỏi A → assign sang B.

## 2. Nghĩa của từng cột

| Cột | Nghĩa |
|---|---|
| `organizations.kind` | `pool` \| `tenant`. Chỉ superadmin set được `pool` (`workspace_admin.py:1655`). Xem migration `123_workspace_kind.py` — nó là lý do tồn tại của cột. |
| `relay_agents.org_id` | Workspace của **activation code** đã enroll agent. Set lúc register (`web/server.py:860` → `crud/relay_agent.py:42,196`). **Bất biến** sau khi enroll (mục 5). |
| `devices.managed_by_org_id` | Workspace **sở hữu** phone (pool, hoặc chính tenant nếu tenant tự chạy relay). Không đổi khi cấp phát. |
| `devices.managed_by_relay_id` + `devices.relay_serial` | Phone này nằm trên agent nào, với serial nào. |
| `devices.org_id` | Workspace **đang được cấp** phone. Đây là cột `tenancy/sqlalchemy.py:33` tự chèn vào mọi ORM SELECT của `TenantScopedModel`. |
| `relay_agents.serials` | Danh sách serial agent **đang báo cáo ngay lúc này**. Bị `update_relay_heartbeat` (`crud/relay_agent.py:259`) ghi đè mỗi heartbeat. Đây là ảnh chụp hiện tại, **không phải** sổ sách sở hữu. |

Quy tắc đọc quan trọng: `devices.org_id == devices.managed_by_org_id` nghĩa là phone
**đang nằm trong kho**, chưa cấp cho ai. `devices.org_id != managed_by_org_id` nghĩa là
**đã cấp ra ngoài**. Trước đây hai trạng thái này cùng một giá trị nên response không
phân biệt được — xem mục 4 (`pooled`).

## 3. Luật pool / tenant

**Token phát từ pool workspace** (workspace của admin):
agent enroll bằng token đó → toàn bộ phone của agent thuộc pool.
Admin **được** cấp phone ra workspace X, Y, Z. Một agent 20 phone có thể chia 5 cho X,
5 cho Y, giữ 10 trong kho.

**Token phát từ tenant workspace X**:
agent enroll bằng token đó → phone thuộc riêng X.
Admin **KHÔNG được** cấp phone đó ra workspace khác. Không phải hạn chế kỹ thuật mà là
luật nghiệp vụ: nếu cho phép, tenant X im lặng trở thành người quản lý phone của tenant
khác (nguyên văn lý do trong migration 123). Muốn phone vào pool thì **revoke code cũ,
phát activation code mới từ pool workspace, enroll lại agent**.

Điểm chặn trong code:

- `_assign_agent_phone_serials` (`workspace_admin.py:3013`) → 409 `AGENT_NOT_IN_POOL_WORKSPACE`
- `admin_transfer_device_workspace` (`workspace_admin.py:3506`) → 409 `DEVICE_NOT_IN_POOL_WORKSPACE`

Luật này **đúng và phải giữ**. Việc cần làm là giải thích nó ngay tại chỗ admin bấm nút,
chứ không phải nới nó ra.

## 4. Hợp đồng API sau đợt sửa này

### 4.1 Trường mới

| Trường | Kiểu | Ở đâu | Nghĩa |
|---|---|---|---|
| `pooled` | bool | `AdminAgentPhoneOut`, `AdminDeviceOut` | `true` = phone đang trong kho của workspace sở hữu (`org_id == managed_by_org_id`, hoặc chưa có device row). `false` = đã cấp ra một workspace khác. Suy ra lúc trả response, **không thêm cột DB**. |
| `workspaceKind` | `"pool"` \| `"tenant"` | `AdminAgentOut` | `kind` của `relay_agents.org_id`. Console dùng nó để biết agent này có được cấp phát hay không, trước khi gọi API và ăn 409. |

### 4.2 Mã lỗi

| Mã | HTTP | Khi nào | Console phải nói gì |
|---|---|---|---|
| `AGENT_NOT_IN_POOL_WORKSPACE` | 409 | Assign phone từ agent thuộc tenant workspace | "Agent này enroll bằng activation code của workspace <tên>, phone của nó thuộc riêng workspace đó. Muốn chia sẻ, hãy phát activation code mới từ pool workspace rồi enroll lại agent." |
| `DEVICE_NOT_IN_POOL_WORKSPACE` | 409 | Chuyển device mà workspace quản lý không phải pool | Như trên, ở màn hình devices |
| `SERIAL_NOT_REPORTED_BY_AGENT` | 409 | **Chỉ còn ở POST (assign)**. Serial không nằm trong `agent.serials` | "Agent chưa báo cáo serial này" |
| `NO_SERIALS_SELECTED` | 400 | Danh sách serial rỗng | — |
| `PHONE_BATCH_TOO_LARGE` | 413 | > 200 serial một lần | — |
| `DEVICE_MANAGED_BY_ANOTHER_WORKSPACE` | 409 | Device đã thuộc pool khác | — |
| `DEVICE_NOT_FOUND` | 404 | **Mới ở DELETE**: unassign một serial không có device row nào | "Serial này chưa từng được đăng ký" |
| `TARGET_WORKSPACE_ARCHIVED` | 409 | Workspace đích đã archive | — |
| `AGENT_WORKSPACE_IS_IMMUTABLE` | 409 | **Mới**: `PATCH /admin/agents/{id}` với `workspaceId` khác giá trị hiện tại | "Workspace của agent do activation code quyết định, không đổi được tại đây" |

### 4.3 Hành vi DELETE `/admin/agents/{relay_id}/phone-allocations`

- **Không** còn bắt serial phải nằm trong `agent.serials`.
- Vẫn bắt buộc phải resolve ra device row (theo `devices.serial` / `devices.adb_serial`);
  không có row → 404 `DEVICE_NOT_FOUND` kèm serial. **Tuyệt đối không tạo device mới trên
  đường unassign** — đó là hành vi chỉ đúng cho POST.
- Vẫn giữ gate pool (`AGENT_NOT_IN_POOL_WORKSPACE`), giới hạn batch, và audit event
  `device.returned_to_agent_pool`.

## 5. Quyết định: bỏ khả năng đổi workspace của agent

Hiện trạng: `PATCH /admin/agents/{relay_id}` nhận `workspaceId` và set `row.org_id`
(`workspace_admin.py:3206`). Nhưng `upsert_relay_agent` có `"org_id": org_id` trong
`on_conflict_do_update` (`crud/relay_agent.py:234`), lấy từ enrollment token — nên agent
reconnect là ghi đè lại. Thay đổi của admin **không sống sót**. (So sánh: `name` được cố
ý loại khỏi conflict update đúng vì lý do này, comment ở `:216`.)

**Quyết định: chặn ở PATCH, không sửa upsert.**

Lý do: theo mô hình user chốt, agent không di chuyển giữa workspace — workspace của agent
do activation code quyết định, đổi thì revoke code + re-enroll. `upsert_relay_agent` lấy
`org_id` từ token là **đúng**, nó chính là nguồn sự thật. Cái sai là cái API hứa một
chuyện mà token sẽ ghi đè lại ở heartbeat kế tiếp. Sửa upsert (loại `org_id` khỏi conflict
update) sẽ làm agent enroll lại bằng code của workspace khác vẫn kẹt ở workspace cũ — tệ hơn.

Cách chặn: `workspaceId` **giữ nguyên trong schema** nhưng route raise 409
`AGENT_WORKSPACE_IS_IMMUTABLE` nếu giá trị khác `row.org_id` hiện tại. Echo lại đúng giá
trị cũ vẫn được (form edit hay gửi cả object — cùng tiền lệ với `kind` ở
`test_workspace_admin_cannot_promote_own_workspace_to_pool`). Không xoá field khỏi schema
vì Pydantic mặc định bỏ qua field lạ → xoá đi thì API lại im lặng nuốt, đúng cái lỗi đang
muốn diệt.

## 6. Danh sách test case

File: `device_farm/tests/test_workspace_admin_console.py`. Style theo hai test đã có ở
`:906` và `:931`.

### Case dương

| # | Tên | Kỳ vọng |
|---|---|---|
| D1 | Pool agent cấp phone cho tenant workspace | 200, `assignedWorkspaceId` = tenant, `pooled == false` |
| D2 | Unassign phone đang được cấp, serial vẫn được agent báo cáo | 200, `org_id` về pool, `pooled == true` |
| D3 | **Unassign phone đã chết** (serial đã biến mất khỏi `agent.serials`) | 200, device về pool, không còn 409 `SERIAL_NOT_REPORTED_BY_AGENT` |
| D4 | Một agent chia phone cho hai workspace khác nhau | 200 cả hai, mỗi device một `org_id` |
| D5 | PATCH agent với `workspaceId` bằng đúng giá trị hiện tại | 200, không đổi gì |

### Case âm

| # | Tên | Kỳ vọng |
|---|---|---|
| A1 | Assign từ agent thuộc tenant workspace (đã có, `:931`) | 409 `AGENT_NOT_IN_POOL_WORKSPACE` |
| A2 | **Assign** serial agent chưa báo cáo | 409 `SERIAL_NOT_REPORTED_BY_AGENT` (guard này giữ nguyên cho POST) |
| A3 | **Unassign** serial chưa từng có device row | 404 `DEVICE_NOT_FOUND`, và **không** có device row nào được tạo thêm |
| A4 | Transfer device thuộc tenant workspace | 409 `DEVICE_NOT_IN_POOL_WORKSPACE` |
| A5 | Assign > 200 serial | 413 `PHONE_BATCH_TOO_LARGE` |
| A6 | PATCH agent đổi `workspaceId` sang workspace khác | 409 `AGENT_WORKSPACE_IS_IMMUTABLE`, `relay_agents.org_id` không đổi |
| A7 | Phân biệt rảnh vs đã cấp | Cùng một device: sau assign `pooled == false`, sau unassign `pooled == true` |

## 7. Console (admin-agents-page)

`PHONE_ALLOCATION_ENABLED = false` được bật lại. Điều kiện để bật: console phải nói được
luật ngay tại chỗ bấm.

- Agent thuộc **pool** (`workspaceKind === 'pool'`): nút cấp phát hoạt động bình thường.
- Agent thuộc **tenant**: nút cấp phát **disabled**, kèm giải thích tại chỗ (tooltip hoặc
  dòng chữ trong dialog) nêu đúng hai ý: (a) phone của agent này thuộc riêng workspace đó,
  (b) cách xử lý là phát activation code mới từ pool workspace rồi enroll lại agent.
- Cột/badge trạng thái phone phải phân biệt "trong kho" (`pooled === true`) với "đã cấp cho
  <workspace>" (`pooled === false`).
- Mọi key i18n mới phải có ở **cả** `front-end/messages/en.json` và `vi.json`
  (`pnpm check:i18n`).

## 8. Nợ kỹ thuật (ghi nhận, không sửa đợt này)

### 8.1 Assign xong device vẫn chưa dùng được ngay

Sau khi assign, device vẫn `user_id = None`, `status = unpaired`. Workspace phải tự claim
(409 `DEVICE_NOT_CLAIMED`, `api/routes/devices.py:1012`), và claim gắn device vào **một
user cụ thể**. Việc này lệch tầng với luật "1 device → 1 workspace": quyền sở hữu nằm ở
workspace, nhưng bước cuối lại gắn vào user. Hệ quả: admin cấp phone xong, workspace vẫn
thấy "chưa có gì" cho tới khi có người claim.

Chưa sửa vì nó là thay đổi về mô hình quyền, không phải bug, và đang có đường vòng dùng
được. Khi sửa: tách "device thuộc workspace" khỏi "device do user nào đang giữ".

### 8.2 `relay_agents.serials` bị dùng như sổ sách

`serials` là ảnh chụp theo heartbeat nhưng nhiều chỗ đọc nó như danh sách phone của agent
(`deviceCount` trên `AdminAgentOut` chẳng hạn). Đợt này chỉ gỡ phụ thuộc đó ở đường
unassign. Nguồn sự thật đúng là `devices.managed_by_relay_id`.
