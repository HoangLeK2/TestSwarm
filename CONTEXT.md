# Device Farm

Device Farm is a social-media automation and data-collection context built on
managed Android devices. This glossary defines the project language used across
product docs, module docs, and implementation work.

## Language

**Product Requirements Document**:
The active product-facing source of truth for product intent, users, outcomes, and capability requirements.
_Avoid_: external PRD, archived PRD, module spec

**Module Documentation**:
The implementation-facing contract for one bounded project module.
_Avoid_: PRD, ticket spec

**Archived Reference**:
Historical or research material preserved for context but not valid as an implementation contract.
_Avoid_: source of truth, active spec

**Social Media Automation**:
Automation of actions and workflows on social platforms such as TikTok, Instagram, and Facebook.
_Avoid_: generic Android automation when discussing the current product focus

**Target Social Platform**:
A mainstream social app that Device Farm intentionally supports for automation and data collection.
_Avoid_: random app, test app

**Target Platform Profile**:
The product-facing contract that defines supported workflows, steps, extraction output, account expectations, and gaps for one target social platform.
_Avoid_: ad hoc platform notes, hidden parser assumptions

**Draft Platform Profile**:
A target platform profile that defines intended contracts and gaps before active implementation support exists.
_Avoid_: supported platform, active platform contract

**Platform Automation Step**:
A scenario step or graph node that performs a platform-specific social action or extraction operation.
_Avoid_: separate platform runner, out-of-band Facebook automation

**Platform Action Step**:
A **Platform Automation Step** that performs a platform-specific action on a social app screen.
_Avoid_: generic platform action blob, hidden action script

**Platform Extraction Strategy**:
A **Platform Automation Step** extraction mode that identifies a target social platform and data object.
_Avoid_: unscoped parser name, platform runner

**Legacy Platform Step Alias**:
An older platform-specific step name preserved for backward compatibility but not used as the naming model for new work.
_Avoid_: canonical step name

**Social Data Collection**:
Large-scale collection of social media content and evidence from real device screens or app state.
_Avoid_: scraping, testing output

**Platform-Qualified Content Type**:
A content classification key that combines target platform and social data object, such as `fb_post` or `tiktok_comment`.
_Avoid_: ambiguous generic content type when platform-specific classification matters

**External Entity**:
An organization-owned, reusable identity for an external source such as a group, profile, page, channel, or community.
_Avoid_: Facebook-only group record, search-result row

**External Entity Observation**:
A time-stamped set of mutable facts seen for an **External Entity**, such as member count, privacy, status, or display name.
_Avoid_: overwriting history, treating changing metrics as identity

**External Entity Discovery**:
The search or navigation context that explains how an **External Entity** was found, including query and result rank.
_Avoid_: using a search query as the entity identity

**Entity Assignment**:
The dispatch-time mapping that gives one **Independent Device Session** one **External Entity** and freezes the target facts used by that run.
_Avoid_: resolving the target again during retry, sharing one mutable target across devices

**Threads Post**:
A platform-qualified content type for a post-like item from Meta Threads.
_Avoid_: generic thread object

**Conversation Thread**:
A relationship or grouping between social content items, usually represented through parent/child links or raw platform metadata.
_Avoid_: Threads platform post, standalone content object by default

**Social Account**:
An external-platform account used by social automation workflows.
_Avoid_: scenario variable only, device account row only

**Account Runtime Config**:
Account-related values supplied through scenario config, device context, or resolved account resources for a scenario run.
_Avoid_: mandatory vault-backed credential contract in the current product slice

**Scenario-Owned Account Intent**:
The rule that a scenario must explicitly provide or reference the account/login information it needs.
_Avoid_: implicit account fallback

**Scenario Configuration Error**:
A run failure caused by missing or invalid scenario/device config required by the scenario's own steps, usually discovered during execution.
_Avoid_: platform bug, device failure, preflight-only validation failure

**UI-Gated Step**:
A scenario step that must observe or rely on current app UI state before its action can be considered successful.
_Avoid_: blind command, fire-and-forget step

**Step-Blocking Failure**:
A step failure that stops the remaining scenario steps from running.
_Avoid_: skip and continue by default

**Explicit Recovery Path**:
Scenario-authored retry, branch, skip, pause, or recovery behavior that defines what to do when UI state differs from the expected path.
_Avoid_: hidden recovery, implicit continue-on-error

