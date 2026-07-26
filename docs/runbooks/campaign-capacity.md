# Campaign Capacity Runbook

This runbook validates the campaign-processing control plane at the current
target of 120 concurrent devices. The probe exercises Temporal activity slots
and the real PostgreSQL activity pool without requiring physical phones or
mutating campaign/device data.

## Capacity budget

Keep every process that connects to the shared PostgreSQL instance inside one
explicit budget:

```text
web pool max
+ worker processes * activity pool max per worker
+ Temporal persistence allowance
+ recovery reserve
<= PostgreSQL connection limit
```

The local compose defaults are:

| Component | Calculation | Maximum |
|---|---:|---:|
| Web process | `8 + 2` | 10 |
| Activity workers | `7 * (4 + 0)` | 28 |
| Temporal allowance | configured budget | 40 |
| Recovery reserve | configured budget | 15 |
| Total budgeted | | 93 / 100 |

Seven workers at 20 concurrent activities provide 140 slots: 120 target slots
and 20 slots of headroom. Four database connections per worker remove the
measured two-connection activity bottleneck while retaining a 15-connection
recovery reserve. Do not raise the activity pool above four in this shared
database topology without reviewing the full connection budget. Production
must set `DB_CONNECTION_LIMIT` to its real database limit. A value of `0` is
advisory-only and should be used only while rolling out the validation.

## Configuration

The relevant environment variables are documented in `.env.example`:

- `TEMPORAL_WORKER_COUNT`
- `TEMPORAL_WORKER_MAX_CONCURRENT_ACTIVITIES`
- `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`
- `DB_ACTIVITY_POOL_SIZE`, `DB_ACTIVITY_MAX_OVERFLOW`
- `DB_CONNECTION_LIMIT`, `DB_CONNECTION_RESERVE`
- `TEMPORAL_DB_MAX_CONNECTIONS`
- `TEMPORAL_SQL_MAX_CONNS`, `TEMPORAL_SQL_MAX_IDLE_CONNS`
- `TEMPORAL_SQL_VIS_MAX_CONNS`, `TEMPORAL_SQL_VIS_MAX_IDLE_CONNS`
- `METRICS_ENABLED`, `METRICS_TOKEN`
- `EXECUTION_EVENT_OUTBOX_LEASE_SECONDS`

Startup fails when an explicit non-zero database limit is smaller than the
configured demand plus reserve. The activity and web pools stay independent so
long device work cannot consume the web pool.

## Local validation

Build and recreate the services before measuring so the running containers use
the candidate code:

```bash
docker compose build farm
docker compose up -d temporal farm
curl -fsS http://localhost:8081/api/health
cd device_farm
.venv/bin/python scripts/stress_temporal_capacity.py \
  --production-120 \
  --server localhost:7233 \
  --worker-count 7 \
  --activities-per-worker 20 \
  --db-pool-size 8 \
  --db-max-overflow 2 \
  --db-activity-pool-size 4 \
  --db-activity-max-overflow 0 \
  --json-output /tmp/temporal-capacity-120.json
```

The production-shaped suite passes only when:

- all 120 slot probes and all 120 database-hold probes succeed;
- Temporal schedule-to-start p95 is at most two seconds;
- slot latency p95 is at most 15 seconds;
- database-hold latency p95 is at most 30 seconds;
- no pool timeout or `too many clients` error occurs.

The harness reports effective slots as diagnostic data. It is not a pass/fail
gate because one wall-clock outlier can distort that estimate while p95 queue
delay remains healthy.

Inspect server connections before and after the run:

```sql
SHOW max_connections;
SELECT datname, state, count(*)
FROM pg_stat_activity
GROUP BY datname, state
ORDER BY datname, state;
```

## Metrics

Metrics are hidden by default. To expose the internal endpoint, set both:

```text
METRICS_ENABLED=1
METRICS_TOKEN=<strong-random-token>
```

Scrape with `Authorization: Bearer <token>`. Never publish the endpoint without
network-level access control. Monitor:

- dispatch HTTP and phase duration;
- outbox backlog, oldest unpublished age, batch size/duration, and failures;
- database pool pressure and PostgreSQL connection count;
- Temporal schedule-to-start latency and activity failures.

## Outbox lease

The execution-event poller claims a bounded batch with a database-backed token
and lease, commits the claim, publishes without holding a database transaction,
then acknowledges successful rows in one update. Failed rows are released for
immediate retry; a crashed publisher is recovered after
`EXECUTION_EVENT_OUTBOX_LEASE_SECONDS` (default 30 seconds). Delivery remains
at-least-once, so consumers must tolerate a duplicate when publication succeeds
but acknowledgement does not.

Lease timestamps come from PostgreSQL rather than an application-node clock.
Keep the lease comfortably above the worst expected batch publication time.

