# Device Farm Canary Rollout

This runbook applies to extraction refactors using `extract_profile` and
`strategy_version` on Facebook group templates.

## Scope

- Templates:
  - `fb_group_1h`
  - `fb_group_1h_one_group`
  - `fb_group_1h_multi_account` (inherits via `run_scenario`)
- Control variables in template:
  - `EXTRACT_PROFILE`
  - `FB_POSTS_STRATEGY_VERSION`
  - `FB_COMMENTS_STRATEGY_VERSION`

## Canary strategy

1. Keep baseline values:
   - `EXTRACT_PROFILE=balanced`
   - `FB_POSTS_STRATEGY_VERSION=fb_posts:v1`
   - `FB_COMMENTS_STRATEGY_VERSION=fb_comments:v1`
2. Roll canary by overriding one variable at a time in campaign variables:
   - example: `FB_COMMENTS_STRATEGY_VERSION=fb_comments:v2-canary`
3. Limit canary to 1-2 campaign/device pairs.
4. Compare against baseline executions:
   - extracted post count
   - extracted comment count
   - duplicate ratio
   - save errors in step details
5. Promote only if no regression in data quality and no step stability drop.

## Rollback

Immediate rollback is variable-only:

- Set `FB_POSTS_STRATEGY_VERSION` / `FB_COMMENTS_STRATEGY_VERSION` back to `:v1`.
- Keep `EXTRACT_PROFILE=balanced`.

No code rollback is required for version rollback.

## Crawl speed: fast-path + soft SLA

Crawl loop speed is split into two parts that must be measured and tuned
separately. There is **no flat 30s-per-post SLA** — comment volume varies far
too much for a single hard number to be meaningful.

| Component | Behavior | Target |
|-----------|----------|--------|
| **Transition** (capture + settle between nodes) | Fixed overhead, independent of comment count | **p50 ≤ 3s/loop** — can gate |
| **Post extract** (open + expand + dump) | Depends on truncation, not comments | p50 ≤ 15s, p95 ≤ 25s |
| **Comment extract** | Scales with comments; early-stops on no-new / no-growth / wall cap | No hard cap |

`total_ms = transition + post_extract + comment_extract`. Only the transition
floor and post-extract path are gated; the comment phase is allowed to scale
with content as long as it stops early when nothing new appears.

### Fast-path settings (cut transition)

Set on the crawl scenario body (or campaign scenario config):

```text
capture_steps      = false   # disables step screenshot/hierarchy capture (and its settle/stale-wait)
settle_timeout_ms  = 0        # no post-step settle sleep
```

`capture_steps: false` now wins even for campaign-bound executions (which used
to force capture on via the execution id). It can also be supplied as the
campaign variable `__CAPTURE_STEPS__=0`. Nested branch/loop-body steps
(`depth > 0`) skip per-step capture automatically unless a step sets
`require_capture: true`.

For builder-exported (`schema_version: 2.0`) templates, the equivalent lever is
setting `pre_capture: false` / `post_capture: false` on the steps.

### Adaptive comment extract (handler scales with content)

The comment scroller already early-stops; the relevant per-step keys are:

```text
comment_stop_if_no_new = true   # stop when no new comment keys appear (default on)
comment_no_growth_break = 2      # stop after N identical XML dumps
min_comment_scan_passes = 1      # minimum dumps before early-stop is allowed
comment_scroll_passes   = 48     # MAX budget, not a target — usually stops earlier
comment_scroll_wall_s   = 90     # wall-clock safety cap for huge threads (0 = disabled)
```

Short threads finish in a few dumps; long threads scroll until no-new / no-growth
or the wall cap. Post extract skips the "See more" expander entirely when the
opened post is not truncated (`expand_skip_if_not_truncated`, default on).

### Benchmark / gate

Use `agent-boot/scripts/mcp_crawl_all_nodes.py --mode transition --allow-nav`
to split per-step `wall_ms` into `transition_overhead_ms` vs handler counts and
to log the comment-count vs wall-time correlation. The gate is the transition
floor (`--transition-budget-ms`, default 3000), **not** total post time.

Alert on `transition_ms > 5s` (capture regression). Do not alert on total
duration exceeding any fixed per-post number.