**Authored Scenario Flow**:
The user-defined sequence of scenario steps, branches, retries, and recovery paths that Device Farm executes.
_Avoid_: backend-specific execution flow as product behavior

**Scenario Error Policy**:
Scenario-authored behavior that defines whether a failed step stops, continues, pauses, or is ignored.
_Avoid_: hidden backend error handling

**AI-Agent Assisted Operation**:
An automation mode where an AI agent interprets screen state and proposes or performs bounded actions.
_Avoid_: generic AI, magic automation

**L1 Independent Device-Session Control**:
The coverage level where operators coordinate many independent device sessions through Device Farm tools and scenario context.
_Avoid_: bulk-only console, single-device manual testing

**L2 Scenario Automation**:
The coverage level where users configure reusable scenarios that automatically drive devices through Device Farm tools.
_Avoid_: hardcoded script, one-off macro

**L3 MCP Agent Tools**:
The coverage level where one AI agent uses MCP tools to control one device/session flexibly.
_Avoid_: unbounded autonomous control

**Media Source**:
A device-identified producer of encoded screen media, usually one Android device serial emitting H.264 frames.
_Avoid_: viewer, WebRTC session

**Media Session**:
A short-lived viewer authorization to receive one **Media Source** through a selected media transport.
_Avoid_: device session, scenario session, peer connection as the domain object

**Media Viewer**:
The user/browser-side consumer attached to a **Media Session**.
_Avoid_: device, relay, source

**Media Transport**:
The delivery mechanism used by a **Media Session**, such as WebRTC or the legacy WebSocket H.264 path.
_Avoid_: treating WebRTC implementation objects as domain language

**Independent Device Session**:
A device-bound work context that can progress separately from other devices while sharing campaign or operator coordination.
_Avoid_: shared global session

**Scenario Config**:
The default key-value configuration used throughout a scenario run.
_Avoid_: global settings, script constants

**Device Context**:
Per-device configuration applied to an independent device session for a scenario.
_Avoid_: device session row, runtime state

**Device Config Override**:
A device-specific value that replaces a matching **Scenario Config** value for one scenario-device pair.
_Avoid_: separate script, forked scenario

**Effective Runtime Config**:
The merged configuration actually used by a scenario on one device.
_Avoid_: raw scenario variables

**Free-Form Config**:
Valid JSON configuration accepted without a formal typed schema.
_Avoid_: invalid JSON, unparseable text config

**Typed Config Schema**:
A future stricter contract that defines config keys, types, defaults, and validation metadata.
_Avoid_: current mandatory config format

**Config Secret Hardening**:
A future control layer that prevents or redirects secrets away from free-form scenario/device config.
_Avoid_: current required validation

**Group Action**:
An explicit action fanned out to multiple selected devices as a coordination helper.
_Avoid_: primary execution model

**Generic Android Automation**:
Broader app automation or testing use cases that the platform can support but is not currently optimized for.
_Avoid_: core product focus

## Relationships

