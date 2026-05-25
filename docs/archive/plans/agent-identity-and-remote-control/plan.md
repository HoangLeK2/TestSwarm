# Implementation Plan: Agent Identity Tracking + Remote Control API

## Overview

Persist and expose relay-agent identity (who owns which device serial) plus a
typed gRPC control channel for bootstrap/restart commands triggerable from the UI.

**Key constraint**: `RelayService.Stream` is NOT touched — it carries H264 video
frames at high throughput. Mixing control messages into it causes head-of-line
blocking. Instead, a new `AgentControlService` runs on the same gRPC port as a
separate, lightweight bidi stream.

## Requirements

- R1: Server persists relay-agent records (relay_id, hostname, ip, version, serials, timestamps) in Postgres.
- R2: `GET /api/relay-agents` and `GET /api/relay-agents/{relay_id}` expose current state.
- R3: `POST /api/devices/{device_id}/bootstrap|restart-u2|restart-atx` trigger the corresponding agent command and return the result.
- R4: `POST /api/relay-agents/{relay_id}/bootstrap-all` bootstraps every serial managed by that relay.
- R5: Device list UI shows relay-agent badge per device; device actions include Bootstrap / Restart u2 / Restart atx buttons.
- R6: No-op when relay is disconnected or serial unknown — return 409/503 with clear error, never hang.

## Non-Goals

- No changes to `RelayService.Stream` or its proto messages (`AgentMsg`, `ControlMsg`, `VideoFrame`).
- No auth/permission model beyond the existing `x-relay-api-key`.
- No relay-agent "kick" / force-disconnect API.
- No historical relay-session table (one row per relay_id, updated in place).
- No Redis schema changes.
- No WS protocol changes (WS mode keeps existing JSON for identity/commands as-is).

## Architecture

### Two independent gRPC channels from agent-boot

```
agent-boot                          device_farm server
    │                                   │
    │  Channel 1 (existing, unchanged)  │
    ├──RelayService.Stream──────────────►│  H264 video, scrcpy binary
    │   AgentMsg{VideoFrame}            │
    │◄──ControlMsg{scrcpy ctrl}─────────┤
    │                                   │
    │  Channel 2 (NEW, control only)    │
    ├──AgentControlService.ControlStream►│  identity, commands
    │   AgentControlMsg{register/hb/result}│
    │◄──ServerControlMsg{bootstrap/...}─┤
```

### Proto additions (`relay.proto`)

```protobuf
// ── NEW service, separate from RelayService ──────────────────────────
service AgentControlService {
  rpc ControlStream(stream AgentControlMsg) returns (stream ServerControlMsg);
}

// Agent → Server
message AgentControlMsg {
  oneof payload {
    RegisterMsg      register  = 1;
    HeartbeatMsg     heartbeat = 2;
    CommandResultMsg result    = 3;
  }
}

message RegisterMsg {
  string          relay_id      = 1;
  repeated string serials       = 2;
  string          hostname      = 3;
  string          ip            = 4;
  string          agent_version = 5;
}

message HeartbeatMsg {
  string          relay_id = 1;
  repeated string serials  = 2;
  repeated DeviceCaps caps = 3;
}

message DeviceCaps {
  string serial          = 1;
  string android_version = 2;
  int32  sdk             = 3;
  string brand           = 4;
  string model           = 5;
  bool   has_u2          = 6;
  bool   has_stf         = 7;
}

message CommandResultMsg {
  string msg_id    = 1;
  bool   ok        = 2;
  int32  exit_code = 3;
  string output    = 4;
  string error     = 5;
}

// Server → Agent
message ServerControlMsg {
  oneof payload {
    RegisterAck    ack         = 1;
    BootstrapCmd   bootstrap   = 2;
    RestartU2Cmd   restart_u2  = 3;
    RestartAtxCmd  restart_atx = 4;
    ShellCmd       shell       = 5;
  }
}

message RegisterAck  { string message = 1; }
message BootstrapCmd  { string msg_id = 1; string serial = 2; int32 timeout = 3; }
message RestartU2Cmd  { string msg_id = 1; string serial = 2; int32 timeout = 3; }
message RestartAtxCmd { string msg_id = 1; string serial = 2; int32 timeout = 3; }
message ShellCmd      { string msg_id = 1; string serial = 2; string cmd = 3; int32 timeout = 4; }
```

