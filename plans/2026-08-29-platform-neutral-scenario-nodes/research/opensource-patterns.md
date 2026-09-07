---
title: "Open Source Research - Platform Neutral Scenario Nodes"
created: 2026-08-29
scope: "Research OSS automation/workflow patterns before planning Device Farm node neutrality"
---

# Open Source Research - Platform Neutral Scenario Nodes

## Research Channels

- Local repo search: used `rg`, targeted file reads.
- Web official docs/GitHub public pages: used for Appium, Robot Framework, Node-RED, Airflow, Maestro, Airtest, OpenTelemetry.
- Package registry preflight: npm available (`11.12.1`), `python3 -m pip` available, `python` alias missing.
- GitHub CLI: authenticated and available. No private external mutation done.

## OSS Findings

### Appium

Source:

- https://appium.io/docs/en/latest/developing/build-drivers/
- https://appium.io/docs/en/2.19/developing/build-plugins/
- https://appium.io/docs/en/3.6/reference/cli/extensions/

Useful pattern:

- Core exposes protocol/session.
- Driver/plugin owns platform-specific behavior.
- Extension lifecycle is explicit: install, list, doctor, update, uninstall.
- Before writing a driver, you must know how that platform can be launched, controlled, and read.

Device Farm implication:

- Keep scenario node names platform-neutral.
- Platform adapter must declare support and health/doctor result before UI enables it.
- Do not create `facebook_*`, `tiktok_*`, `instagram_*` public nodes.
- Add adapter doctor/readiness checks before enabling a platform in production.

### Robot Framework

Source:

- https://robotframework.org/robotframework/latest/RobotFrameworkUserGuide.html

Useful pattern:

- Core is target-independent.
- High-level keywords compose lower-level keywords.
- Libraries handle target interaction.
- Variables/tags make flows reusable across environments.

Device Farm implication:

- Treat Device Farm node as a keyword/capability.
- Templates should compose capabilities and variables.
- Platform-specific selectors, labels, and choreography belong to adapter libraries.
- Scenario author should see `Open comments`, not `Tap Facebook comment button`.

### Node-RED

Source:

- https://nodered.org/docs/creating-nodes/

Useful pattern:

- Nodes should be well-defined and simple.
- Hide implementation complexity and domain jargon.
- Be forgiving in accepted inputs.
- Be consistent in output properties.
- Catch errors; never leave runtime state unknown.

Device Farm implication:

- Split overloaded social nodes by purpose, not by platform.
- Standardize output envelopes per node family.
- Error output must include `reason_code`, `platform`, `adapter`, `capability`, and trace path.
- UI should show unsupported platform states, not silently default to Facebook.

### Apache Airflow Providers

Source:

- https://airflow.apache.org/docs/apache-airflow-providers/index.html
- https://airflow.apache.org/docs/apache-airflow/stable/howto/custom-operator.html

Useful pattern:

- Core remains stable; providers add integrations.
- Providers can be upgraded/downgraded independently.
- Operators should avoid expensive work at construction time.
- Execution happens with runtime context.

Device Farm implication:

- `services/social_ext` should act as provider registry.
- Adapter metadata must be cheap to load.
- Expensive platform probes run only in doctor/readiness or execution.
- Adapter version/lifecycle must be visible to frontend and trace.

### Maestro

Source:

- https://maestro.dev/
- https://github.com/mobile-dev-inc/maestro

Useful pattern:

- Human-readable command flows.
- Platform target is config, command language stays compact.
- Good fit for simple launch/tap/input/assert flows.

Device Farm implication:

- Do not replace current executor.
- Borrow its command vocabulary discipline: simple generic commands, platform/app details as config.
- Future adapter may compile simple Device Farm steps to Maestro only when it reduces custom code.

### Airtest

Source:

- https://airtest.netease.com/
- https://github.com/airtestproject/airtest

Useful pattern:

- Cross-platform automation with image recognition and UI hierarchy.
- Useful alternate locator path when native selectors are weak.

Device Farm implication:

- Keep `tap_image`, `extract_text_ocr`, hierarchy extract as generic primitives.
- Do not bake Facebook label heuristics into generic nodes.
- Adapter can choose UI hierarchy, OCR, image matching, or platform API per capability.

### OpenTelemetry

Source:

- https://opentelemetry.io/docs/specs/semconv/general/trace/
- https://opentelemetry.io/docs/specs/semconv/general/events/

Useful pattern:

- Shared semantic attributes make traces comparable across languages/platforms.
- Distinct events should carry occurrence-specific attributes.

Device Farm implication:

- Extend recent traceability with semantic fields:
  - `scenario.step.id`
  - `scenario.step.path`
  - `scenario.node.type`
  - `scenario.capability`
  - `scenario.platform.requested`
  - `scenario.platform.resolved`
  - `scenario.adapter`
  - `scenario.reason_code`
- This keeps frontend trace useful after Facebook is no longer the default mental model.

## Recommendation

Adopt patterns, not frameworks, for this phase.

Reason:

- Device Farm already has executor, relay, capability registry, template migration, and trace events.
- Replacing executor with Appium/Maestro/Airtest would be a rewrite.
- The correct next step is a thin capability/provider model around existing handlers.
- Libraries can be optional adapter internals later, after capability contracts are stable.

## Design Principle

Default path:

`generic node -> capability contract -> platform resolver -> adapter implementation`

Specialization path:

`generic node -> capability facets -> platform recipe/config -> adapter implementation only when needed`

Never:

`generic node -> implicit Facebook behavior`

Also never:

`unsupported platform -> run Facebook instead`
