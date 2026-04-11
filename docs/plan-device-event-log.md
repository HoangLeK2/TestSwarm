# Plan: Device Event Log & Notification System

## Mục tiêu

Khi thiết bị mất kết nối, reconnect, lỗi, hoặc thay đổi trạng thái — user phải **biết ngay** thiết bị nào, lý do gì, và lúc nào. Hiện tại chỉ có server log (stdout), user không thấy gì trên UI.

## Hiện trạng

| Component | Có chưa | Ghi chú |
|-----------|---------|---------|
| Device state machine | ✅ | 6 states: DISCONNECTED → CONNECTING → READY → BUSY → ERROR → DEAD |
| Server-side logging | ✅ | `_log()` → ring buffer 50 dòng + stdout |
| WS broadcast status | ✅ | `_publish_status()` → frontend nhận `{ type: 'status' }` |
| Toast library (sonner) | ✅ | Đã cài, dùng ở nhiều nơi |
| DB session tracking | ✅ | `device_sessions` table (connected_at/disconnected_at) |
| **Disconnect notification** | ❌ | User không biết device nào mất |
| **Disconnect reason** | ❌ | Không ghi lý do vào DB |
| **Event log UI** | ❌ | Không có panel xem lịch sử events |
| **Event DB table** | ❌ | Chỉ có `u2_recovery_events` |

## Kiến trúc tổng quan

```
Device Agent (APK/Relay)
    ↓ disconnect/error/reconnect
DeviceClient._set_state()
    ↓ state change detected
    ├─→ DeviceEventLog.record(serial, event, reason)  ← NEW
    │       ├─→ In-memory ring buffer (last 200 events)
    │       └─→ DB: device_events table (persistent)
    └─→ WS broadcast { type: 'device_event', ... }    ← NEW
            ↓
Frontend
    ├─→ Toast notification (sonner)
    └─→ Event Log Panel (sidebar/drawer)
```

---

## Phase 1: Backend — Event Model & Recording

**Effort: ~2-3 giờ**

### 1.1 DB Model: `device_events` table

**File:** `db/models/device_event.py` (new)

```python
class DeviceEvent(Base):
    __tablename__ = "device_events"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    serial = Column(String, nullable=False, index=True)
    event = Column(String, nullable=False)       # "disconnected", "connected", "error", "state_change", "reconnected"
    reason = Column(String, nullable=True)        # "ws_closed", "ping_timeout", "agent_crash", "network_error"
    old_state = Column(String, nullable=True)     # "READY"
    new_state = Column(String, nullable=True)     # "DISCONNECTED"
    device_model = Column(String, nullable=True)  # "Galaxy S21" — snapshot tại thời điểm event
    device_brand = Column(String, nullable=True)  # "Samsung"
    extra_data = Column(JSON, nullable=True)      # { "ws_code": 1006, "duration": "2h15m", "ip": "..." }
    created_at = Column(DateTime, server_default=func.now(), index=True)
```

**Event types:**
| Event | Khi nào | Reason examples |
|-------|---------|-----------------|
| `connected` | Agent WS hello thành công | — |
| `disconnected` | Agent WS close/error | `ws_closed(1006)`, `ping_timeout`, `network_error` |
| `reconnected` | Device connect lại sau disconnect | `auto_reconnect` |
| `state_change` | State machine transition | `READY→ERROR`, `ERROR→DEAD` |
| `error` | Lỗi cụ thể (u2, scrcpy, etc.) | `scrcpy_crash`, `u2_timeout`, `minicap_failed` |

### 1.2 Event Recorder Service

**File:** `runtime/core/event_recorder.py` (new)

```python
class EventRecorder:
    """Records device events to in-memory buffer + DB."""

    def __init__(self, db_enabled: bool = True):
        self._buffer: deque[dict] = deque(maxlen=500)  # last 500 events across all devices
        self._db_enabled = db_enabled
        self._listeners: list[Callable] = []

    def record(self, serial: str, event: str, *,
               reason: str | None = None,
               old_state: str | None = None,
               new_state: str | None = None,
               device_model: str | None = None,
               device_brand: str | None = None,
               extra: dict | None = None) -> dict:
        entry = { ... }
        self._buffer.append(entry)
        self._notify_listeners(entry)
        if self._db_enabled:
            self._write_db(entry)  # fire-and-forget async
        return entry

    def get_recent(self, limit=50, serial: str | None = None) -> list[dict]:
        ...

    def add_listener(self, fn: Callable[[dict], None]) -> Callable:
        """WS manager subscribes here to broadcast events to frontend."""
        ...
```