### File changes summary

```
relay.proto                               ← add AgentControlService + new messages
agent-boot/relay/grpc_gen/                ← regen stubs (relay_pb2.py + relay_pb2_grpc.py)
agent-boot/relay/control_client.py        ← NEW: AgentControlClient (Channel 2 handler)
agent-boot/relay/agent.py                 ← wire ControlClient alongside existing stream
device_farm/runtime/transports/
  adb_relay_server.py                     ← existing (unchanged for Stream logic)
  agent_control_servicer.py              ← NEW: AgentControlServicer (gRPC server-side)
device_farm/db/models/relay_agent.py      ← NEW: RelayAgent SQLAlchemy model
device_farm/db/migrations/030_relay_agents.py  ← NEW: create table
device_farm/db/crud/relay_agent.py        ← NEW: upsert/heartbeat/offline/list/get
device_farm/api/schemas/relay_agent.py   ← NEW: Pydantic schemas
device_farm/api/routes/relay_agents.py   ← NEW: REST endpoints
device_farm/api/routes/devices.py        ← add bootstrap/restart-u2/restart-atx
device_farm/web/server.py                ← register AgentControlServicer on gRPC server
front-end/src/features/devices/
  services/manage-api.ts                 ← add deviceControlApi + relayAgentsApi
  components/device-list/columns.tsx     ← relay badge column
  components/device-list/row-actions.tsx ← Bootstrap/Restart buttons
```

---

## Phase 1 — Proto & stub regen

**1. Update `relay.proto`**

Add `AgentControlService` + all new messages above. Do NOT change any existing
message or the `RelayService` definition. Existing generated code stays valid.

**2. Regen stubs**

```bash
cd agent-boot
python -m grpc_tools.protoc \
  -I. --python_out=relay/grpc_gen --grpc_python_out=relay/grpc_gen \
  relay.proto
```

