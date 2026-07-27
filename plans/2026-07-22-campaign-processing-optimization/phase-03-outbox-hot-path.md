# Phase 3: Outbox Hot-path Removal

## Objective

Keep activity event writes transactional while removing global event publication work from every step's critical path. Strengthen the existing background outbox poller rather than building a second publisher.

## Design

- Activity path: insert event and commit its own transaction; do not scan/publish the global backlog inline.
- Poller path: claim a bounded batch atomically, publish it, update attempt/published state, and report true backlog age.
- Delivery contract: at-least-once unless the in-process SSE bus gains durable acknowledgement. Consumers must tolerate duplicate delivery.

## Tasks

- [ ] Run GitNexus impact analysis for `_emit_step_events_for_activity`, `process_outbox_batch`, `fetch_unpublished_events`, and poller lifecycle symbols.
- [ ] Remove or rollout-gate inline `process_outbox_batch()` from the activity event path.
- [ ] Make concurrent polling safe using row-level atomic claiming, such as `FOR UPDATE SKIP LOCKED`, with deterministic ordering.
- [ ] Define failure semantics for publish-before-mark and worker crash; never mark an event published before the bus accepts it.
- [ ] Calculate lag from the oldest unpublished row rather than resetting the gauge when any batch succeeds.
- [ ] Keep the current one-second polling interval initially. Add an in-process wake signal only if measured SSE latency misses the two-second target.
- [ ] Bound batch size and transaction duration from the phase-1 event-volume baseline.
- [ ] Add cleanup/retention checks so the events table and unpublished index remain efficient.
- [ ] Add a temporary, scoped rollout flag for inline publication only if canary rollback needs it; remove the flag after stabilization.

## Expected Files

- `device_farm/temporal/activities.py`
- `device_farm/services/execution/event_publisher.py`
- `device_farm/db/crud/execution_events.py`
- `device_farm/services/execution/outbox_poller.py`
- `device_farm/services/execution/activity_events.py`
- `device_farm/tests/test_epic04_execution_event_stream.py`
- `device_farm/tests/test_streaming_db_pool.py`
- `device_farm/tests/test_temporal_batch_cancel.py`

## Verification

- [ ] Two concurrent pollers never claim the same event row in one attempt.
- [ ] A publisher failure increments attempts, keeps the row eligible, and does not lose it.
- [ ] Started/finished ordering remains deterministic for each execution.
- [ ] Cancellation and retry events remain visible to SSE consumers.
- [ ] At 120 devices, oldest-unpublished age p95 is below two seconds and pool wait is lower than baseline.
- [ ] Compare event count, duplicate delivery count, activity duration, query count, and database connection peak against phase 1.

## Exit Gate

The event stream catches up within target under 120-device load with no lost events, no duplicate row claims, and a measurable reduction in activity hot-path database time.
