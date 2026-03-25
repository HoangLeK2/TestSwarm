# Luồng đầy đủ (chưa dùng AI)

Đi hết luồng: backend + DB → đăng ký/đăng nhập → thêm thiết bị → tạo campaign → gán scenario thủ công → thêm device vào campaign → chạy campaign. **Không dùng AI** (không compile-scenario từ câu nói).

---

## Điều kiện

- **Backend** device_farm đang chạy (vd. `uv run main.py`), **database bật** trong `config.yaml`.
- Ít nhất **1 điện thoại** đã kết nối (agent qua WebSocket hoặc ADB) — có trong `/api/devices/live`.

---

## 1. Lấy serial thiết bị (không cần auth)

```bash
curl -s http://localhost:8081/api/devices/live | jq .
```

Ghi lại `serial` của thiết bị (vd. `ABC123XYZ`). Nếu mảng rỗng thì chưa có device nào kết nối.

---

## 2. Đăng ký user (chỉ lần đầu)

```bash
curl -s -X POST http://localhost:8081/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","name":"You","password":"your-password","role":"operator"}' | jq .
```

---

## 3. Đăng nhập → lấy JWT

```bash
export TOKEN=$(curl -s -X POST http://localhost:8081/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"you@example.com","password":"your-password"}' | jq -r '.access_token')
echo $TOKEN
```

Các bước sau dùng header: `Authorization: Bearer $TOKEN`.

---

## 4. Đăng ký thiết bị vào DB (gắn với user)

Dùng **serial** từ bước 1:

```bash
curl -s -X POST http://localhost:8081/api/devices \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"serial":"SERIAL_TỪ_BƯỚC_1","name":"Phone 1"}' | jq .
```

Trả về có `id` (UUID). Ghi lại **device_id** này để thêm vào campaign.

---

## 5. Danh sách thiết bị của user (lấy device_id nếu cần)

```bash
curl -s http://localhost:8081/api/devices \
  -H "Authorization: Bearer $TOKEN" | jq .
```

---

## 6. Tạo campaign

```bash
curl -s -X POST http://localhost:8081/api/campaigns \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Test campaign",
    "description": "Chạy thử không AI",
    "scenario": {},
    "device_ids": []
  }' | jq .
```

Ghi lại `id` campaign (UUID). Có thể bỏ `device_ids` rồi thêm device ở bước 8.

---

## 7. Gán scenario thủ công (đúng schema MCP/executor)

Schema step: xem `GET /api/scenario/schema` hoặc `device_farm/common/scenario_schema.py`.

**Lưu ý:**  
- "Vào Google" = mở **trang web** Google → dùng **`open_url`** với `https://www.google.com`. **Không** dùng `launch_app` (Chrome).  
- **Bắt buộc** có bước **tap** (tap_position hoặc tap_ratio) **ngay trước** `input_text` để focus vào ô search; nếu thiếu thì `input_text` dễ lỗi NPE trên U2.

Ví dụ: **vào Google (Chrome), đợi 3s, tap search_bar, đợi 1s, gõ "hello", bấm enter:**

```bash
export CAMPAIGN_ID="<id_campaign_từ_bước_6>"

curl -s -X PATCH "http://localhost:8081/api/campaigns/$CAMPAIGN_ID/scenario" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "scenario": {
      "instructions": "Vào Google, gõ hello và enter",
      "steps": [
        { "type": "open_url", "url": "https://www.google.com", "package": "com.android.chrome" },
        { "type": "wait", "seconds": 3 },
        { "type": "tap_position", "pos": "search_bar" },
        { "type": "wait", "seconds": 1 },
        { "type": "input_text", "via": "u2", "text": "hello" },
        { "type": "key", "key": "enter" },
        { "type": "wait", "seconds": 2 }
      ]
    }
  }' | jq .
```

---

## 8. Thêm thiết bị vào campaign

```bash
export DEVICE_ID="<device_id_UUID_từ_bước_4>"

curl -s -X POST "http://localhost:8081/api/campaigns/$CAMPAIGN_ID/devices" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "{\"device_id\": \"$DEVICE_ID\"}" | jq .
```

---

## 9. Chạy campaign (không cần auth)

```bash
curl -s -X POST "http://localhost:8081/api/campaigns/$CAMPAIGN_ID/run" | jq .
```

Trả về có `task_ids`, `device_serials`. Dispatcher sẽ lấy task và chạy trên device tương ứng.

---

## 10. Xem trạng thái task (tùy chọn)

```bash
curl -s "http://localhost:8081/api/tasks" | jq .
# hoặc theo id
curl -s "http://localhost:8081/api/tasks?ids=<task_id>" | jq .
```

---

## Tóm tắt thứ tự

| Bước | Hành động              | Auth |
|------|------------------------|------|
| 1    | GET /api/devices/live  | Không |
| 2    | POST /api/auth/register | Không |
| 3    | POST /api/auth/login  | Không |
| 4    | POST /api/devices     | Bearer |
| 5    | GET /api/devices      | Bearer |
| 6    | POST /api/campaigns   | Bearer |
| 7    | PATCH .../scenario    | Bearer |
| 8    | POST .../devices      | Bearer |
| 9    | POST .../run          | Không |
| 10   | GET /api/tasks        | Không |

---

## Lấy schema scenario (cho bước 7)

```bash
curl -s http://localhost:8081/api/scenario/schema | jq .
```

Các `type` step hợp lệ: `launch_app`, `open_url`, `wait`, `tap_position`, `tap_ratio`, `swipe_ratio`, `tap_selector`, `input_text`, `key`, `scroll_down`. Mỗi type có `required`/`optional` trong schema.
