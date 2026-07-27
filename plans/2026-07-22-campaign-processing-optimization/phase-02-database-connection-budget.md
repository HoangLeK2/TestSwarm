# Phase 2: Database Connection Budget

## Objective

Make configured connection demand safe for the database before adding concurrency elsewhere. Treat the web pool, every activity event-loop pool, Temporal persistence, monitoring, migrations, and recovery access as one budget.

## Budget Model

Use an explicit deployment calculation:

`web_max + (worker_processes x activity_pool_max_per_process) + temporal_max + support_reserve <= database_safe_limit`

`pool_max` means `pool_size + max_overflow`. The safe limit must come from the target environment, not from the local 100-connection snapshot.

## Tasks

- [ ] Run GitNexus impact analysis for database configuration/session creation symbols before edits.
- [ ] Inventory every process that connects to the shared PostgreSQL instance and document its configured and observed maximum.
- [ ] Verify Temporal PostgreSQL pool configuration with primary Temporal documentation before changing it.
- [ ] Add startup/config validation that compares theoretical application demand with an explicit deployment connection budget; fail production startup or emit a prominent warning according to rollout policy.
- [ ] Preserve a recovery reserve of at least 15 connections, or the production DBA-defined value.
- [ ] Tune web and activity pool sizes from measured transaction concurrency rather than activity slot count.
- [ ] Decide and document the production topology: preferably isolate Temporal persistence from application data or put a transaction pooler in front of compatible application workloads; otherwise cap both sides within the shared budget.
- [ ] Update compose/example configuration and the capacity runbook with the formula and recommended per-environment values.
- [ ] Extend the capacity harness with a database-hold probe that records pool wait, timeout, and server connection peaks.

## Expected Files

- `device_farm/db/database.py`
- `device_farm/core/config.py`
- `docker-compose.yml`
- `.env.example`
- `device_farm/scripts/stress_temporal_capacity.py`
- `device_farm/tests/test_database_pool_config.py`
- `docs/runbooks/campaign-capacity.md`

## Verification

- [ ] Unit-test valid, boundary, and over-budget configurations.
- [ ] Run 20/60/120 database-hold probes with real PostgreSQL and Temporal.
- [ ] Assert zero pool timeouts and zero `too many clients` errors.
- [ ] Assert peak usage is below 85% and the recovery reserve remains available.
- [ ] Confirm connection count returns to steady state after the run and per-event-loop pools are disposed on worker shutdown.

## Exit Gate

The 120-device probe passes with measured headroom. Do not increase activity concurrency until this gate is green.

## Rollback

Pool sizes and budget enforcement remain configuration-driven. Roll back one deployment configuration at a time; never respond to pool pressure by only raising `max_connections` without checking database memory and Temporal demand.