### 1.3 Tích hợp vào DeviceClient

**File:** `runtime/core/device_client.py`

Sửa `_set_state()` (hiện tại ở line ~379):

```python
def _set_state(self, new: DeviceState) -> None:
    old = self._state
    if old == new:
        return
    self._state = new
    self._log(f"State: {old.value} → {new.value}")
    self._publish_status()

    # NEW: record event
    if self._event_recorder:
        event_type = "state_change"
        if new == DeviceState.DISCONNECTED:
            event_type = "disconnected"
        elif new == DeviceState.READY and old == DeviceState.DISCONNECTED:
            event_type = "reconnected"
        elif new == DeviceState.ERROR:
            event_type = "error"

        self._event_recorder.record(
            serial=self.serial,
            event=event_type,
            old_state=old.value,
            new_state=new.value,
            device_model=self.model,
            device_brand=self.brand,
        )
```

Sửa `on_agent_disconnected()` (line ~460) — thêm reason:

```python
def on_agent_disconnected(self, reason: str = "unknown", ws_code: int | None = None):
    ...
    if self._event_recorder:
        self._event_recorder.record(
            serial=self.serial,
            event="disconnected",
            reason=reason,
            old_state="READY",
            new_state="DISCONNECTED",
            device_model=self.model,
            device_brand=self.brand,
            extra={"ws_code": ws_code, "duration": dur_str, "ip": self._client_ip},
        )
```

### 1.4 Truyền reason từ WS handler

**File:** `web/ws.py` (line ~1224)

```python
except (WebSocketDisconnect, StarletteWSDisconnect) as exc:
    code = getattr(exc, "code", None)
    device.on_agent_disconnected(reason=f"ws_closed({code})", ws_code=code)

except Exception as exc:
    device.on_agent_disconnected(reason=f"ws_error: {type(exc).__name__}", ws_code=None)
```

---

## Phase 2: Backend — API & WS Broadcast

**Effort: ~1-2 giờ**

### 2.1 REST API endpoint

**File:** `api/routes/public.py` (thêm vào existing router)

```python
@api.get("/events")
async def api_events(
    request: Request,
    serial: Optional[str] = None,
    event: Optional[str] = None,   # filter by event type
    limit: int = 50,
    offset: int = 0,
):
    _verify_token_only(request)
    recorder = request.app.state.event_recorder
    events = recorder.get_recent(limit=limit + offset, serial=serial)
    if event:
        events = [e for e in events if e["event"] == event]
    return {"total": len(events), "events": events[offset:offset+limit]}
```

### 2.2 WS broadcast device events

**File:** `web/ws.py` — WebSocketManager

EventRecorder listener → broadcast `device_event` message to all connected frontends:

```python
# In WebSocketManager.__init__ or setup:
event_recorder.add_listener(self._on_device_event)

async def _on_device_event(self, event: dict):
    msg = {"type": "device_event", **event}
    # broadcast to all connections' status queues
    async with self._lock:
        for conn_id, conn in self._connections.items():
            for q in self._status_queues.get(conn_id, {}).values():
                _sync_put(q, msg)
```

---

## Phase 3: Frontend — Toast Notifications

**Effort: ~1-2 giờ**

### 3.1 Thêm message type

**File:** `front-end/src/features/devices/types.ts`

```typescript
// Add to WsMessage union:
| { type: 'device_event'; serial: string; event: string; reason?: string;
    device_model?: string; device_brand?: string; old_state?: string;
    new_state?: string; created_at: string; extra_data?: Record<string, unknown> }
```

### 3.2 Hook xử lý device events

**File:** `front-end/src/features/devices/hooks/use-device-farm.ts`

Trong WS message handler, thêm case cho `device_event`:

```typescript
case 'device_event': {
  const { serial, event, reason, device_model, device_brand } = msg;
  const label = `${device_brand || ''} ${device_model || ''} (${serial})`.trim();

  if (event === 'disconnected') {
    toast.error(`📱 ${label} disconnected`, {
      description: reason || 'Connection lost',
      duration: 8000,
    });
  } else if (event === 'reconnected') {
    toast.success(`📱 ${label} reconnected`, { duration: 5000 });
  } else if (event === 'error') {
    toast.warning(`📱 ${label} error`, {
      description: reason,
      duration: 6000,
    });
  }

  // Store event in local state for event log panel
  setEvents(prev => [msg, ...prev].slice(0, 200));
  break;
}
```