## Database separation decision gate

This rollout intentionally keeps Temporal and application data on the current
shared PostgreSQL topology. Do not separate the databases without an explicit
operator review. Raise that review only when production evidence shows one or
more of:

- sustained connection use above 80% after pool and transaction tuning;
- recurring pool timeouts or `too many clients`;
- Temporal history/visibility I/O correlating with application query latency;
- an operational requirement to scale, back up, or maintain Temporal
  independently.

The review must include 20/60/120-device measurements, current connection/I/O
headroom, migration and rollback steps, and a before/after cost assessment.

## Rollout

1. Record the git SHA, deployment configuration, database limit, background
   load, and raw JSON from the old version.
2. Deploy connection-budget settings first and verify steady-state connection
   count.
3. Deploy outbox hot-path removal, then dispatch transaction changes as
   separate observable steps.
4. Canary real campaigns at 10 and 30 devices before ramping to 60 and 120.
5. Exercise cancellation, partial Temporal-start failure, worker restart,
   sequential promotion, SSE delivery, and DLQ handling.
6. Roll back only the latest phase if its latency or correctness gates regress;
   do not rewrite persisted execution or outbox history.

The synthetic probe validates infrastructure capacity, not phone/app action
latency. A real-device canary is still required before declaring production
campaign latency improved.

## Full campaign pipeline benchmark

`stress_temporal_capacity.py` isolates worker and database-slot capacity.
Use `stress_campaign_pipeline.py` to measure the whole control plane:

```text
POST /api/campaigns/{id}/dispatch
-> fan-out and persistence
-> Temporal workflow start
-> synthetic activity
-> real finalize_campaign activity
-> transactional outbox publication
```

The synthetic activity never controls a phone. The route, PostgreSQL writes,
Temporal scheduling, execution finalization, and event outbox are real. The
script creates a unique task queue so production workers cannot consume its
workflows.

This is a process-level control-plane benchmark: its in-process FastAPI app and
single dedicated Temporal worker do not reproduce the deployed multi-process
worker/poller topology. Pair its result with `stress_temporal_capacity.py
--production-120`, live `/api/health` and `/api/live` checks, SSE verification,
and the real-device canary before calling the result production-proven.

Always use a dedicated disposable database. The script rejects database names
that do not contain `benchmark`, `bench`, `perf`, or `loadtest` unless the
operator explicitly passes `--allow-shared-db`.

Create the database from the deployed application's schema (schema only, never
copy production rows). The harness seeds the checked-in RBAC policy itself:

```bash
createdb postgresql://postgres:postgres@localhost:5433/device_farm_benchmark
pg_dump --schema-only --no-owner --no-privileges \
  postgresql://postgres:postgres@localhost:5433/device_farm \
  | psql postgresql://postgres:postgres@localhost:5433/device_farm_benchmark
```

Capture the first measured version:

```bash
cd device_farm
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/device_farm_benchmark \
.venv/bin/python scripts/stress_campaign_pipeline.py \
  --levels 20,60,120 \
  --warmups 1 \
  --repeats 2 \
  --skip-init-db \
  --capture-baseline \
  --json-output tmp/campaign-pipeline-baseline.json
```

Then compare a candidate under the same host load and configuration:

```bash
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/device_farm_benchmark \
.venv/bin/python scripts/stress_campaign_pipeline.py \
  --levels 20,60,120 \
  --warmups 1 \
  --repeats 2 \
  --skip-init-db \
  --baseline-json tmp/campaign-pipeline-baseline.json \
  --json-output tmp/campaign-pipeline-candidate.json
```

At 120 targets, operational acceptance requires dispatch HTTP p95 at most five
seconds, device-activity schedule-to-start p95 at most two seconds,
finalization schedule-to-start p95 at most one second, finalization runtime and
outbox lag p95 at most two seconds, complete event delivery, zero workflow or
pool failures, and peak PostgreSQL connections below 85%. A speed-improvement
claim additionally requires at least 30% lower HTTP p95 than the supplied
baseline. Without a baseline, the report deliberately marks improvement as
`not_evaluated`.

## Dispatch persistence batching

Parallel campaign dispatch claims devices in deterministic `device_id` order
to keep concurrent transactions on the same lock order. The API response still
uses the caller's resolved target order.

Execution, execution-device, and initial execution-result rows are persisted in
chunks of 25. At the 120-device target this is five bulk statements per table
(15 total), instead of one insert per table per device (360 total). Device
claim, FSM, tenant, and security-audit behavior remains unchanged.

The focused 120-device test stubs the external claim/runtime work so it measures
the persistence seam independently. Treat its latency as a regression signal,
not as a production HTTP latency result. Production acceptance still requires
the real-device canary and the dispatch HTTP p95 target above.
