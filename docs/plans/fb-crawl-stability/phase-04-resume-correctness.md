# Phase 4 — Resume Correctness

> Goal: when a scenario resumes after mid-run failure, pick up cleanly from the last known-good state without re-extracting posts already persisted and without losing the ones the UI has already scrolled past.
> Effort: 1 day
> Priority: P1
> Depends: Phase 1 (save-partial must be in place)

---

## Problem

Today, `Execution.meta["_checkpoint_step"]` records the last successful step index. On resume, executor skips to that step. But:
- Posts persisted in phase 1 (save-partial) may be ahead of `_checkpoint_step` — we could re-crawl posts we already have.
- If the scroll step after extraction was the one that failed, resuming at `step_index=k` with `ctx["posts"]=[]` means we lose visibility into what we've already extracted during loop iteration.
- Loop iterator counter (`_iteration_index` in fb_group_crawl.json) is ephemeral in ctx — not persisted.

---

## Fix

### F4.1 — Persist loop iteration state

Extend `Execution.meta` schema:

```python
{
  "_checkpoint_step": int,
  "_loop_state": {
      "main_scroll_idx": int,         # which MAX_SCROLLS iteration we're on
      "comment_scroll_idx": int,      # within a comment sub-loop
      "posts_persisted_count": int,   # sum of successful saves
      "last_post_content_hash": str | None,  # for O(1) "have we seen this" check
  }
}
```

Extract step writes `_loop_state` after every successful save (incrementally). Scenario resume reads it + restores the ctx loop counters before resuming.

**File**: `tasks/scenario/executor.py` — extend checkpoint writer; `tasks/scenario/steps/extraction.py` — write loop state on persist.

### F4.2 — Checkpoint on post-persist, not only on step-complete

**Problem**: Today checkpoint fires on `ok=True`. If step extracts 20 posts but fails mid-save, we lose the save progress.

**Fix**: `content_store.save_batch_idempotent` (introduced in F1.4) returns a count; emit a `post_persisted` checkpoint event with the current `_loop_state` after **every** saved post, not per step. Throttle to every N=5 posts to avoid DB write amplification.

### F4.3 — Dedup guard on resume

On resume, before running the extract step of the current main loop iteration, query `content` table for posts from this execution and seed `ctx["posts_persisted"]` with their content_hashes. Extraction F1.4 already dedupes by hash, so nothing is re-saved, but the loop counters advance correctly and `stop_if_no_new` behaves correctly.

**Files**: `tasks/scenario_task.py` (startup hook); `db/crud/content.py` (new `list_content_hashes_by_execution`).

### F4.4 — Clean-exit on cancel preserves state

When `cancel_event` is set mid-scenario:
- Current step completes if in-flight.
- `_loop_state` flushed to DB.
- Execution status set to `CANCELLED_RESUMABLE`.
Next run with same `execution_id` picks up where we left off.

Today cancel behavior is partial — verify in `executor.py:103` + `scenario_task.py`. Add integration test.

### F4.5 — TTL on abandoned executions

If an execution in `CANCELLED_RESUMABLE` or `FAILED_RETRYABLE` hasn't been resumed within 24h, mark it terminal. Avoids zombie state. Handled by existing DLQ worker or a new cron in `api/routes/executions.py`.

---

## Steps

1. **Schema extension** for `_loop_state` in Execution.meta (no migration needed — JSONB) (~30min).
2. **Write loop state on persist** in extraction step (~1h).
3. **F4.2 post-level checkpoint** (~1.5h).
4. **F4.3 resume dedup seed** (~1h).
5. **F4.4 cancel-preserves-state** review + test (~1h).
6. **F4.5 TTL cron or job** (~1h).
7. **Integration test**: run scenario, kill at step K, resume, verify no duplicates + counters advance (~1.5h).

---

## Acceptance

- [ ] Resume after crash yields **zero duplicate posts** in `content` table (verified via unique `content_hash` constraint).
- [ ] Resume continues loop iteration from where it left off (not from scratch).
- [ ] Cancel mid-run sets `CANCELLED_RESUMABLE`, `_loop_state` is valid on next start.
- [ ] Zombie `CANCELLED_RESUMABLE` rows older than 24h auto-expire.
- [ ] Integration test: kill scenario after 30 posts extracted, resume, confirm final DB has ≥ 30 posts from run 1 + whatever new posts run 2 extracts (no overlap).

---

## Risks

| Risk | Mitigation |
|------|------------|
| Dedup seed query slow on long executions | Index `content(execution_id)` + cap seed to last N=500 hashes |
| Post-level checkpoints spam DB | Throttle to every 5 posts or 2 seconds, whichever comes first |
| Resume from a 1-week-old state is pointless | Phase 4 TTL (F4.5) expires after 24h by default |
