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
