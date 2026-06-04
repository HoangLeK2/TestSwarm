# Phase 5 - Scenario Regression Benchmarks

Status: Planned
Priority: P1
Effort: 2h

## Objective

Prove the optimization improves scenario latency without breaking relay behavior.

## Scope

- Add a repeatable local benchmark for a small scenario pattern:
  - dump XML,
  - tap,
  - optional type/key,
  - dump XML again.
- Capture before/after metrics:
  - command accepted latency,
  - queue wait,
  - execution time,
  - XML dump count,
  - total scenario step time.

## Files

- `/Users/hoangle/farm/device-farm/agent-boot/relay/tests`
- `/Users/hoangle/farm/device-farm/device_farm/tests`
- `/Users/hoangle/farm/device-farm/device_farm/tools`

## Benchmark Cases

1. Idle device, one scenario.
2. Scenario while bootstrap is queued.
3. XML refresh storm.
4. u2 timeout path.

## Validation Commands

```bash
cd /Users/hoangle/farm/device-farm/agent-boot
uv run pytest relay/tests/test_grpc_client_tls.py relay/tests/test_fair_send_queue.py relay/tests/test_u2_session_pool.py

cd /Users/hoangle/farm/device-farm/device_farm
uv run pytest tests/test_agent_control_servicer.py tests/test_a11y_relay_api.py tests/test_relay_agents_routes.py
```

## Success Criteria

- Benchmarks show lower p95 interactive queue wait.
- XML dump count drops under refresh storms.
- Existing relay unit tests pass.
- Any remaining bottleneck is visible in timing logs.
