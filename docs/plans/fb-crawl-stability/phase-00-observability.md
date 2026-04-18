# Phase 0 — Observability (Minimal)

> Goal: every flaky event leaves enough on-disk evidence to root-cause offline. File-only. No DB, no API, no CLI — all cut from the original scope.
> Effort: ~4 hours
> Priority: P0
> Depends: Phase -1 (evidence pull) cleared with "proceed" verdict

---

## What Got Cut (and why)

Original Phase 0 called for `failure_bundles` DB table, operator API, download endpoint, replay CLI. Red-team called these 30-40% of plan effort for 90% redundant with existing `captures/` dir + existing parse tests. Cut all of it. Stick to:

1. `parse_diagnostic` tuple return from parser.
2. File-only bundles under `captures/_failures/<execution_id>/<step_idx>_<ts>/`.
3. `structlog` event on every extract step.

Re-add DB + API + CLI only if ops tells us file-browsing bundles has real friction after 2 weeks in prod.

---

## Deliverables

### D0.1 — `parse_diagnostic` tuple return

Modify `tasks/fb_extract.py`:

```python
def parse_fb_posts_from_xml(xml: str, source_index: int = 0) -> Tuple[List[Dict], Dict]:
    """Returns (posts, diagnostic).

    Diagnostic schema:
      reason_code: "ok" | "xml_parse_error" | "no_feed_container" |
                   "no_candidates" | "all_filtered_junk" | "anchor_not_found" |
                   "no_text_nodes" | "empty_cluster" | "login_screen" |
                   "rate_limited" | "parser_exception"
      posts_returned: int
      feed_container_score: float | None
      screen_size: (w, h)
      candidate_clusters: int
      filtered_junk_count: int
      filtered_noise_count: int
      truncated_post_count: int
      locale_tokens_hit: list[str]
      elapsed_ms: float
    """
```

Same change for `parse_fb_comments_from_xml`. Plus two new `reason_code` values — `login_screen` and `rate_limited` — detected by heuristic scan for known login/rate-limit phrases (phase 1 F1.8 consumes these).

**Migration**: grep every caller, update in same PR. `Grep "parse_fb_posts_from_xml(" --include="*.py"` count = audit first, list all sites in PR description. Keep a legacy `_legacy_parse_fb_posts_from_xml(xml)` one-line wrapper that returns `posts` only, for any tests we can't migrate cleanly. Drop the wrapper in Phase 3.

### D0.2 — File-only failure bundles

Implement `tasks/scenario/failure_bundle.py`:

```python
def capture_failure_bundle(
    device,
    ctx: dict,
    execution_id: str,
    step_idx: int,
    reason: str,
    diagnostic: dict | None = None,
    exc: BaseException | None = None,
) -> str | None:
    """Write bundle to captures/_failures/<execution_id>/<step_idx>_<ts>/.

    Returns bundle path, or None if FB_CAPTURE_FAILURES disabled.
    Silent no-op on write error — never break scenario.
    """
```

Bundle contents:
- `hierarchy.xml.gz`
- `screen.jpg` (if current frame available)
- `step_context.json` (ctx variables + accumulator counts, **not** full post list — avoid GB bundles)
- `parse_diagnostic.json`
- `traceback.txt` if exception

Triggers (call from `steps/extraction.py` + `executor.py` exception handler):
- `reason_code` not in `{"ok"}` AND not in ignore set (`{"no_candidates"}` when scrolling past end of feed is expected)
- Exception raised by any step
- F1.8 session-death detected

**Cap**: max 50 bundles per execution (env `FB_FAILURE_CAP=50`). Drop bundles past cap with counter log. Avoids disk flood on rate-limit page loop.

### D0.3 — Structured log event

Extend existing `structlog` scenario_trace logger. One event per extraction step:

```python
trace_log.info(
    "extraction_result",
    execution_id=..., step_idx=..., source_index=...,
    reason_code=diagnostic["reason_code"],
    posts_added=len(new_posts),
    posts_dropped_truncated=diagnostic["truncated_post_count"],
    parse_ms=diagnostic["elapsed_ms"],
    frame_age_ms=...,       # from Phase -1 instrumentation, now permanent
    u2_heartbeat_age_ms=...,
    bundle_path=bundle_path or None,
)
```

### D0.4 — Doc

Short `docs/RUNBOOK_fb_crawl_failures.md`: how to locate a bundle on disk, how to replay parser via existing `test_captures_parse_persist_accuracy` fixture pattern.

---

## Steps

1. **Parser signature change + caller migration** (~2h) — one-PR breaking change, guarded by legacy wrapper.
2. **`capture_failure_bundle` helper + wiring** into extraction step + executor finally (~1h).
3. **Structured log event** (~30min).
4. **Runbook doc** (~20min).
5. **Smoke test**: run scenario with `FB_CAPTURE_FAILURES=1` on a known-flaky device, inspect one bundle (~10min).

---

## Acceptance

- [ ] All `parse_fb_posts_from_xml` / `parse_fb_comments_from_xml` calls migrated to tuple return; existing tests green.
- [ ] `FB_CAPTURE_FAILURES=1` + triggered flake → bundle dir with 4-5 expected files.
- [ ] `FB_FAILURE_CAP` enforced — no more than N bundles per execution.
- [ ] `extraction_result` log event visible per extract step.
- [ ] Runbook exists.

---

## Deferred (re-add only if ops asks)

- DB table `failure_bundles` with index on `reason_code`
- `GET /api/executions/{id}/failures` operator API
- `replay_capture.py` CLI (existing test fixture pattern covers this today)
- Grafana dashboard / alerting
