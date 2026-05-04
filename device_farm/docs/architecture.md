# Device Farm — architecture

## Startup (`main.py`)

1. Load `.env` from the package directory (non-destructive: does not override existing env).
2. `load_config(FARM_CONFIG)` → YAML `config.yaml` by default.
3. Construct `TaskQueue`, `DeviceManager`, start `WatchdogThread` and `Dispatcher` on background threads.
4. Build FastAPI via `web.server.create_app` (templates, static, HTTP routers, WebSockets).
5. Run **uvicorn** in a **daemon thread** (main thread blocks on shutdown signal).

### FastAPI lifespan (`web/server.py`)

- Register asyncio loop with `DeviceManager`.
- Start periodic **heartbeat** task.
- If `database.enabled` in config: `init_db()` (PostgreSQL). Startup fails if DB init or migrations fail.

### Database migrations

- Migration files live in `db/migrations/[0-9]*.py` and run in filename order.
- Applied migrations are recorded in PostgreSQL table `schema_migrations` with a SHA-256 checksum.
- Already-applied files are skipped on later startups. If an applied migration file changes, startup fails; add a new migration instead of editing production history.
- Destructive migrations must validate legacy data before dropping columns/tables. For example, migration 019 aborts if any `content_items.run_id` row cannot be mapped to `execution_id`.
- SQLAlchemy `Base.metadata.create_all()` is disabled by default when `DEVICE_FARM_ENV` is `production`, `prod`, or `staging`. Set `FARM_DB_AUTO_CREATE_SCHEMA=1` only for an intentional bootstrap of an empty environment.

## HTTP surface

| Prefix | Source | When |
|--------|--------|------|
| Public / pages / device control | `api/mount.py` → `api/routes/*` | Always (see each router) |
| **CRUD** `/api/...` (users, orgs, campaigns, devices, auth) | `api/crud/router.py` | Only if `config.database.enabled` |

Device apps connect to the cloud **without ADB on the server**: local agent / app uses QR → WebSocket **`/device-agent`**. Dashboard/browser uses **`/ws`** for live UI.

## Where to add things

- **New authenticated REST entity** (JWT + DB): add route under `api/routes/`, include it in `api/crud/router.py`, schemas in `api/schemas/`, CRUD in `db/crud/`.
- **Streaming / touch / scrcpy / sessions**: `api/routes/device_control/` and mount via `api/routes/device_control/__init__.py` (wired from `api/mount.py`).
- **Device protocol / ADB / transports**: `runtime/transports/`, `runtime/core/`.
- **CLI / agents**: `scripts/` (root shims call into here).

## Environment variables

Canonical getters for the **server process** live in `core/env.py`. Below is the full reference (including optional tuning used in runtime and CLI).

### Server / process (`main`, `web`)

| Variable | Default | Purpose |
|----------|---------|---------|
| `FARM_CONFIG` | `config.yaml` | Path to YAML config |
| `FARM_RELOAD` | off | `1`/`true`/`yes` → uvicorn `--reload` |
| `FARM_FRONTEND_DIST` | (search) | Override directory for built SPA (`…/dist`) |
| `NGROK_ENABLED` | off | Expose HTTP port via ngrok |
| `NGROK_AUTHTOKEN` | empty | ngrok auth token |

### Auth / JWT

| Variable | Default | Purpose |
|----------|---------|---------|
| `SECRET_KEY` | *(required for DB auth)* | JWT signing |
| `JWT_ALGORITHM` | `HS256` | JWT alg |
| `ACCESS_EXPIRE_HOURS` | `1` | Access token TTL |
| `REFRESH_EXPIRE_DAYS` | `30` | Refresh token TTL |

### Database

| Variable | Default | Purpose |
|----------|---------|---------|
| `DATABASE_URL` | from `config.yaml` | Async SQLAlchemy DSN (see `db/database.py`) |
| `FARM_DB_AUTO_CREATE_SCHEMA` | off in production/staging, on elsewhere | Allow SQLAlchemy `create_all()` before migrations |

### Agents / local tools (scripts, not all via `core/env`)

| Variable | Typical use |
|----------|-------------|
| `DEVICE_FARM_WS` | Default WebSocket URL for local agent |
| `DEVICE_FARM_URL` | HTTP base URL for tools / AI client |
| `ADB` | Path to `adb` binary |
| `SCRCPY_JAR`, `SCRCPY_ADB_BIN` | scrcpy paths |

### Runtime tuning (optional)

| Variable | Purpose |
|----------|---------|
| `LOW_BW_MODE`, `LOW_BW_FRAME_SKIP` | Reduce streaming bandwidth |
| `U2_KEEPALIVE_INTERVAL` | uiautomator2 keepalive |
| `FORCE_MINITOUCH`, `DISABLE_U2` | Transport overrides |
| `AI_MCP_URL`, `SCENARIO_AI_*`, `OPENAI_*`, `GEMINI_*` | AI scenario backends |