- A **Product Requirements Document** describes product intent for multiple **Module Documentation** files.
- **Module Documentation** links product capabilities to current source code, API contracts, and data ownership.
- An **Archived Reference** may inform future work but must be revalidated before it affects **Module Documentation**.
- **Social Media Automation** is the current product focus; **Generic Android Automation** is broader platform scope.
- A **Target Social Platform** includes TikTok, Threads, Facebook, Instagram, and other mainstream social platforms as they are added.
- A **Target Platform Profile** defines what "supported" means for one **Target Social Platform**.
- A **Draft Platform Profile** helps future implementation follow the shared platform contract, but it must not be presented as supported behavior.
- **Platform Automation Steps** are the canonical way to express Facebook, TikTok, Threads, Instagram, or future social-platform-specific actions and extraction.
- A **Platform Action Step** should name the target platform, action, and object clearly.
- A **Platform Extraction Strategy** should identify the target platform and extracted data object.
- A **Legacy Platform Step Alias** may remain valid for old scenarios, but new docs and templates should use the canonical naming model.
- A **Platform-Qualified Content Type** is the primary content classification key for social extraction output.
- An **External Entity** is stable and reusable; changing platform facts belong to **External Entity Observations**.
- An **External Entity Discovery** records why a source appeared without becoming part of its identity.
- An **Entity Assignment** belongs to one **Independent Device Session** and remains stable for retries of that run.
- Use **Threads Post** for post-like items from the Threads platform.
- Use **Conversation Thread** for reply/conversation grouping; do not make `thread` a generic social content object by default.
- A **Social Account** is a resource, but the current product slice may pass account-related values through **Account Runtime Config** for simplicity.
- **Account Runtime Config** follows the same free-form scenario/device config rules; credential separation is future hardening, not a current blocker.
- **Scenario-Owned Account Intent** means the scenario author is responsible for declaring account/login inputs when the workflow needs them.
- If a scenario needs login/account data and does not provide it, Device Farm still follows the scenario as written; any resulting stuck flow or failure is a **Scenario Configuration Error**, not an implicit fallback.
- Social automation steps are **UI-Gated Steps** by default.
- A failed **UI-Gated Step** creates a **Step-Blocking Failure** unless the scenario explicitly models an alternate branch or retry behavior.
- An **Explicit Recovery Path** is the only canonical way for a scenario to continue, retry, skip, pause, or branch after unexpected UI state.
- Device Farm follows the **Authored Scenario Flow**. Backend execution engines are implementation details, not separate product semantics.
- **Scenario Error Policy** is part of the **Authored Scenario Flow** when explicitly set by the scenario author.
- **Social Data Collection** can be produced by **L1 Independent Device-Session Control**, **L2 Scenario Automation**, or **L3 MCP Agent Tools**.
- **L2 Scenario Automation** and **L3 MCP Agent Tools** depend on **L1 Independent Device-Session Control** primitives.
- An **Independent Device Session** belongs to exactly one device at a time.
- An **Independent Device Session** always has **Device Context**.
- A **Media Source** is identified by device serial but is not itself an **Independent Device Session**.
- A **Media Session** grants one **Media Viewer** access to one **Media Source** through one **Media Transport**.
- A **Media Session** must not authorize control actions; control remains part of **L1 Independent Device-Session Control**.
- A **Scenario Config** provides default values for every independent run of that scenario.
- A **Device Config Override** wins over a matching **Scenario Config** value.
- An **Effective Runtime Config** is produced from **Scenario Config** plus **Device Context** and runtime variables.
- **Free-Form Config** is the current accepted config format as long as it is valid JSON.
- **Typed Config Schema** is desirable but not required for the current product slice.
- **Config Secret Hardening** is desirable but not prioritized; current **Free-Form Config** may accept any valid JSON.
- **L3 MCP Agent Tools** bind one AI agent to one **Independent Device Session** at a time.
- A **Group Action** may affect many devices, but it is not the primary execution model.

## Example dialogue

> **Dev:** "Can I implement from the Maestro PRD in the archive?"
> **Domain expert:** "No. Use the active **Product Requirements Document** for intent and the relevant **Module Documentation** for implementation details. Treat archived PRDs as reference only."
>
> **Dev:** "Should I optimize this workflow for generic mobile testing?"
> **Domain expert:** "No. Testing can reuse the platform later, but this product slice should optimize for **Social Media Automation** and **Social Data Collection** first."
>
> **Dev:** "If ten devices run the same scenario, do they share one config?"
> **Domain expert:** "They share the same **Scenario Config** defaults, but each **Independent Device Session** has its own **Device Context** and may apply **Device Config Overrides**."
>
> **Dev:** "Should Facebook automation be implemented as a separate runner?"
> **Domain expert:** "No. Facebook automation, and later TikTok, Threads, and Instagram automation, should be represented as **Platform Automation Steps** inside scenarios."
>
> **Dev:** "Should new social extraction be one generic platform action?"
> **Domain expert:** "No. Use clear **Platform Action Steps** for actions and **Platform Extraction Strategies** for extraction. Preserve any old names only as **Legacy Platform Step Aliases**."
>
> **Dev:** "Should extracted content use generic `post` or platform-specific `fb_post`?"
> **Domain expert:** "Use a **Platform-Qualified Content Type** such as `fb_post` as the main classification key. Keep generic fields only when they help filtering or compatibility."
>
> **Dev:** "Should `thread` be a generic content object?"
> **Domain expert:** "No. Use **Threads Post** for the Threads platform. Use **Conversation Thread** only as relationship/grouping metadata."
>
> **Dev:** "Is an account just scenario JSON?"
> **Domain expert:** "No. A **Social Account** is a resource, but current scenarios can use **Account Runtime Config** to keep execution simple. Strong credential separation comes later."
>
> **Dev:** "If a login step has no account config, should Device Farm pick the device primary account?"
> **Domain expert:** "No. **Scenario-Owned Account Intent** wins. Run the scenario as written; missing login/account values are a **Scenario Configuration Error** if the scenario gets stuck or fails."
>
> **Dev:** "If a UI action step fails, should later steps continue?"
> **Domain expert:** "No. Steps are **UI-Gated Steps** by default. A failed step is a **Step-Blocking Failure** and stops the scenario unless the scenario explicitly defines branching or retry behavior."
>
> **Dev:** "What if the user wants recovery when UI changes?"
> **Domain expert:** "Model it as an **Explicit Recovery Path** with retry, condition branches, pause, skip, or nested recovery steps."
>
> **Dev:** "Does the behavior depend on whether the backend uses Temporal?"
> **Domain expert:** "No. Product behavior is the **Authored Scenario Flow**. Temporal or any other backend runner is an implementation detail."
>
> **Dev:** "Is `ignore_error` part of the scenario or backend behavior?"
> **Domain expert:** "It is **Scenario Error Policy**, so it is part of the **Authored Scenario Flow** when the user sets it."
>
> **Dev:** "Where do I document Facebook-specific behavior?"
> **Domain expert:** "Use the Facebook **Target Platform Profile**. Do not hide platform assumptions only in parser code or templates."
>
> **Dev:** "Can I create profiles for platforms not implemented yet?"
> **Domain expert:** "Yes, but mark them as **Draft Platform Profiles** and document gaps clearly."

