# Social Platform Extension Gaps

Status: active
Last audited: 2026-05-19

This plan tracks implementation gaps discovered while aligning the product docs,
platform profiles, and current codebase. It is intentionally action-oriented so
agents and developers can pick work without rereading the full PRD.

## References

- Product PRD: `docs/product/prd.md`
- Platform profile index: `docs/product/platforms/README.md`
- Facebook profile: `docs/product/platforms/facebook.md`
- Draft profiles: `docs/product/platforms/tiktok.md`,
  `docs/product/platforms/instagram.md`, `docs/product/platforms/threads.md`
- Extension contract: `docs/modules/social-platform-extensions.md`
- Scenario module: `docs/modules/campaigns-scenarios-executions.md`
- Content module: `docs/modules/content-extraction-artifacts.md`

## Priority Legend

| Priority | Meaning |
|---|---|
| P0 | Blocks consistency with the agreed product contract |
| P1 | Needed before adding more social platforms safely |
| P2 | Useful hardening or polish |

## Gap Summary

| ID | Priority | Area | Gap | Recommended next action |
|---|---|---|---|---|
| SPG-001 | P0 | Scenario execution | All execution surfaces must follow the authored scenario flow and scenario error policy consistently | Audit preview, session run, campaign run, MCP run, and Temporal-backed paths; align stop/continue/pause/ignore semantics |
| SPG-002 | P0 | Facebook action naming | Canonical `fb_tap_comment_button` is documented but not implemented; current code uses `tap_fb_comment_button` | Add backend alias/schema/frontend support or update examples to stay on legacy naming until alias exists |
| SPG-003 | P1 | Multi-platform extraction schema | Draft strategies such as `tiktok_videos`, `ig_media`, and `threads_posts` are not accepted by current step schema | Extend schema, handlers, tests, and frontend editor only when implementing each platform |
| SPG-004 | P1 | Platform-qualified content types | Current save paths may still produce generic `post`/`comment` content types in older templates | Update platform templates/examples and save steps to use `fb_post`, `fb_comment`, and future platform-qualified types |
| SPG-005 | P1 | Platform profiles | TikTok, Instagram, and Threads are draft profiles with no active implementation | Implement one platform at a time following `docs/modules/social-platform-extensions.md` checklist |
| SPG-006 | P1 | L3 MCP guardrails | MCP tools are generic; platform-specific L3 behavior is not profiled | Define platform-specific agent observations, allowed actions, and handoff rules before claiming L3 support |
| SPG-007 | P2 | Account/login handling | Scenario-owned account intent is documented, but legacy code may still infer device primary accounts in some dispatch paths | Audit and decide whether to preserve legacy behavior behind compatibility flags or migrate to explicit scenario intent |
| SPG-008 | P2 | Secret/config hardening | Free-form config may include credential-like values; hardening is intentionally low priority | Add vault/ref-based config later without blocking current free-form JSON behavior |

## Detailed Gaps

### SPG-001: Align Execution Surfaces With Authored Scenario Flow

Current contract:

- User-facing behavior follows the authored scenario flow.
- Step failure blocks later steps by default.
- `ignore_error` and `on_error` are scenario error policy when explicitly set.
- Recovery must be modeled through explicit branches, retry, loops, skip, pause,
  or nested recovery steps.

Known risk:

- Source contains multiple execution surfaces: device preview, preview stream,
  device/session run, campaign run, MCP-triggered run, and Temporal-backed
  campaign workflows.
- These surfaces may not apply error policy identically.

Acceptance criteria:

- Every execution surface has tests showing default stop-on-failure.
- Every execution surface has tests for explicit continue/ignore behavior if it
  supports scenario error policy.
- Documentation says which surfaces support pause/retry/skip.

### SPG-002: Implement Or Defer `fb_tap_comment_button`

Current contract:

- Canonical new action naming is `<platform>_<verb>_<object>`.
- Facebook profile prefers `fb_tap_comment_button`.
- Current code uses `tap_fb_comment_button`.

Recommended implementation:

- Add schema support for `fb_tap_comment_button`.
- Register handler alias to existing `tap_fb_comment_button` behavior.
- Add frontend node/editor label for canonical action.
- Keep `tap_fb_comment_button` as legacy alias for existing scenarios.
- Add regression tests proving both names work.

### SPG-003: Add Multi-Platform Extraction Strategies Deliberately

Current contract:

- Extraction step uses `type: "extract"` plus `strategy:
  "<platform>_<data_object>"`.
- Draft profiles propose strategies such as `tiktok_videos`, `tiktok_comments`,
  `ig_media`, `ig_comments`, `threads_posts`, and `threads_comments`.

Known risk:

- Strategy names appearing in draft docs are not active support.
- Adding names only to schema is insufficient. Each strategy needs parser logic,
  output mapping, content persistence tests, frontend support, and docs.

Acceptance criteria for each strategy:

- Backend schema accepts the strategy.
- Handler/parser returns normalized runtime objects.
- `save_extraction` can persist the correct platform-qualified `content_type`.
- Tests cover parser output and content persistence.
- Platform profile moves the relevant capability from draft to active.

### SPG-004: Migrate Templates To Platform-Qualified Content Types

Current contract:

- Social extraction output should use platform-qualified `content_type` values:
  `fb_post`, `fb_comment`, `tiktok_video`, `tiktok_comment`, `threads_post`,
  `ig_media`, `ig_comment`, etc.

Known risk:

- Existing templates or save paths may still use generic `post` or `comment`.

Recommended implementation:

- Audit seeded scenario templates and user-facing examples.
- Update Facebook templates to save posts as `fb_post` and comments as
  `fb_comment`.
- Preserve backward compatibility in content queries for old records.

### SPG-005: Implement Draft Platforms One At A Time

Current contract:

- TikTok, Instagram, and Threads profiles are draft and not active.
- Draft profile text must not be interpreted as implemented behavior.

Recommended sequencing:

1. Pick one platform and one data object.
2. Implement one extraction strategy end to end.
3. Add one minimal platform action step only if needed to reach that data.
4. Update platform profile from draft target to active capability.
5. Leave other platform capabilities as draft gaps.

### SPG-006: Define Platform-Specific L3 MCP Guardrails

Current contract:

- MCP exposes generic `df_*` device/session/scenario tools.
- L3 means one AI agent controls one device/session through MCP.
- Platform-specific L3 support is not claimed until guardrails are documented.

Recommended implementation:

- For Facebook first, define allowed observations, action boundaries, evidence
  expectations, and handoff rules.
- Add MCP examples that operate through authored scenario flow or bounded
  device/session actions.
- Avoid hidden platform assumptions in MCP-only prompts or tools.

### SPG-007: Decide Legacy Account Fallback Migration

Current contract:

- Scenario-owned account intent is canonical.
- Missing account/login config is a scenario configuration error owned by the
  scenario author.
- Device Farm should not infer a fallback account for new social workflows.

Known risk:

- Some code paths still use legacy primary-device account fallback.

Recommended options:

- Keep legacy behavior but document it as compatibility-only.
- Gate it behind an explicit scenario/campaign flag.
- Remove it after templates migrate to explicit account runtime config.

### SPG-008: Add Secret/Config Hardening Later

Current contract:

- Config is free-form valid JSON.
- Product intent is not to design workflows around plaintext credentials.
- Secret filtering, vault-backed refs, and typed schema are low priority.

Recommended implementation:

- Add optional secret metadata only after current scenario config behavior is
  stable.
- Do not block valid JSON config in the current product slice.
- Prefer migration paths that keep existing scenarios runnable.
