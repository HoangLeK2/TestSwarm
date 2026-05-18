# Target Social Platform Profiles

Status: active
Last audited: 2026-05-19

Each target social platform must have a profile before platform-specific work is
considered product-ready. Profiles define what "supported" means across L1, L2,
and L3 coverage.

All platform-specific automation must be expressed as scenario steps or graph
nodes. A profile does not define a separate platform runner; it defines the
platform actions, extraction strategies, config, outputs, and failure modes that
the scenario engine must support.

## Coverage Levels

| Level | Meaning |
|---|---|
| L1 Independent device-session control | Operators can coordinate many independent device sessions while collecting evidence |
| L2 Scenario automation | Users can configure reusable scenarios/campaigns that automate platform workflows |
| L3 MCP agent tools | One AI agent can use MCP tools to control one device/session and adapt to screen state within guardrails |

## Initial Platforms

| Platform | Target level | Profile |
|---|---|---|
| TikTok | Draft target | `docs/product/platforms/tiktok.md` |
| Threads | Draft target | `docs/product/platforms/threads.md` |
| Facebook | L2 active, L3 foundation | `docs/product/platforms/facebook.md` |
| Instagram | Draft target | `docs/product/platforms/instagram.md` |

## Profile Template

```md
# <Platform> Profile

Status: draft | active
Target coverage: L1 | L2 | L3

## Product Goal

What this platform support must enable.

## Supported Data Scope

Public/feed-visible data and evidence this platform profile may collect.

## L1 Independent Device-Session Control

Required manual-control workflows and evidence.

## L2 Scenario Automation

Reusable scenario workflows, inputs, outputs, and failure modes.

List platform automation steps/nodes and extraction strategies. Each entry
should include step type, required config keys, optional per-device overrides,
outputs, evidence artifacts, retry behavior, and known failure modes.

Naming convention:

- Extraction uses `type: "extract"` plus `strategy:
  "<platform>_<data_object>"`.
- Actions use explicit step types named `<platform>_<verb>_<object>`.
- Legacy aliases may be documented for compatibility, but new examples should
  use canonical names.

Output convention:

- Social extraction output should declare a platform-qualified `content_type`
  such as `fb_post`, `fb_comment`, `tiktok_video`, `tiktok_comment`,
  `threads_post`, `ig_media`, or `ig_comment`.
- Avoid `thread` as a generic content object. Use `threads_post` for the Threads
  platform and parent-child/raw metadata for conversation grouping.
- Platform-specific fields belong in `raw_data` unless they map cleanly to
  common content columns.

## L3 MCP Agent Tools

MCP tools, guardrails, handoff rules, and required observations.

## Account And Session Requirements

Login/session/account constraints.

## Config Contract

Free-form JSON keys required by this platform profile. Include typed metadata
only when the workflow depends on it. Do not intentionally design platform
profiles around plaintext secrets in config, even though current config accepts
any valid JSON.

## Completion Criteria

What must be true before this profile is considered supported.
```
