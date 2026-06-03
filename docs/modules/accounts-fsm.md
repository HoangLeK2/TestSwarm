# Account state FSM (DF-T-07-005)

Five lifecycle states for social accounts: `active`, `cooldown`, `suspended`, `banned`, `retired`.

## Transition matrix

| From \\ To | active | cooldown | suspended | banned | retired |
|------------|--------|----------|-----------|--------|---------|
| **active** | — | yes | yes | yes | yes |
| **cooldown** | yes (auto TTL or manual) | — | yes | no | yes |
| **suspended** | yes | no | — | yes | yes |
| **banned** | no | no | no | — | yes |
| **retired** | no | no | no | no | — |

`retired` is terminal.

## API

`POST /api/accounts/{id}/state`

```json
{
  "to": "cooldown",
  "reason": "FB rate limit",
  "ttl_seconds": 86400,
  "expected_state_changed_at": "2026-05-26T10:00:00Z"
}
```

Errors: `INVALID_STATE_TRANSITION` (422), `INVALID_TTL` (422), `STATE_CONFLICT` (409).

## Operations

- Cooldown expiry: background loop every 5 min + Temporal activity `process_expired_account_cooldowns`.
- Round-robin / `pick_next_batch`: only `state=active` accounts.
- Audit: `account_events` with `event_type=account.state.changed`.
- Metrics: `account_state_total` (Gauge, current counts), `state_transition_total` (Counter, `reason_code` label).
- Cooldown cron: asyncio loop 5 min + Temporal schedule `df-account-cooldown-tick` (`*/5 * * * *`).
