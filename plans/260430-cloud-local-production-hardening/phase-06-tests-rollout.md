# Phase 06 - Tests And Rollout

## Overview

Add regression coverage and staged rollout controls so the hardening can land without breaking existing local development or manual control.

## Priority

P1. This plan touches cross-repo contracts; tests must catch drift.

## Files

Modify or create tests in:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/tests/`
- `/Users/hoanglcpila.vn/deviceFarmer/agent-boot/relay/tests/`

Modify docs:

- `/Users/hoanglcpila.vn/deviceFarmer/device_farm/docs/architecture.md`
- `/Users/hoanglcpila.vn/deviceFarmer/docs/device-farm-canary-rollout.md`
- `/Users/hoanglcpila.vn/deviceFarmer/docs/cloud-local-production-runbook.md`

## Test Matrix

Device farm unit tests:

- cloud mode does not spawn local agent.
- relay agent token auth accepts valid token and rejects disabled node.
- device lease unique active serial.
- stale lease expiry.
- scheduler excludes leased/quarantined/offline/draining devices.
- relay command builder includes `lease_id`.
- raw shell disabled by default.

Agent boot unit tests:

- `lease_start` activates serial lease.
- wrong lease is rejected.
- expired lease is rejected.
- missing lease is allowed in soft mode and rejected in hard mode.
- cleanup command stops/evicts expected components.
- protocol version payload is sent in register.

Integration tests:

- fake agent connects to gRPC control stream.
- cloud registers agent.
- cloud acquires lease.
- command with lease succeeds.
- command with stale lease fails.
- cleanup result releases lease.

## Rollout Flags

Start with safe defaults:

```env
DEVICE_FARM_DEPLOY_MODE=cloud
ENABLE_LOCAL_AGENT_BOOT=0
RELAY_PER_AGENT_TOKEN_REQUIRED=0
RELAY_SEND_LEASE_ID=1
RELAY_REQUIRE_LEASE=0
AGENT_REQUIRE_LEASE=0
RELAY_ALLOW_RAW_SHELL=0
```

Canary sequence:

1. Deploy phase 01 to staging and production.
2. Register one canary agent with per-agent token.
3. Enable lease creation but not enforcement.
4. Enable agent lease enforcement on canary node.
5. Enable cloud lease requirement for canary user/campaign.
6. Enable globally after 24h stable run.

Rollback:

- Disable `RELAY_REQUIRE_LEASE`.
- Disable `AGENT_REQUIRE_LEASE`.
- Keep lease table writes; do not drop schema.
- Re-enable shared key fallback temporarily if per-agent token rollout blocks nodes.

## Required Commands

Device farm:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_cloud_mode_boundary.py tests/test_relay_agent_identity.py tests/test_device_leases.py tests/test_relay_lease_contract.py tests/test_cleanup_quarantine.py
```

Agent boot:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/agent-boot
uv run pytest relay/tests/test_relay_identity_config.py relay/tests/test_lease_guards.py
```

Existing regression subset:

```bash
cd /Users/hoanglcpila.vn/deviceFarmer/device_farm
uv run pytest tests/test_relay_agents_routes.py tests/test_grpc_relay_n2n.py tests/test_a11y_relay_api.py tests/test_hardening_regressions.py
```

## Success Criteria

- New tests pass in both repos.
- Existing relay/a11y/migration hardening tests pass.
- Rollout can be disabled by env without schema rollback.
- Runbook documents cloud/local production operation.

## Risks

- Some integration tests may need fake gRPC stubs.
- Mitigation: keep first pass unit-level and add one fake-agent integration test after contract stabilizes.
