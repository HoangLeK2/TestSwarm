---
title: "Platform Neutral Scenario Nodes"
description: "Move scenario node catalog and runtime resolution away from Facebook-first behavior while preserving existing Facebook scenarios."
status: pending
priority: P1
effort: 4-6 days
branch: fix/relay-registration-scaling
tags: [feature, refactor, frontend, backend, scenario, platform-neutral, tech-debt]
created: 2026-08-29
---

# Platform Neutral Scenario Nodes

## Overview

Current code already has a platform-neutral social contract, but user-facing nodes, defaults, templates, and adapter coverage are still Facebook-first. This plan makes nodes neutral by default and keeps Facebook as one adapter with bounded platform-specific behavior, not a fallback target for other platforms.

Revision note:

- Facebook must not be used as "fallback execution" for another platform.
- Facebook-specific behavior should be modeled as reusable capability facets when possible.
- Write platform-specific code only when config/recipe/schema cannot safely express the behavior.

Research input: [Open Source Research](./research/opensource-patterns.md)

Related previous plan: `plans/2026-08-28-social-platform-neutral-nodes/plan.md`

## Current Evidence

- `device_farm/services/social_ext/contract.py` already says social step names must not carry platform names.
- `device_farm/services/social_ext/registry.py` has provider-like registry and draft platform loading for `tiktok`, `threads`, `instagram`.
- `front-end/src/features/campaigns/hooks/use-platform-capabilities.ts` already reads backend capability matrix.
- `front-end/src/features/campaigns/components/scenario-steps/types.ts` still exposes Facebook wording in labels/defaults.
- `device_farm/db/seeds/scenario_templates.py` is heavily Facebook template driven.
- `agent-boot/relay/u2_executor.py` still holds most real platform behavior in `_fb_*` functions.

## Target Rule

Default:

`node type` is platform-neutral.

Platform field:

- Optional for truly generic device/app/input/control nodes.
- Required for social/content/account capability nodes once the scenario is executable.
- May default from scenario/campaign platform, not hardcoded Facebook.

Platform-specific behavior:

- Each platform may declare special facets, for example `connection_kind=friend_request`, `community_surface=group`, `comment_filter_modes`, `post_surface_layout`.
- The node stays neutral; the adapter declares how the platform realizes that capability.
- If a requested platform lacks the capability, execution fails with an actionable unsupported message.
- The system may degrade to a generic locator/recipe only when the capability declares that degradation safe.
- It must not execute Facebook behavior for a non-Facebook platform.

## Phases

| # | Phase | Status | Effort | Link |
|---|-------|--------|--------|------|
| 1 | Node Inventory And Taxonomy | Pending | 0.5d | [phase-01](./phase-01-node-inventory-taxonomy.md) |
| 2 | Capability Contract V2 | Pending | 1d | [phase-02](./phase-02-capability-contract-v2.md) |
| 3 | Frontend Neutral Catalog | Pending | 1-1.5d | [phase-03](./phase-03-frontend-neutral-catalog.md) |
| 4 | Runtime Platform Resolver | Pending | 1-1.5d | [phase-04](./phase-04-runtime-platform-resolver.md) |
| 5 | Template Migration Strategy | Pending | 0.5-1d | [phase-05](./phase-05-template-migration.md) |
| 6 | Verification And Benchmarks | Pending | 0.5d | [phase-06](./phase-06-verification-benchmarks.md) |

## Recommended Architecture

```text
Scenario Step
  type: social.open_comments / social_open_comments
  platform: auto | facebook | instagram | tiktok | threads
  capability: social.comments.open
  facets:
    comment_surface: overlay | detail | unknown
    locator_strategy: hierarchy | ocr | image | adapter

        |
        v

Capability Registry
  declares input schema
  declares output schema
  lists compatible platforms
  lists safe generic recipes
  lists platform facets

        |
        v

Platform Resolver
  resolves requested platform
  checks org feature flag
  checks adapter support
  rejects unsupported combinations
  chooses generic recipe or adapter specialization

        |
        v

Adapter
  facebook implementation: existing _fb_* / social_actions
  future tiktok/instagram/threads implementation
```

## Non Goals

- Do not remove Facebook scenarios.
- Do not rewrite executor around Appium/Maestro/Airtest.
- Do not add TikTok/Instagram behavior without live platform research and adapter doctor checks.
- Do not silently convert existing saved scenarios to another platform.

## Main Decisions

- Use existing `social_ext` registry as provider boundary.
- Use existing frontend capability matrix, but make unsupported and platform-specific states visible.
- Keep migration aliases for old Facebook node names until one stable release after the new UI is shipped.
- Tests are written after implementation per user instruction, but each phase lists acceptance checks upfront.

## Risk

- Existing templates rely on Facebook defaults; changing defaults can break old scenarios.
- Some social node names are neutral but semantics are still Facebook-specific, especially friend request and group membership.
- Future platforms may use follow/subscribe/join semantics instead of Facebook friend/group semantics.
- Trace must show requested platform, resolved platform, selected recipe/adapter, and platform facets or debugging will be misleading.
