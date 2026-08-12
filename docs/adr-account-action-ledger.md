# ADR: Account Action Ledger

## Status

Accepted, default-disabled rollout.

## Decision

Account social actions receive a tenant-scoped ledger identity derived from the organization, account, execution, step, action type, and a canonical redacted target. `account_actions` stores the current projection; `account_action_transitions` and `account_action_attempts` are append-only audit records. State advances through conditional rank updates and terminal states never reopen.

One action represents one logical scenario step. Each device retry opens a new numbered attempt before interacting with the device and closes that attempt with its actual outcome. Retryable failures keep the action in `running`; only a verified success or the final failed attempt advances the action to a terminal state. An `already_applied` UI state is recorded as a successful no-op with `action_performed=false`.

Ledger transitions enqueue `account_action.created` and `account_action.transitioned` through the existing `execution_events` transactional outbox. The ledger does not publish directly and does not alter outbox leasing, retention, or delivery. Existing execution step artifact references are copied into ledger records rather than creating a second artifact store.

`ACCOUNT_ACTION_LEDGER_MODE` supports `disabled` (default), `observe`, and `enabled`. Executor metadata is attached only for `content_interaction`, `connection_request`, and `community_membership`; disabled mode executes the unchanged path. Observe mode is intended for identity/telemetry validation without making the ledger authoritative.

Observe records persist their outcome in the action projection. Enabled records persist `action_performed`, `error_code`, and `error_message` from the actual runtime result so account history can distinguish a failed tap from a post-tap verification failure.

Failures before device interaction, including unsupported actions, unavailable hierarchy, ambiguous targets, and missing targets, are also recorded with `action_performed=false`. This keeps account history complete without implying that the device interaction occurred.

The query endpoint is `GET /api/accounts/{account_id}/actions`. It validates account ownership and applies an explicit organization predicate in addition to ORM tenant scoping. Reconciliation advances stale `queued` or `running` records to terminal `stale`. A web-lifecycle background worker runs an immediate pass and repeats on `ACCOUNT_ACTION_RECONCILE_INTERVAL_SECONDS` (default 60 seconds), using `ACCOUNT_ACTION_RECONCILE_STALE_AFTER_SECONDS` (default 3600 seconds) as the age threshold. Both values are parsed as bounded integers.

## Operational Notes

Apply migration `102_account_action_ledger.py` before enabling. Start in `observe`, compare ledger events with execution steps, then use `enabled` after reconciliation scheduling and dashboards are deployed. Payloads are recursively redacted for known credential keys, but callers must still avoid passing arbitrary secrets under misleading key names.

The worker does no database work while the ledger mode is `disabled`. In `observe` and `enabled` modes it uses a PostgreSQL advisory lock so only one API replica reconciles at a time, and commits each pass through an `AsyncSessionLocal` transaction. Prometheus metrics report run outcomes, duration, and the number of actions marked stale. Cancellation propagates after advisory-lock cleanup so application shutdown is not delayed by the scheduling loop.
