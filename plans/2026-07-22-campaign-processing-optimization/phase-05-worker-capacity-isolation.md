# Phase 5: Worker Capacity Isolation

## Objective

Prevent long device activities from starving finalization and control work. This phase is conditional: implement it only if the phase-4 120-device run violates finalization/control schedule-to-start targets.

## Decision Gate

- Skip this phase if finalization/control schedule-to-start p95 is below one second and terminal-status lag p95 is below two seconds.
- Proceed if all 120 device slots saturate the shared worker and finalization/control activities queue behind device work.

## Preferred Design

Add a small, reserved Temporal control task queue/worker for finalization, cooldown, scheduling, and other non-device control activities. Keep hardware-bound device activities on their correctly routed device/machine queues; do not horizontally distribute them to workers that lack the device or relay context.

## Tasks

- [ ] Verify task-queue routing and worker concurrency APIs against primary Temporal Python documentation.
- [ ] Run GitNexus impact analysis for worker startup, workflow activity invocations, and task-queue configuration symbols.
- [ ] Classify registered activities as device-bound, control, or mixed; document ownership and routing requirements.
- [ ] Introduce explicit control queue and concurrency configuration with a conservative default derived from load data.
- [ ] Route finalization/control activity calls to the control queue while preserving retry and timeout policies.
- [ ] Start the control worker in both in-process and standalone `worker_main.py` deployment modes.
- [ ] Keep total database pool demand inside phase-2 limits; a new worker must not silently allocate another unsafe pool.
- [ ] Add queue-specific schedule-to-start metrics and health reporting.

## Expected Files

- `device_farm/temporal/worker.py`
- `device_farm/temporal/worker_main.py`
- `device_farm/temporal/workflows.py`
- `device_farm/core/config.py`
- `device_farm/config.yaml`
- `docker-compose.yml`
- `device_farm/tests/test_temporal_worker_config.py`
- `device_farm/tests/test_campaign_finalize_queue.py`

## Verification

- [ ] Saturate 120 device activities and enqueue finalization/control work concurrently.
- [ ] Confirm control schedule-to-start p95 below one second and terminal lag p95 below two seconds.
- [ ] Confirm device activities still execute only where their relay/device context exists.
- [ ] Confirm worker restart, cancellation, retry, and graceful shutdown behavior on both queues.
- [ ] Confirm PostgreSQL connection peaks remain inside the phase-2 budget.

## Rollback

Route activity calls back to the original queue and stop the control worker. Queue names and rollout configuration must allow existing in-flight workflows to drain safely before removal.