Run the same regen on the server side (or copy the pb2 files — they're identical).
Commit both sides together so proto + stubs are always in sync.

**3. Verify existing tests pass**

`python -m pytest relay/tests/ -v` — no changes to existing message classes, so
all existing tests must still pass. This is a strict pre-condition for the next phases.

---

## Phase 2 — Agent-side: AgentControlClient

**4. New file `agent-boot/relay/control_client.py`**

Manages Channel 2 independently. Key responsibilities:
- Connect to same server address as Channel 1
- Send `RegisterMsg` on connect, `HeartbeatMsg` every 30s
- Receive `ServerControlMsg`, dispatch to command executor (reuses `_execute_command` from `agent.py`)
- Send `CommandResultMsg` back
- Reconnect with exponential backoff (same cap 8s as existing stream) independently of Channel 1

```python
class AgentControlClient:
    def __init__(self, server_addr: str, api_key: str, relay_agent: "RelayAgent"):
        self._addr       = server_addr
        self._api_key    = api_key
        self._agent      = relay_agent   # back-ref to access _execute_command, _registry

    async def run(self):
        """Outer retry loop — mirrors RelayAgent's video stream retry."""
        attempt, base = 0, 0.5
        while True:
            try:
                await self._stream_once()
                attempt = 0
            except Exception as exc:
                attempt += 1
                delay = min(base * (2 ** attempt), 8.0) * (1 + 0.2 * random.random())
                logger.warning("control stream failed (attempt %d): %s — retry %.1fs", attempt, exc, delay)
                await asyncio.sleep(delay)

    async def _stream_once(self):
        meta = [("x-relay-api-key", self._api_key)] if self._api_key else []
        async with grpc.aio.insecure_channel(self._addr) as channel:
            stub = AgentControlServiceStub(channel)
            send_queue: asyncio.Queue[AgentControlMsg] = asyncio.Queue()

            # Send register immediately
            await send_queue.put(AgentControlMsg(register=RegisterMsg(
                relay_id=self._agent._relay_id,
                serials=list(self._agent._registry.online_serials()),
                hostname=socket.gethostname(),
                ip=_primary_lan_ip(),
                agent_version=_AGENT_VERSION,
            )))

            async def _producer():
                while True:
                    msg = await send_queue.get()
                    yield msg

            heartbeat_task = asyncio.create_task(self._heartbeat_loop(send_queue))
            try:
                async for ctrl in stub.ControlStream(_producer(), metadata=meta):
                    await self._handle(ctrl, send_queue)
            finally:
                heartbeat_task.cancel()

    async def _heartbeat_loop(self, q):
        while True:
            await asyncio.sleep(30)
            await q.put(AgentControlMsg(heartbeat=HeartbeatMsg(
                relay_id=self._agent._relay_id,
                serials=list(self._agent._registry.online_serials()),
            )))

    async def _handle(self, msg: ServerControlMsg, q: asyncio.Queue):
        kind = msg.WhichOneof("payload")
        if kind == "ack":
            logger.info("control channel registered: %s", msg.ack.message)
        elif kind in ("bootstrap", "restart_u2", "restart_atx", "shell"):
            cmd = getattr(msg, kind)
            cmd_type = {"bootstrap": CMD_BOOTSTRAP, "restart_u2": CMD_RESTART_U2,
                        "restart_atx": CMD_RESTART_ATX, "shell": CMD_SHELL}[kind]
            raw_cmd  = cmd.cmd if hasattr(cmd, "cmd") else ""
            result   = await asyncio.get_event_loop().run_in_executor(
                None,
                self._agent._execute_command,
                cmd.msg_id, cmd.serial, raw_cmd, int(cmd.timeout), cmd_type,
            )
            res = json.loads(result)
            await q.put(AgentControlMsg(result=CommandResultMsg(
                msg_id    = cmd.msg_id,
                ok        = res.get("ok", False),
                exit_code = res.get("exit_code", -1),
                output    = res.get("output", ""),
                error     = res.get("error", ""),
            )))
```

**5. Wire into `RelayAgent.run()`** (`agent-boot/relay/agent.py`)

Only when `relay_mode == "grpc"`:
```python
if self._relay_mode == "grpc":
    ctrl = AgentControlClient(self._grpc_addr, self._api_key, self)
    asyncio.create_task(ctrl.run())   # runs independently, never awaited
```

The task runs for the lifetime of the process. If `ctrl.run()` crashes, the outer
retry loop in `AgentControlClient` restarts it — Channel 1 (video) is unaffected.

> WS mode: keep existing JSON register/heartbeat/command handling in `agent.py` unchanged.
> No new code for WS — it already works.

---

## Phase 3 — Server-side: AgentControlServicer

**6. New file `device_farm/runtime/transports/agent_control_servicer.py`**

Implements the gRPC servicer for `AgentControlService`. Manages connections from
all agent-boot processes. Uses the same in-memory registry pattern as `AdbRelayManager`
but dedicated to the control plane.

```python
from grpc_gen.relay_pb2_grpc import AgentControlServiceServicer
from grpc_gen.relay_pb2 import (
    AgentControlMsg, ServerControlMsg,
    RegisterAck, CommandResultMsg,
)
import asyncio, uuid, logging

log = logging.getLogger(__name__)

class ControlConnection:
    """One per connected agent-boot (control channel)."""
    def __init__(self, relay_id: str, send_q: asyncio.Queue):
        self.relay_id = relay_id
        self._q       = send_q
        self._pending: dict[str, asyncio.Future] = {}

    async def send_command(self, cmd_msg: ServerControlMsg, timeout: float) -> dict:
        msg_id = cmd_msg.WhichOneof("payload") and getattr(
            cmd_msg, cmd_msg.WhichOneof("payload")).msg_id
        loop = asyncio.get_running_loop()
        fut  = loop.create_future()
        self._pending[msg_id] = fut
        await self._q.put(cmd_msg)
        try:
            return await asyncio.wait_for(asyncio.shield(fut), timeout=timeout + 10)
        except asyncio.TimeoutError:
            return {"ok": False, "error": "timeout", "exit_code": -1, "output": ""}
        finally:
            self._pending.pop(msg_id, None)

    def resolve(self, result: CommandResultMsg):
        fut = self._pending.get(result.msg_id)
        if fut and not fut.done():
            fut.set_result({
                "ok": result.ok, "exit_code": result.exit_code,
                "output": result.output, "error": result.error,
            })


class AgentControlServicer(AgentControlServiceServicer):
    def __init__(self):
        self._conns:  dict[str, ControlConnection] = {}   # relay_id → conn
        self._serial_index: dict[str, str] = {}            # serial → relay_id

        # Persistence callbacks (wired from web/server.py)
        self._on_register:  callable = None
        self._on_heartbeat: callable = None
        self._on_offline:   callable = None

    def set_persistence_callbacks(self, on_register, on_heartbeat, on_offline):
        self._on_register  = on_register
        self._on_heartbeat = on_heartbeat
        self._on_offline   = on_offline

    # ── gRPC bidi stream ────────────────────────────────────────────────
    async def ControlStream(self, request_iterator, context):
        relay_id = None
        send_q: asyncio.Queue[ServerControlMsg] = asyncio.Queue()
        conn: ControlConnection = None

        async def _sender():
            while True:
                msg = await send_q.get()
                yield msg

        sender = _sender()
        try:
            async for msg in request_iterator:
                kind = msg.WhichOneof("payload")

                if kind == "register":
                    r = msg.register
                    relay_id = r.relay_id or f"relay-{uuid.uuid4().hex[:8]}"
                    conn = ControlConnection(relay_id, send_q)
                    self._conns[relay_id] = conn
                    for s in r.serials:
                        self._serial_index[s] = relay_id
                    await send_q.put(ServerControlMsg(ack=RegisterAck(
                        message=f"registered {len(r.serials)} serials"
                    )))
                    if self._on_register:
                        asyncio.create_task(_safe(self._on_register({
                            "relay_id": relay_id,
                            "hostname": r.hostname,
                            "ip":       r.ip,
                            "version":  r.agent_version,
                            "serials":  list(r.serials),
                        })))

                elif kind == "heartbeat" and conn:
                    h = msg.heartbeat
                    new_serials = set(h.serials)
                    old_serials = {s for s, rid in self._serial_index.items() if rid == relay_id}
                    for s in old_serials - new_serials:
                        self._serial_index.pop(s, None)
                    for s in new_serials:
                        self._serial_index[s] = relay_id
                    conn.serials = new_serials
                    if self._on_heartbeat:
                        asyncio.create_task(_safe(self._on_heartbeat({
                            "relay_id": relay_id,
                            "serials":  sorted(new_serials),
                        })))

                elif kind == "result" and conn:
                    conn.resolve(msg.result)

        finally:
            if relay_id:
                self._conns.pop(relay_id, None)
                for s in list(self._serial_index):
                    if self._serial_index.get(s) == relay_id:
                        del self._serial_index[s]
                if self._on_offline:
                    asyncio.create_task(_safe(self._on_offline(relay_id)))

        # stream must yield — iterate sender (never reached in normal flow,
        # but required by gRPC servicer contract for server-side streaming)
        async for m in sender:
            yield m

    # ── Public API (called by REST endpoints) ───────────────────────────
    def conn_for_serial(self, serial: str) -> ControlConnection | None:
        rid = self._serial_index.get(serial)
        return self._conns.get(rid) if rid else None

    def conn_for_relay(self, relay_id: str) -> ControlConnection | None:
        return self._conns.get(relay_id)

    async def bootstrap(self, serial: str, timeout=180.0) -> dict:
        return await self._send(serial, "bootstrap", timeout)

    async def restart_u2(self, serial: str, timeout=60.0) -> dict:
        return await self._send(serial, "restart_u2", timeout)

    async def restart_atx(self, serial: str, timeout=30.0) -> dict:
        return await self._send(serial, "restart_atx", timeout)

    async def _send(self, serial: str, kind: str, timeout: float) -> dict:
        conn = self.conn_for_serial(serial)
        if not conn:
            return {"ok": False, "error": "no control channel for serial", "exit_code": -1, "output": ""}
        msg_id = str(uuid.uuid4())
        cmd_cls = {"bootstrap": BootstrapCmd, "restart_u2": RestartU2Cmd,
                   "restart_atx": RestartAtxCmd}[kind]
        ctrl = ServerControlMsg(**{kind: cmd_cls(msg_id=msg_id, serial=serial, timeout=int(timeout))})
        return await conn.send_command(ctrl, timeout)


async def _safe(coro):
    try:
        await asyncio.wait_for(coro, timeout=2.0)
    except Exception as exc:
        log.warning("control persistence callback failed: %s", exc)
```

**7. Register servicer on gRPC server** (`device_farm/web/server.py`)

In the existing gRPC server setup block, add:
```python
from runtime.transports.agent_control_servicer import AgentControlServicer
from grpc_gen.relay_pb2_grpc import add_AgentControlServiceServicer_to_server

_ctrl_servicer = AgentControlServicer()
add_AgentControlServiceServicer_to_server(_ctrl_servicer, grpc_server)

# Wire persistence callbacks (same pattern as WS relay)
_ctrl_servicer.set_persistence_callbacks(_on_register, _on_heartbeat, _on_offline)
```

Expose `_ctrl_servicer` via `get_control_servicer()` for REST endpoints to call.

---

## Phase 4 — DB model, migration, CRUD

*(Identical to original plan — no changes from gRPC design decision)*

**8. `device_farm/db/models/relay_agent.py`**

```python
class RelayAgent(Base):
    __tablename__ = "relay_agents"
    id:                Mapped[str]              = mapped_column(String(36), primary_key=True, default=_uuid)
    relay_id:          Mapped[str]              = mapped_column(String(128), unique=True, nullable=False, index=True)
    hostname:          Mapped[str]              = mapped_column(String(255), default="")
    ip:                Mapped[str]              = mapped_column(String(64),  default="")
    version:           Mapped[str]              = mapped_column(String(32),  default="")
    serials:           Mapped[list]             = mapped_column(JSON, default=list)
    status:            Mapped[str]              = mapped_column(String(16), default="online")  # online|offline
    connected_at:      Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=_now)
    last_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    disconnected_at:   Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at:        Mapped[datetime]         = mapped_column(DateTime(timezone=True), default=_now)
```

**9. Migration `030_relay_agents.py`** — idempotent `CREATE TABLE IF NOT EXISTS`.

**10. CRUD `device_farm/db/crud/relay_agent.py`**

```python
async def upsert_relay_agent(db, *, relay_id, hostname, ip, version, serials) -> RelayAgent
async def update_relay_heartbeat(db, *, relay_id, serials) -> None
async def mark_relay_offline(db, relay_id: str) -> None
async def list_relay_agents(db) -> list[RelayAgent]
async def get_relay_agent(db, relay_id: str) -> Optional[RelayAgent]
```

**11. Startup reconciliation** (`web/server.py`, after `init_db()`):

```python
await db.execute(text("UPDATE relay_agents SET status='offline', disconnected_at=NOW() WHERE status='online'"))
```

Clears stale rows from a previous crash.

---

## Phase 5 — REST API

**12. Schemas** (`device_farm/api/schemas/relay_agent.py`)

```python
class RelayAgentOut(BaseModel):
    relay_id: str; hostname: str; ip: str; version: str
    serials: list[str]; status: str
    connected_at: datetime
    last_heartbeat_at: Optional[datetime] = None
    disconnected_at:   Optional[datetime] = None

class RelayCommandOut(BaseModel):
    ok: bool; output: str = ""; exit_code: int = -1; error: str = ""

class BootstrapAllResult(BaseModel):
    relay_id: str; total: int; ok: int; failed: int
    results: list[dict]
```

**13. Relay agents router** (`device_farm/api/routes/relay_agents.py`)

```python
@router.get("",             response_model=list[RelayAgentOut])
@router.get("/{relay_id}", response_model=RelayAgentOut)
@router.post("/{relay_id}/bootstrap-all", response_model=BootstrapAllResult)
```

`bootstrap-all` fans out with `asyncio.Semaphore(4)` — concurrency 4 per relay.

**14. Device control endpoints** (`device_farm/api/routes/devices.py`)

```python
@router.post("/{device_id}/bootstrap",   response_model=RelayCommandOut)
@router.post("/{device_id}/restart-u2",  response_model=RelayCommandOut)
@router.post("/{device_id}/restart-atx", response_model=RelayCommandOut)
```

Each: look up device by UUID → get serial → call `get_control_servicer().bootstrap(serial)` etc.
Return HTTP 200 always; `ok: false` carries semantic failure.

> **DEAD device**: CMD_BOOTSTRAP intentionally works even when device state is DEAD —
> bootstrap talks ADB directly, bypassing state machine. This is the recovery path.

**15. Register routers** (`device_farm/api/crud/router.py`) — include `relay_agents_router`.

---

## Phase 6 — Frontend (minimum viable)

**16. API client** (`front-end/src/features/devices/services/manage-api.ts`)

```ts
export const deviceControlApi = {
  bootstrap:  (id: string) => farmApi.post<RelayCommandOut>(`/devices/${id}/bootstrap`).then(r => r.data),
  restartU2:  (id: string) => farmApi.post<RelayCommandOut>(`/devices/${id}/restart-u2`).then(r => r.data),
  restartAtx: (id: string) => farmApi.post<RelayCommandOut>(`/devices/${id}/restart-atx`).then(r => r.data),
};
export const relayAgentsApi = {
  list:         () => farmApi.get<RelayAgentOut[]>('/relay-agents').then(r => r.data),
  bootstrapAll: (relayId: string) => farmApi.post<BootstrapAllResult>(`/relay-agents/${relayId}/bootstrap-all`).then(r => r.data),
};
```

**17. Relay badge** — fetch `relayAgentsApi.list()` alongside device list. Build
`serial → relay` map client-side (`staleTime: 15_000, refetchInterval: 30_000`).
New column shows `hostname` + online/offline dot.

**18. Device action menu** (`row-actions.tsx`) — Bootstrap (confirm dialog), Restart u2,
Restart atx. Toast on result. Disable while in-flight.

**19. (Phase 6b, deferrable)** Relay agents page `/relay-agents` with Bootstrap All button.

---

## Transport decision summary

| Message type | Transport | Channel |
|---|---|---|
| H264 video frames | gRPC / WS | Channel 1 (existing) |
| scrcpy binary control | gRPC / WS | Channel 1 (existing) |
| Identity (register/heartbeat) | **gRPC typed** / WS JSON | **Channel 2 (new)** / existing |
| Bootstrap / Restart commands | **gRPC typed** / WS JSON | **Channel 2 (new)** / existing |
| Command results | **gRPC typed** / WS JSON | **Channel 2 (new)** / existing |

WS mode: Channel 2 doesn't exist — identity and commands continue over the single
WS connection as JSON (no regressions, no code deletion).

gRPC mode: Channel 1 stays untouched. Channel 2 handles all non-video traffic.

---

## Merge order

```
Phase 1 (proto + regen) → Phase 2 (agent control client) → Phase 3 (server servicer)
→ Phase 4 (DB) → Phase 5 (REST API) → Phase 6 (frontend)
```

Phases 1–3 must ship together (proto contract must match on both sides).
Phases 4–6 are independently mergeable after Phase 3 lands.

## Risks & Mitigations

| Risk | Mitigation |
|---|---|
| gRPC stub version mismatch after regen | Pin `grpcio-tools` version in both `requirements.txt`; regen in CI |
| Agent opens Channel 2 before Channel 1 is ready | Channels are independent — order doesn't matter |
| `bootstrap-all` blocks for minutes | Semaphore(4) + document in UI; async background job is future scope |
| WS mode regression | WS code path unchanged; run existing WS tests in CI |
| Stale relay rows on server restart | Startup reconciliation (Phase 4, step 11) marks all online→offline |

## Success Criteria

- [ ] `relay_agents` table populated after agent reconnects via gRPC.
- [ ] `GET /api/relay-agents` returns connected relays with hostname + ip + serials.
- [ ] Kill agent-boot → row flips to `offline` immediately.
- [ ] `POST /api/devices/{id}/bootstrap` returns `{ok:true}`, device recovers from DEAD.
- [ ] `POST .../restart-u2` and `.../restart-atx` return `{ok:true}` on healthy device.
- [ ] `RelayService.Stream` (video) is completely unaffected during any control operation.
- [ ] Operator recovers a DEAD device from browser without SSH.
