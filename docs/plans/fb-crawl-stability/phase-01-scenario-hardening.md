# Phase 1 — Scenario Engine Hardening

> Goal: guarantee extraction sees fresh, stable UI; recover gracefully when a step flakes; never silently lose partial progress.
> Effort: 2-3 days
> Priority: P0
> Depends: Phase 0 (diagnostics + bundle)

---

## Fixes

### F1.1 — Force fresh hierarchy on extraction entry

**Problem (S4)**: `steps/extraction.py:63` calls `device.hierarchy_xml(force_refresh=False)` by default on the first pass → may return cached hierarchy from before the prior scroll.

**Fix**:
```python
# tasks/scenario/steps/extraction.py
xml = device.hierarchy_xml(force_refresh=True)
```
Apply also at the retry-loop XML re-fetches (lines 122-146). Cost: ~200ms per dump.

### F1.2 — Wait-for-hierarchy-stable after scroll

**Problem (S1, S2)**: Swipe finishes, `pause_seconds` elapses, next step runs — but FB lazy-load may still be mutating the tree when UIAutomator dumps.

**Fix**: After every scroll, run `wait_stable(timeout=3s, stable_duration_ms=500)` (reuse `scenario/utils.py:301-327`). Two approaches:

**Option A (scenario-level, recommended)**: insert `{"type": "wait_stable", "timeout_seconds": 3, "stable_duration_ms": 500}` after every `scroll` step in `scenarios/fb_group_crawl.json`. Keeps engine simple, applies per-scenario as needed.

**Option B (engine-level)**: in `steps/navigation.py:127-136`, after final swipe + pause, automatically call `wait_stable` with configurable `post_scroll_stable_ms`. Adds implicit behavior.

Recommend **A** for this phase; revisit B if we add same pattern to IG/TikTok later.

### F1.3 — Reject extract on stale frame

**Problem (S1)**: `capture_post_step` logs warning and continues when frame timestamp didn't advance.

**Fix**: in `capture.py:56-70`, change warning-and-continue to **raise `StaleFrameError`** when stale-after-settle, with knob `allow_stale_frame=False` for extraction steps specifically. Extraction step wraps in try/except and returns `ok=False, retryable=True` (feeds into F1.5 retry).

### F1.4 — Save partial posts before any abort

**Problem (S8)**: `extraction.py:87-90` persists only on `ok=True`.

**Fix**:
- Introduce `ctx["posts_persisted"]` set — track which `content_hash` values already saved.
- After **every** parse call (even if result is `[]`), flush new-posts-not-yet-persisted to `content_store.save()`.
- On exception inside extraction step, `finally:` block triggers the same flush.
- Existing dedupe via `content_hash` prevents double-writes.

Implement in `services/content_store.py` (add `save_batch_idempotent`) and call from `steps/extraction.py`.

### F1.5 — Per-step retry with backoff for extraction + comment-entry

**Problem (S6)**: Single step failure aborts scenario.

**Fix**: Add per-step `retry` config on extraction and comment-tap steps only (not on every step — some should fail fast):

```json
{
  "type": "extract",
  "retry": {"attempts": 3, "backoff_ms": 1000, "jitter_ms": 500, "on": ["stale_frame", "empty_parse"]},
  ...
}
```

Engine change in `executor.py`:
- Check `step.retry` block; if step fails with `retryable=True` and attempts remain, sleep `backoff * 2^(n-1) + jitter`, re-run step.
- After max attempts: `ignore_error` honored (skip) OR abort with failure bundle captured.
- Emit `step_retry` structured log event.

**Tenacity reuse, do not double-wrap**: `agent-boot/relay/u2_executor.py` already uses tenacity for `_run_with_retry`. Use the same import + style here. Do not add a second retry layer around u2 calls that are already retried — guard by checking step type (extract + tap wrap; wait + sleep do not).

### F1.6 — Tap-retry with bounds re-resolution

**Problem (S7)**: Post bounds stale between find and tap.

**Fix**: In `scenario/utils.py` `_execute_tap`, on tap failure:
1. Re-dump hierarchy (force refresh).
2. Re-resolve selector.
3. Retry tap up to 2 times before fallback ratio.
Emit `tap_retry` log event.

### F1.7 — Stop-if-no-new counts only `reason_code == "ok"` results

**Problem (S5)**: `stop_if_no_new_threshold` ticks up even when parser silently returned `[]` due to anchor miss. Loop exits early on real feeds.

**Fix**: In `extraction.py:178-188`, only increment `_no_new_posts_streak` when `diagnostic.reason_code == "ok"` AND `posts_added == 0`. On diagnostic errors (`anchor_not_found`, `no_candidates`, etc), do **not** increment — treat as retry-worthy.