### 3.3 Sound notification (optional)

Dùng `new Audio('/sounds/disconnect.mp3').play()` khi device disconnect để user biết dù không nhìn màn hình.

---

## Phase 4: Frontend — Event Log Panel

**Effort: ~2-3 giờ**

### 4.1 Event Log Panel Component

**File:** `front-end/src/features/devices/components/event-log-panel.tsx` (new)

- Sheet/Drawer bên phải (giống task-panel.tsx hiện có)
- Hiển thị danh sách events mới nhất (từ WS real-time + fetch API `/api/events`)
- Filter theo: serial, event type, time range
- Mỗi event row hiển thị:
  - Icon theo event type (🔴 disconnect, 🟢 connect, ⚠️ error)
  - Device name (brand + model + serial)
  - Reason
  - Timestamp (relative: "2 phút trước")
- Auto-scroll khi có event mới
- Badge count trên nút mở panel (số events unread)

### 4.2 Tích hợp vào Dashboard

**File:** `front-end/src/features/devices/components/device-farm.tsx`

Thêm nút 🔔 ở header cạnh WS status indicator → mở Event Log Panel.

---

## Phase 5: DB Migration & Cleanup

**Effort: ~1 giờ**

### 5.1 Alembic migration

```python
def upgrade():
    op.create_table(
        'device_events',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('serial', sa.String(), nullable=False, index=True),
        sa.Column('event', sa.String(), nullable=False),
        sa.Column('reason', sa.String(), nullable=True),
        sa.Column('old_state', sa.String(), nullable=True),
        sa.Column('new_state', sa.String(), nullable=True),
        sa.Column('device_model', sa.String(), nullable=True),
        sa.Column('device_brand', sa.String(), nullable=True),
        sa.Column('extra_data', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), index=True),
    )
```

### 5.2 Auto-cleanup cron

Event log sẽ lớn theo thời gian. Thêm cleanup task:
- Giữ events 30 ngày gần nhất
- Chạy mỗi ngày 1 lần (hoặc khi server start)

---

## Thứ tự triển khai (recommended)

```
Phase 1 (Backend core)     ████████░░  ~2-3h
Phase 5 (DB migration)     ██░░░░░░░░  ~1h     ← chạy song song Phase 1
Phase 2 (API + WS)         ████░░░░░░  ~1-2h
Phase 3 (Frontend toast)   ████░░░░░░  ~1-2h
Phase 4 (Event log panel)  ██████░░░░  ~2-3h
                                        ─────
                              Total:    ~7-11h
```

**MVP nhanh nhất:** Phase 1 + 2 + 3 (toast only, không cần panel) = **~4-6 giờ**

---

## Các file cần tạo/sửa

### Tạo mới:
| File | Mô tả |
|------|--------|
| `db/models/device_event.py` | SQLAlchemy model |
| `runtime/core/event_recorder.py` | Event recording service |
| `front-end/src/features/devices/components/event-log-panel.tsx` | UI panel |
| `alembic/versions/xxx_add_device_events.py` | Migration |

### Sửa:
| File | Thay đổi |
|------|----------|
| `runtime/core/device_client.py` | Inject EventRecorder, gọi record() khi state change |
| `web/ws.py` | Truyền reason vào on_agent_disconnected, broadcast device_event |
| `front-end/src/features/devices/types.ts` | Thêm device_event message type |
| `front-end/src/features/devices/hooks/use-device-farm.ts` | Handle device_event → toast |
| `front-end/src/features/devices/components/device-farm.tsx` | Thêm event log button |
| `api/routes/public.py` | Thêm GET /api/events |
| `main.py` | Khởi tạo EventRecorder, inject vào manager |
| `db/models/__init__.py` | Import DeviceEvent |

---

## Rủi ro & lưu ý

1. **Performance:** Event recording phải fire-and-forget (async DB write), không block frame relay
2. **Memory:** Ring buffer maxlen=500 events, không để leak
3. **DB size:** Cần auto-cleanup hoặc partition theo tháng
4. **Race condition:** EventRecorder listeners chạy trên event loop, phải thread-safe
5. **Backward compat:** Frontend cũ nhận `device_event` message sẽ ignore (unknown type) — OK
