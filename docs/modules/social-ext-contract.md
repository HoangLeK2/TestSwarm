# Social Extension Contract

Status: active
Last updated: 2026-05-31

## Ownership Boundary

`device_farm` owns the social extension contract, registry, discovery API,
feature flags, scenario schema, and scenario-step dispatch.

`agent-boot` owns extra data: XML/hierarchy parser execution, extra-data ingest,
content row construction, and `raw_data` persistence. Do not add a second raw XML
parser or raw payload persistence path in `device_farm`.

## Interfaces

The stable contract version is `1.0.0` and is exposed from
`device_farm/services/social_ext/contract.py`.

| Interface | Purpose |
|---|---|
| `PlatformParser.parse(snapshot, context)` | Declares parser shape; active raw parsing is delegated to `agent-boot/relay/extra_data`. |
| `PlatformHandler.execute(ctx, step)` | Declares platform step handler shape. Runtime dispatch still goes through authored scenario steps. |
| `PlatformScenarioLib` | Registers step types, extraction strategies, and user-facing templates. |
| `PlatformContentTypeSchema` | Registers platform-qualified content types and storage ownership metadata. |

## Discovery API

| Endpoint | Purpose |
|---|---|
| `GET /api/social-ext/platforms` | List registered platform extensions and storage owner metadata. |
| `GET /api/social-ext/platforms/{platform}/steps` | List step types, legacy aliases, strategies, and content types. |
| `GET /api/social-ext/orgs/{org_id}/platforms` | Read per-org platform feature flags. |
| `POST /api/social-ext/orgs/{org_id}/platforms/{platform}/enable` | Enable a platform for an org. |
| `POST /api/social-ext/orgs/{org_id}/platforms/{platform}/disable` | Disable a platform for an org. |
| `POST /api/social-ext/platforms/{platform}/load` | Load a known extension version without restart. |
| `POST /api/social-ext/platforms/{platform}/unload` | Unload an extension for new work while preserving already dispatched work. |
| `POST /api/social-ext/platforms/{platform}/migrate` | Migrate within the same SemVer major version. Major bumps are rejected. |
| `GET /api/social-ext/platforms/{platform}/version-history` | Inspect runtime lifecycle events. |

## Current Registration

Facebook is L2 Active. `fb_tap_comment_button` is the canonical comment-button
step and `tap_fb_comment_button` remains a legacy alias that dispatches to the
same handler.

TikTok, Threads, and Instagram are registered as draft metadata with feature
flags disabled by default. Their extra-data storage owner is still `agent-boot`.