---

### F1.8 — Session-death detection (new; was missing)

**Problem (from red-team)**: If FB logs out the account mid-scroll, today's scenario treats the login screen as "parse returned empty" → retries 3× on a login screen → bundle captured but no recovery. Account may be permanently banned; continuing wastes time and saves garbage posts.

**Fix**: Parser returns `reason_code="login_screen"` when it detects login-screen heuristic (keywords: "Đăng nhập", "Log in", "Enter password", "Quên mật khẩu", "Forgot password"; OR resource-id containing `m_login`, `c_user` missing). Similarly `reason_code="rate_limited"` for "temporarily blocked", "tạm thời bị chặn".

Scenario engine reaction in `scenario_task.py`:
- `login_screen` → immediately set `execution.status = FAILED_ACCOUNT_DEAD`, emit event, capture bundle, mark account for cooldown via `services/account_manager.py.mark_account_suspended(account_id)`, abort scenario. No retry.
- `rate_limited` → `FAILED_RATE_LIMITED`, cooldown account for env-configured window (default 4h), abort scenario.

Detection lives in `fb_extract.py` (cheap text scan on root node before deeper parsing). Reaction lives in the extraction step handler — one-line check on `diagnostic.reason_code` before normal flow.

### F1.9 — Multi-account dedup key (new; was missing)

**Problem (from red-team)**: `ctx["posts_persisted"]` is per-scenario. If account A and account B crawl the same group, content_hash collisions mask real posts from B.

**Fix**: Dedup key is `(content_hash, execution_id, account_id)`. `content_store.save_batch_idempotent` takes `account_id` from ctx (present when `account_manager` started the scenario). DB unique constraint updated to composite. Phase 4 resume dedup seed filters by same key.

Migration: `ALTER TABLE content DROP CONSTRAINT content_hash_unique, ADD CONSTRAINT content_hash_per_account UNIQUE (content_hash, account_id)` (nullable `account_id` allowed for legacy rows).

---

## Steps

1. **F1.1 quick win** — flip `force_refresh=True`. Validate no existing test breaks (~30min).
2. **F1.3 StaleFrameError** + capture.py change (~1.5h).
3. **F1.4 save-partial** batch idempotent + wire into extraction step finally block (~2h).
4. **F1.5 retry engine** — tenacity wrap in executor; schema update for `step.retry`; unit test retry + backoff (~4h).
5. **F1.6 tap retry** — helper in utils, emit event (~1.5h).
6. **F1.7 stop_if_no_new gate** on diagnostic (~30min).
7. **F1.2 wait_stable** inject into `fb_group_crawl.json` after every scroll (~30min).
8. **F1.8 session-death detection** — parser text-scan + scenario-engine reaction + account cooldown hook (~3h).
9. **F1.9 multi-account dedup** — schema migration + CRUD update + save_batch_idempotent signature (~2h).
10. **Integration test** — run scenario 10× against a known-stable group, measure diff-of-runs recall (~2h).

---

## Acceptance

- [ ] All extraction steps see `force_refresh=True` XML.
- [ ] Stale frame during extraction raises `StaleFrameError`, caught by retry, attempted up to 3×.
- [ ] Partial posts always persisted — killed mid-scenario, inspecting DB still shows posts extracted so far.
- [ ] Tap on "Bình luận" retries with fresh bounds on miss.
- [ ] `fb_group_crawl.json` has `wait_stable` after every scroll (~4 locations).
- [ ] Scenario aborts ONLY after retry budget exhausted; single-flake does not kill run.
- [ ] `stop_if_no_new` no longer triggers on diagnostic errors.
- [ ] Login screen XML → execution `FAILED_ACCOUNT_DEAD`, account cooldown set, **no retry**.
- [ ] Rate-limit screen → `FAILED_RATE_LIMITED`, account cooldown 4h.
- [ ] Two accounts crawling the same group → each persists full post set (multi-account dedup).
- [ ] 10 back-to-back runs on test group: diff-of-runs recall ≥ 90% (parser fixes in phase 2 lift to ≥ 95%).

---

## Risks

| Risk | Mitigation |
|------|------------|
| `force_refresh=True` slows every step by 200-500ms | Accept; scope to extraction only, not every step |
| `wait_stable` may time out on very dynamic feeds (video autoplay) | Timeout at 3s, fall through; tune per-scenario if needed |
| Retry + backoff lengthens worst-case scenario runtime | Cap total retry budget per execution; measure before/after p95 runtime |
| Save-partial may persist posts that later phase 2 fixes would have made complete | Accept — partial is better than lost; re-crawl has dedupe |