## Flagged ambiguities

- "PRD" was used for both active product requirements and archived external-tool research. Resolved: **Product Requirements Document** means `docs/product/prd.md`; archived PRDs are **Archived References**.
- "Android automation platform" was too broad for the current product direction. Resolved: the current focus is **Social Media Automation** and **Social Data Collection**; **Generic Android Automation** is secondary platform scope.
- Platform scope was initially phrased as examples only. Resolved: Device Farm aims to cover mainstream **Target Social Platforms**, starting with TikTok, Threads, Facebook, and Instagram.
- Platform-specific automation placement was unresolved. Resolved: Facebook and all future social-platform automation belong inside scenario steps/nodes as **Platform Automation Steps**.
- Platform step naming was unresolved. Resolved: extraction uses **Platform Extraction Strategies**, actions use explicit **Platform Action Steps**, and existing old names are **Legacy Platform Step Aliases**.
- Platform documentation ownership was unresolved. Resolved: each supported platform needs a **Target Platform Profile**.
- Unimplemented platform docs were unresolved. Resolved: TikTok, Instagram, and Threads may have **Draft Platform Profiles** that describe target contracts without claiming support.
- Social content classification was unresolved. Resolved: extracted social records should use **Platform-Qualified Content Type** keys such as `fb_post`, `fb_comment`, `tiktok_video`, or `threads_post`.
- "Thread" was ambiguous between the Threads platform and conversation grouping. Resolved: use **Threads Post** for the platform object and **Conversation Thread** for relationship/grouping semantics.
- Account ownership versus scenario config was unresolved. Resolved: **Social Account** remains a resource, while current execution may carry account-related values through **Account Runtime Config**; credential separation is low priority.
- Account fallback was unresolved. Resolved: **Scenario-Owned Account Intent** is canonical; missing required account/login config is discovered by running the scenario and treated as a **Scenario Configuration Error**, not an implicit device-account fallback.
- Step failure semantics were unresolved. Resolved: social automation steps are **UI-Gated Steps** and a failed step creates a **Step-Blocking Failure** by default.
- Recovery semantics were unresolved. Resolved: recovery must be an **Explicit Recovery Path** authored into the scenario.
- Execution-engine semantics were unresolved. Resolved: user-facing behavior follows the **Authored Scenario Flow**; backend engines must conform to it.
- Error policy ownership was unresolved. Resolved: explicit `on_error` or `ignore_error` is **Scenario Error Policy** and belongs to the authored scenario.
- "Bulk manual control" implied one shared group console as the primary model. Resolved: L1 is **L1 Independent Device-Session Control**; **Group Action** is optional support.
- "Device session" could mean a database row or a product-level work context. Resolved: product docs use **Independent Device Session** for the work context and **Device Context** for per-device config.
- Config schema strictness was unresolved. Resolved: current config is **Free-Form Config**; **Typed Config Schema** is a future quality layer.
- Secret handling in config was unresolved. Resolved: config should not intentionally contain secrets, but **Config Secret Hardening** is low priority and current acceptance remains any valid JSON.
