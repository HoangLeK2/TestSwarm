# Device Farm

Android device-farm platform for operating real devices from a web dashboard,
automation scenarios, scheduled campaigns, and MCP tools for AI agents.

## Table of Contents

- [Repository Structure](#repository-structure)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Quick Start](#quick-start)
- [Environment Setup](#environment-setup)
- [Installation](#installation)
- [Run Project](#run-project)
- [Health Checks](#health-checks)
- [Development Commands](#development-commands)
- [Troubleshooting](#troubleshooting)
- [Documentation](#documentation)

## Repository Structure

The repository is a full-stack workspace:

| Area | Path | Purpose |
|---|---|---|
| Backend | `device_farm/` | FastAPI API, device runtime, Temporal workers, relay server, MCP server |
| Frontend | `front-end/` | Next.js dashboard and generated Device Farm API client |
| Local relay | `agent-boot/` | Runs on a machine with ADB access to Android devices |
| Docs | `docs/` | Product, module, API, data, and implementation documentation |
| Android service | `STFService.apk/` | Android-side service/app sources and bundle assets |

## Architecture

```text
Dashboard browser
  -> Next.js frontend (:3000)
  -> FastAPI backend (:8081)
  -> Postgres, Redis, Temporal
  -> gRPC relay (:50051)
  -> agent-boot on an ADB host
  -> Android devices
```

Default local ports:

| Port | Service |
|---:|---|
| `3000` | Next.js dashboard |
| `8081` | Backend API and WebSocket endpoints |
| `50051` | gRPC relay for `agent-boot` |
| `5433` | Postgres published from Docker Compose |
| `6379` | Redis |
| `5540` | Redis UI |
| `7233` | Temporal gRPC |
| `8233` | Temporal UI |

## Tech Stack

| Layer | Main technologies |
|---|---|
| Backend | Python, FastAPI, SQLAlchemy async, Temporal, Redis, gRPC, MCP server |
| Frontend | Next.js 15, React 19, TypeScript, Tailwind CSS, TanStack Query, Zustand |
| Local device relay | Python, `uv`, Android Platform Tools, uiautomator2, scrcpy, gRPC |
| Infrastructure | Docker Compose, Postgres, Redis, Temporal |

## Prerequisites

- Docker and Docker Compose v2 for the full local stack.
- Python with `uv`. Use Python 3.13 for local Python work; the backend supports
  `>=3.11,<3.14`, and `agent-boot` requires `>=3.13,<3.14`.
- Node.js 22 and pnpm 8.6.x for frontend development.
- Android Platform Tools (`adb`) for real-device operation.
- Android devices with USB debugging or wireless debugging enabled.

## Quick Start

Use this path when you want the full local stack in Docker:

```bash
cp .env.example .env
```

For a dashboard opened from the same machine, make sure the browser-facing URLs
in the root `.env` are set before the first frontend build:

```dotenv
NEXT_PUBLIC_PRODUCT_API_URL=http://localhost:8081
NEXT_PUBLIC_DEVICE_FARM_WS_URL=ws://localhost:8081/ws
```

Then start the stack:

```bash
docker compose up -d --build
docker compose ps
```

Then open:

- Dashboard: `http://localhost:3000`
- Backend liveness: `http://localhost:8081/api/live`
- Backend readiness: `http://localhost:8081/api/ready`
- Temporal UI: `http://localhost:8233`
- Redis UI: `http://localhost:5540`

For real devices, configure and run `agent-boot` on the machine with ADB access.
Before starting it, set `RELAY_API_KEY`, `RELAY_ENROLLMENT_TOKEN`, and the
`AGENT_BOOT_CONTENT_DATABASE_URL` note from [Agent boot](#agent-boot) in
`agent-boot/.env`:

```bash
cd agent-boot
cp .env.example .env
uv sync
adb devices
uv run main.py --relay-only
```

## Environment Setup

Never commit `.env` files. Start from the templates and edit for your machine:

```bash
cp .env.example .env
cp device_farm/.env.example device_farm/.env
cp front-end/.env.example front-end/.env
cp agent-boot/.env.example agent-boot/.env
```

Important variables:

| Variable | Used by | Notes |
|---|---|---|
| `DATABASE_URL`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD` | Backend, Compose | Root `.env.example` is set for in-compose Postgres. Host-run backend should use `localhost:5433`. |
| `SECRET_KEY` | Backend | Required for JWT auth outside throwaway local runs. |
| `RELAY_API_KEY` | Backend, `agent-boot` | Must match on both sides when relay auth is enabled. |
| `RELAY_SERVER` | `agent-boot` | Use `localhost:50051` for local gRPC relay. |
| `NEXT_PUBLIC_PRODUCT_API_URL` | Frontend browser bundle | Browser-reachable backend origin without `/api` suffix, for example `http://localhost:8081` or the public backend domain. Rebuild frontend if changed. |
| `NEXT_PUBLIC_DEVICE_FARM_WS_URL` | Frontend browser bundle | Usually `ws://localhost:8081/ws` for local Docker. |
| `DEVICE_FARM_URL` | MCP server | Backend URL, default `http://localhost:8081`. |
| `MCP_AUTH_TOKEN` | MCP server | Bearer token for authenticated MCP device, session, campaign, content, account, and scenario tools. |

## Installation

### Docker stack

The root Compose stack builds and runs backend, frontend, Postgres, Redis,
Temporal, Temporal UI, and Redis UI.

```bash
cp .env.example .env
docker compose build
```

Edit `.env` before building if the browser-facing backend URL, WebSocket URL,
database credentials, relay API key, or secrets differ from the defaults. The
`NEXT_PUBLIC_*` variables are baked into the frontend image during build, so
changing them later requires rebuilding the frontend image.

### Backend local development

```bash
cd device_farm
cp .env.example .env
uv sync
```

If you use the root Docker services for Postgres, Redis, and Temporal while
running the backend on the host, set these in `device_farm/.env`:

```dotenv
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/device_farm
TEMPORAL_SERVER_URL=localhost:7233
REDIS_URL=redis://localhost:6379/0
FARM_AGENT_BOOT=0
```

`FARM_AGENT_BOOT=0` is recommended when you run `agent-boot` manually in a
separate terminal. Database migrations run automatically during backend startup;
there is no separate Alembic-style migration command.

### Frontend local development

```bash
cd front-end
cp .env.example .env
pnpm install --frozen-lockfile
```

For host development, keep `front-end/.env` pointed at the host backend:

```dotenv
NEXT_PUBLIC_PRODUCT_API_URL=http://localhost:8081
NEXT_PUBLIC_DEVICE_FARM_WS_URL=ws://localhost:8081/ws
```

### Agent boot

`agent-boot` runs on the machine that can reach the Android devices through
ADB. Install Android Platform Tools first.

```bash
cd agent-boot
cp .env.example .env
uv sync
adb devices
```

Set at least:

```dotenv
RELAY_MODE=grpc
RELAY_SERVER=localhost:50051
RELAY_API_KEY=<same value as backend>
RELAY_ENROLLMENT_TOKEN=<token from the Relay Agents page>
```

If `AGENT_BOOT_CONTENT_DB_ENABLED=1` remains enabled, also point
`AGENT_BOOT_CONTENT_DATABASE_URL` at a reachable Postgres instance. With the root
Compose stack on the same machine, use:

```dotenv
AGENT_BOOT_CONTENT_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/device_farm
```

Set `AGENT_BOOT_CONTENT_DB_ENABLED=0` when you only need relay/device control and
do not want `agent-boot` to write content extraction rows directly.

## Run Project

### Run the full Docker stack

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f farm
```

Open:

- Dashboard: `http://localhost:3000`
- Backend liveness: `http://localhost:8081/api/live`
- Backend readiness: `http://localhost:8081/api/ready`
- Temporal UI: `http://localhost:8233`
- Redis UI: `http://localhost:5540`

Stop the stack:

```bash
docker compose down
```

### Run deploy-style Compose with external Postgres

`docker-compose.deploy.yml` is for an environment where Postgres is managed
outside this Compose file. Edit `.env` so `DB_HOST`, `DB_PORT`, `DB_NAME`,
`DB_USER`, and `DB_PASSWORD` point to that database. Also point `REDIS_URL` to an
external Redis instance or leave it blank to use in-memory state only. Set
`DB_CONNECTION_LIMIT` to the real PostgreSQL `max_connections`; deploy Compose
fails fast when this value is missing.

```bash
cp .env.example .env
docker compose -f docker-compose.deploy.yml up -d
docker compose -f docker-compose.deploy.yml ps
```

### Run infrastructure in Docker and backend/frontend on the host

Start only shared infrastructure:

```bash
cp .env.example .env
docker compose up -d postgres redis temporal temporal-ui
```

Run backend:

```bash
cd device_farm
uv run main.py
```

Or run the installed console script:

```bash
uv run device-farm
```

Run frontend in another terminal:

```bash
cd front-end
pnpm dev
```

Run the local relay in another terminal:

```bash
cd agent-boot
uv run main.py --relay-only
```

For first-time device bootstrap, use:

```bash
cd agent-boot
uv run main.py
```

The web backend starts Temporal workers in-process when `temporal.enabled=true`.
To run a standalone worker process instead, use:

```bash
cd device_farm
uv run python -m temporal.worker_main
```

### Run MCP tools for AI agents

The backend must already be running.

```bash
./scripts/run_device_farm_mcp.sh
```

Or from the backend directory:

```bash
cd device_farm
uv run python -m mcp.server
```

See `device_farm/mcp/README.md` for Cursor and token setup.

## Health Checks

```bash
curl -fsS http://localhost:8081/api/live
curl -fsS http://localhost:8081/api/ready
adb devices
```

Expected basics:

- `/api/live` returns `{"status":"ok"}`.
- `/api/ready` returns `status: ok` or `status: degraded` with failing checks.
- `adb devices` shows the target serial with state `device`.

## Development Commands

Backend:

```bash
cd device_farm
uv run pytest
uv run export-openapi
```

Frontend:

```bash
cd front-end
pnpm dev
pnpm build
pnpm start
pnpm lint:strict
pnpm gen:api
```

Regenerate the frontend API client after backend API changes:

```bash
cd device_farm
uv run export-openapi
cp swagger/openapi.json ../front-end/generate/openapi.json
cd ../front-end
pnpm gen:api
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Compose fails before starting services | Run `docker compose config --quiet` and check `.env` values. |
| Backend cannot connect to DB from host | Use `DATABASE_URL=postgresql://postgres:postgres@localhost:5433/device_farm`. |
| Frontend shows empty data or WebSocket errors | Check `NEXT_PUBLIC_PRODUCT_API_URL`, `NEXT_PUBLIC_DEVICE_FARM_WS_URL`, then restart/rebuild frontend. |
| `agent-boot` cannot connect | Confirm `RELAY_SERVER`, `RELAY_API_KEY`, firewall, and that backend exposes `50051`. |
| No devices online | Run `adb devices`, confirm USB/wireless debugging, then restart `agent-boot`. |
| Temporal workflows do not run | Check `TEMPORAL_SERVER_URL`, `docker compose ps temporal`, and Temporal UI at `:8233`. |

## Documentation

- `docs/README.md` - documentation entrypoint.
- `docs/modules/README.md` - module boundaries and source ownership.
- `docs/api/route-matrix.md` - exposed API routes and frontend client mapping.
- `docs/data/schema.md` - database schema ownership and migrations.
- `device_farm/README.md` - backend notes.
- `front-end/README.md` - frontend notes.
- `agent-boot/README.md` and `agent-boot/INSTALL.md` - relay setup and customer installation.
- `device_farm/mcp/README.md` - MCP tools and AI-agent integration.
