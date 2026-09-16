# ADR: Reasoning about execution timelines

## Status

Accepted. Enforced by the guards listed under *Enforcement*.

## Context

Building the nested-step timeline for the run-history dialog surfaced four
defect classes. All four passed type-checking, all four produced a screen that
looked plausible, and none of them raised an error. Three of them had already
shipped to the Monitor screen unnoticed.

The common shape: a surface read a store that never held the data, or trusted a
field that meant something other than its name, and rendered the result with
full confidence. The screen is the only place the lie becomes visible, and only
to someone who already knows what the run did.

---

## Class 1 — Nested steps live in `execution_events`, nowhere else

`execution_steps` holds **depth-0 rows only, by design**:

| Site | What it enforces |
|---|---|
| `db/models/execution_step.py` | unique `(execution_id, step_index)` |
| `services/execution/activity_events.py` | `_mark_step_running` returns early on `depth != 0` |
| `services/execution/step_store.py` | `schedule_persist_step*` return early on `sc.depth > 0` |

Nested steps reuse *local* indices, so writing them would overwrite the parent
row. Temporal's loop body keeps only `{"iteration": i, "success": …}`
(`temporal/workflows.py`) — deliberately, to stay under the 2 MB history budget.

**Rules**

- A surface that must show what happened *inside* a loop or branch reads
  `execution_events`. Not `execution_steps`, not `trace.sub_results`, not
  `step_results` — those are thin on purpose and will stay thin.
- Do not "fix" this by widening the unique constraint or by stuffing
  `child_result.step_results` into the workflow result. The history budget is
  the reason; reason code `loop_history_limit` exists for when it is hit.
- `/executions/{id}/task-log` caps events at 500 with no further paging. One
  20-iteration loop exceeds that. Page `/executions/{id}/events` with
  `since=<last event_id>` until `has_more === false`, with a hard page ceiling.
- Routine events (`step.completed`) are purged at 30 days; forensic ones
  (`step.failed`) at 365 (`services/execution/outbox_poller.py`). Any
  event-derived view needs a documented fallback for older runs.

---

## Class 2 — Only a row's own events may set its identity

`temporal.activity.*` events are emitted **against the first step of a batch**:
they carry that step's `step_id`, `step_index` and `depth`, but their
`trace.step_path` is only the iteration prefix — no step segment. And the
`scheduled` of iteration N+1 shares a timestamp with the `completed` of
iteration N. Observed in execution `057db296`:

```
16:36:44.118  temporal.activity.scheduled  step_id=feed_keyword_nam_hoc_moi  path=0/feed_keyword_loop#1
16:36:44.118  temporal.activity.completed  step_id=feed_keyword_nam_hoc_moi  path=0/feed_keyword_loop#0
```

`foldEventsToStepLog` let the activity path win (`traceSummary.stepPath ??
existing`). Every round's first step was re-stamped into the following round —
so round 1 appeared to start at its second step and to take 0.7 s instead of
5.4 s. The Monitor, which matches steps by `step_path`, was mis-matching the
same rows.

**Rules**

- A secondary event may *add* to an existing row (chips, incidents, attempts).
  It may never set the row's identity or position: `step_path`, `loop_id`,
  `loop_iter`, `branch`, `depth`. Only the row's own `step.started` /
  `step.completed` / `step.failed` may do that.
- Never let delivery or timestamp order decide who wins a field. Timestamps tie
  at millisecond granularity, and workflow telemetry ships in batches.
- Same principle as the Facebook flows (see `adr-facebook-ui-reasoning.md`):
  **identity, not position**. A shared `depth:index:step_id` key is not proof
  that two events describe the same run of a step.

---

## Class 3 — A field named after a measurement may not be one

| Field | What it actually is |
|---|---|
| `duration_ms` on a gesture step | the **configured** gesture duration — `int(step.get("duration_ms", 300))` in `tasks/scenario/steps/interaction.py`, kept by `sr.setdefault(...)` in `temporal/activities.py` |
| `duration_ms` on `loop` / `run_scenario` / `if_*` | absent — container steps run in workflow code and emit none |
| `activity_duration_ms` | the whole batch, not the step |

**Rules**

- Before reporting a number as wrong, check it against the wall clock: the
  `occurred_at` delta between that step's `step.started` and `step.completed`.
  In `057db296`, per-step values summed to 5.27 s against 5.40 s of wall clock —
  the numbers were right; a row was missing.
- Distinguish **wrong value** from **missing row** from **absent field**. They
  look identical on screen and have three different fixes.

---

## Class 4 — Verify against the database, not against intuition

Postgres is published on host port **5433**:

```bash
docker compose exec -T postgres psql -U postgres -d device_farm -c "
SELECT event_type, occurred_at, payload->'trace'->>'step_path' AS path,
       payload->>'duration_ms' AS dur, payload->>'depth' AS d
FROM execution_events WHERE execution_id='<id>' ORDER BY id LIMIT 30;"
```

`/executions/{id}/events` orders by row `id` ascending — replay in that order,
not by `occurred_at`, when reproducing a fold.

**Rule:** "it looks wrong" is a hypothesis. Pull the events for the actual run
and compare before changing code or telling the user what happened.

---

## Repo mechanics that are easy to assume wrong

- **There is no vitest.** Front-end tests are `node:test` + `node:assert/strict`,
  run with `node --loader ./scripts/ts-extension-loader.mjs
  --experimental-strip-types --test <file>`. They sit next to the source as
  `*.test.ts` and import the TS file **by extension** with an
  `@ts-expect-error` on the import.
- **i18n keys go into both `messages/en.json` and `messages/vi.json`**, then
  `node scripts/check-i18n-keys.mjs`. A key present in the files but rendering
  as its raw path (`campaignsFeature.list.someKey`) means the dev server is
  holding stale messages — restart it.
- **No hardcoded display strings in `lib/`.** A helper that cannot derive a
  label returns `null` (or a key plus params) and lets the component translate.
  A literal `` `Bước ${n}` `` in a lib file is how "6. Bước 6" reached the UI.
- Reuse the display map that already exists rather than re-declaring it
  (`actionOutcomeMessageKey` in `lib/workflow-step-list-model.ts`).

---

## Enforcement

| Guard | Protects |
|---|---|
| `execution-event-utils.test.ts` — *activity events do not re-path a finished loop step* | Class 2, with the real `057db296` event sequence |
| `step-log-tree.test.ts` | iteration grouping and numeric ordering (`#10` after `#9`) |
| `scripts/check-i18n-keys.mjs` | literal `t('key')` calls resolving in both locales |

If one of these blocks a change, the fix is to narrow the change — not to widen
the guard.

## Consequences

- Event-derived views cost one paged fetch per execution and degrade to
  top-level steps once routine events age out. Accepted.
- `foldEventsToStepLog` is shared by the Monitor and the history dialog. Run
  `impact` on it before editing (it reports CRITICAL on fan-out; the three
  direct callers are what matter) and re-check both screens after.
