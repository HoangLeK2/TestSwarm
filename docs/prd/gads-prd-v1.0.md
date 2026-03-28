# GADS — Product Requirements Document (Research)

---

- **Product Name:** GADS (Generic Automation Device System branding in README)
- **Version:** v5.2.0+ (track [releases](https://github.com/shamanec/GADS/releases))
- **Author / Maintainer:** shamanec & contributors
- **Last Updated:** 2026-03-28
- **Status:** Active development (per README)

---

## 1. Executive Summary

### Product Overview

**GADS** is a **self-hosted mobile & smart TV device farm** written in **Go**. It provides a **Hub** (web UI, API, authentication, optional embedded UI build), **Provider** agents on machine rooms, and **MongoDB** for logs/sync. Core capabilities: **remote control** (MJPEG/WebRTC video), **per-device Appium endpoint**, optional **Selenium Grid 4** or **experimental in-hub grid**, and **TV automation** (Samsung Tizen, LG webOS) without full remote control parity to phones.

### Problem Statement

Cloud device farms (AWS Device Farm, Firebase Test Lab) are costly; teams need:

- **On-prem** real devices with **reservation** and streaming
- **Standard automation** via **Appium** without custom vendor SDKs
- **Optional Grid** semantics for parallel CI

GADS solves **infrastructure + protocol surface**; **test logic** (if/loop) lives in **Appium clients** or manual UI, not in a GADS-native flow file.

### Success Criteria

| Metric | Target |
|--------|--------|
| Platforms | Android + iOS phones; TV automation (Tizen/WebOS) |
| Remote QA | Tap, swipe, keyboard, clipboard, install, screenshot |
| Automation | Dedicated Appium URL per device + OAuth client secret |
| Ops | Multi-provider, workspace ACL, Mongo-backed config |

---

## 2. Goals and Objectives

### Product Goals

- **Replace** expensive cloud labs for many orgs (positioning in README).
- **Unify** manual remote session + automated Appium in one platform.
- **Extend** to smart TV Appium drivers where mobile-style remote control is not required.

### User Goals

- Reserve device, see stream, interact from browser.
- Point CI at `http://hub:port/device/{id}/appium` with `gads:clientSecret`.
- Optionally use `/grid` for session allocation by capabilities.

### OKRs (interpreted from docs)

```
Objective 1: Reliable device access
+-- KR: Provider registers devices; Hub proxies control
+-- KR: iOS via WDA fork; Android via ADB + UiAutomator2

Objective 2: Secure automation
+-- KR: OAuth2 client credentials for Appium; hashed secrets

Objective 3: Fleet scale
+-- KR: Multiple providers; workspace-scoped access
```

---

## 3. Target Audience

### Persona 1: QA Automation Engineer

| Attribute | Detail |
|-----------|--------|
| Role | Writes Appium tests (Java/Python/JS) |
| Goals | Stable endpoint per device; parallel runs via Grid |
| Pain Points | Grid/Appium version mismatches |
| Quote | "Same capabilities as cloud farm but on our rack." |

### Persona 2: Manual QA / Support

| Attribute | Detail |
|-----------|--------|
| Role | Repro bugs on physical devices remotely |
| Goals | Low-latency video, keyboard input |
| Pain Points | WebRTC vs MJPEG tradeoffs |

### Persona 3: Platform / DevOps

| Attribute | Detail |
|-----------|--------|
| Role | Deploy Hub, MongoDB, providers on macOS/Linux/Windows |
| Goals | Service mode (systemd/WinSW docs), upgrades |
| Pain Points | iOS signing, WDA IPA upload, Grid jar version pins |

---

## 4. User Stories and Use Cases

### US-1: Connect Appium to a specific device

As an **automation engineer**, I want **`http://{hub}/device/{device-id}/appium`** with **`gads:clientSecret`**, so that **my test targets exactly one phone**.

**Acceptance Criteria:**

- Session creation works with documented capability only (device implied by URL).
- Secret validated server-side (bcrypt-hashed storage per docs).

**Priority:** P0

---

### US-2: Remote manual session

As a **QA tester**, I want **tap/swipe/text/screenshot** from the Hub UI**, so that **I can debug without the device on my desk**.

**Priority:** P0

---

### US-3: Run parallel tests via grid

As a **CI engineer**, I want **`http://hub/grid`** or **external Selenium Grid 4**, so that **sessions route to devices by UDID or platform capabilities**.

**Priority:** P1 (experimental grid caveat in docs)

---

### US-4: Automate TV apps

As a **TV app developer**, I want **Tizen/WebOS Appium drivers** on provider**, so that **I can run tests without mobile-style streaming**.

**Acceptance Criteria:**

- README: TV = **automation only**, no full remote control like phones.

**Priority:** P2 (niche)

---

### Use Case: CI pipeline with client credentials

1. Admin creates OAuth client in Hub; store secret in CI vault.
2. Job resolves `device-id` (API or static mapping).
3. Test framework opens session to `/device/{id}/appium` with `gads:clientSecret`.
4. Standard WebDriver flow: find, click, assert, screenshot.
5. Release device per farm policy (reservation UI/API).

---

## 5. Features and Requirements

### Feature 1: Hub — auth, workspaces, file uploads

**Description:** JWT/session auth, workspace ACL, admin uploads (WDA ipa, Selenium jar).

**Priority:** P0

---

### Feature 2: Provider — per-device Appium (optional)

**Description:** Node 16+ Appium on host; drivers xcuitest, uiautomator2, tizen-tv, webos per README.

**Priority:** P0 for automation path

---

### Feature 3: Streaming

**Description:** Android MJPEG; WebRTC experimental; iOS WDA stream / ffmpeg / broadcast extension paths.

**Priority:** P0 remote QA; WebRTC marked experimental in places

---

### Feature 4: Non-Appium interaction path

**Description:** README lists **non-Appium based interaction** on provider for certain flows (performance).

**Priority:** P1

---

### Feature 5: Experimental Hub Grid

**Description:** `http://hub/grid` — custom implementation; tested with TestNG + Java client; capability filters for UDID, platform, automationName, platformVersion.

**Priority:** P1 with **caveat**: may differ from Selenium Grid semantics

---

### Non-Functional Requirements

#### Security

- Client secrets hashed (bcrypt); TLS recommended in production
- `hub --auth=false` only for dev

#### Licensing

- **AGPL-3.0** for open components
- **hub-ui proprietary** — cannot modify/redistribute source; prebuilt zip from releases for `-tags ui` build

#### Platform matrix (host)

| Host | Android | iOS | TV |
|------|---------|-----|-----|
| macOS | Full | Full | Automation only |
| Linux / Windows | Full | Limited (no Xcode-only tools) | Automation only |

---

## 6. Technical Specifications

### Architecture

```
+----------+     +------------+
|  hub-ui  |     |  API/Grid  |
| (propr.) |     |  Go Hub    |
+----+-----+     +------+-----+
     |                 |
     +--------+--------+
              |
       +------v------+
       |  MongoDB    |
       +------^------+
              |
       +------+------+
       |  Provider(s)|  Go + Appium + platform tools
       +------+------+
              |
       +------v------+
       |  Devices      |
       +---------------+
```

### Stack (high level)

| Layer | Technology |
|-------|------------|
| Core | Go |
| DB | MongoDB 6.0 recommended |
| Automation | Appium 2 + drivers |
| iOS agent | [shamanec/WebDriverAgent](https://github.com/shamanec/WebDriverAgent) fork |
| TV | SDB, WebOS CLI per provider.md |

### Appium endpoint model

- URL path binds session to **one device**
- Capability: `gads:clientSecret` ([docs](https://github.com/shamanec/GADS/blob/main/docs/appium-credentials.md))

---

## 7. Analytics and Metrics

OSS product — no mandatory telemetry described in README. Operators track:

- Session count, provider uptime, stream failures, Grid queue depth

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| AGPL compliance for SaaS/network use | Medium | Legal | Legal review; use separate clean-room UI if needed |
| Proprietary hub-ui lock-in | Medium | Medium | Build without UI (`no_embed_ui`) or negotiate with vendor |
| Grid/Appium version fragility | Medium | High | Pin versions per hub docs (e.g. Selenium 4.13 note) |
| iOS signing & WDA churn | High | High | Follow fork updates; supervised devices optional |
| Experimental WebRTC quality | Medium | Medium | Fallback MJPEG |

---

## 9. Timeline and Milestones

### Current (per public README)

- Active development; releases ongoing (e.g. v5.2.0 Mar 2026 in search index)
- Experimental: Hub grid, WebRTC paths

### For Device Farmer

- [ ] Decide: GADS as **device plane** only vs full org standard
- [ ] Bridge: map `device-id` ↔ internal serial in dispatcher

---

## 10. Open Questions and Assumptions

### Open Questions

1. **AGPL** interaction with proprietary Device Farmer distribution model?
2. Use **embedded grid** vs external Selenium for CI?

### Assumptions

1. MongoDB available on LAN
2. Appium tests authored outside GADS (Java/Python/JS)

### Out of Scope (GADS product)

1. **YAML/JSON scenario DSL** with `repeat`/`if` — use test code or external orchestrator (e.g. Device Farmer scenarios)
2. **Pixel-perfect** cross-browser remote (browser testing is not core pitch)

---

## 11. Resources and Team

- **Repo:** [github.com/shamanec/GADS](https://github.com/shamanec/GADS)
- **Docs:** `docs/hub.md`, `docs/provider.md`, `docs/appium-credentials.md`
- **Internal short ref:** [gads-reference-and-scenario-mapping.md](../gads-reference-and-scenario-mapping.md)

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD-style research from public README/docs | Cursor |

---

## 13. Comparison Snapshot: GADS vs Maestro vs atxserver2

| Dimension | Maestro | GADS | atxserver2 |
|-----------|---------|------|------------|
| Core UX | YAML flows | Hub + Provider farm | Reservation REST + web |
| Automation hook | Own drivers + CLI | **Appium** URL | **uiautomator2** agent address |
| TV support | No (in Maestro PRD scope) | **Yes** (Tizen/WebOS) | No |
| License | OSS CLI + commercial cloud | AGPL + proprietary UI | MIT |
| Maintenance | Active | Active | **Legacy** |
