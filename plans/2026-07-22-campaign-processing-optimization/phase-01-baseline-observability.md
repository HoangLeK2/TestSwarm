# Phase 1: Baseline and Observability

## Objective

Measure the complete campaign path before changing its behavior. Produce a repeatable baseline for 20, 60, and 120 campaign devices using real PostgreSQL and Temporal, while replacing physical phone work with a controlled probe activity.

## Current Gaps

- `campaign_dispatch_duration_seconds` wraps `dispatch_campaign()` but excludes Temporal startup and response hydration.
- `/metrics` and `/api/metrics` currently return 404 even though metrics are defined.
- Existing capacity tests use mocked database/Temporal calls or test worker slots in isolation; neither covers the full pipeline.
- Campaign identifiers are not safe Prometheus labels because they are high-cardinality.

## Tasks

- [ ] Run GitNexus impact analysis for the route, metrics registration, dispatcher, runtime starter, event publisher, and activity wrapper before edits.
- [ ] Expose a protected/internal metrics endpoint. Do not expose tenant or campaign data publicly.
- [ ] Extend dispatch measurement to the full HTTP operation and record phase histograms for validation, snapshot, claim, commit, Temporal start, metadata persistence, and response hydration.
- [ ] Add pool wait/timeout counters, Temporal schedule-to-start, finalization lag, outbox batch duration/count, backlog count, and oldest-unpublished-event age.
- [ ] Put `campaign_id`, `execution_id`, and `org_id` in structured logs/traces rather than unbounded Prometheus labels.
- [ ] Add `device_farm/scripts/stress_campaign_pipeline.py` or extend the existing capacity harness to call the real dispatch path against real PostgreSQL and Temporal with deterministic probe activities.
- [ ] Store baseline output as JSON: git SHA, configuration, worker count, pool sizes, PostgreSQL limits/session counts, latency percentiles, failures, event volume, and run timestamps.
- [ ] Add focused tests proving metric boundaries and endpoint access control.

## Expected Files

- `device_farm/web/metrics.py`
- `device_farm/web/server.py`
- `device_farm/api/routes/campaigns.py`
- `device_farm/services/campaign/dispatcher.py`
- `device_farm/services/campaign/execution_runtime.py`
- `device_farm/services/execution/event_publisher.py`
- `device_farm/temporal/activities.py`
- `device_farm/scripts/stress_campaign_pipeline.py`
- `device_farm/tests/test_campaign_performance_metrics.py`
- `docs/runbooks/campaign-capacity.md`

## Verification

- [ ] Run 20/60/120 twice each after one warm-up run.
- [ ] Confirm HTTP total approximately equals the measured internal phases plus small framework overhead.
- [ ] Confirm metrics endpoint is inaccessible outside its intended boundary.
- [ ] Confirm the probe does not require physical phones and cannot mutate real device/account data.
- [ ] Review raw baseline before approving phases 2-5; replace provisional targets in the master plan if the business SLA is stricter.

## Exit Gate

A second engineer can reproduce the baseline and identify whether time is spent in dispatch, database wait/queries, Temporal queueing, device activity, outbox publication, or finalization. No optimization proceeds without this evidence.
