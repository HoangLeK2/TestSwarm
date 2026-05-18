# atxserver2 — Product Requirements Document (Research)

---

- **Product Name:** atxserver2
- **Version:** 0.2.0 (release tag); codebase tip `master`
- **Author / Maintainer:** openatx community (codeskyblue et al.)
- **Last Updated:** 2026-03-28
- **Status:** Maintenance / legacy (upstream README: **不再积极开发** — recommend other platforms)

---

## 1. Executive Summary

### Product Overview

**atxserver2** is an open-source **smartphone management platform** (Python) for **Android and iOS**, reimplemented from the earlier atx-server. It provides a **web UI**, **REST API** (OpenSTF-inspired device reservation), and integration with **separate provider processes** that attach physical devices. After reserving a device, clients receive **`source` connection metadata** to drive automation via **[uiautomator2](https://github.com/openatx/uiautomator2)** (Android) or **WebDriverAgent** URLs (iOS).

### Problem Statement

Teams running **real device labs** need:

- Central **inventory** of who is using which device
- **Remote screen + input** for manual QA
- **Stable endpoints** for automation (ADB-over-network, u2 agent, WDA) without re-plugging USB

atxserver2 addresses **reservation + discovery + provider bridge**; it does **not** ship a declarative test language (unlike Maestro YAML or Device Farmer `scenario.steps`).

### Success Criteria (historical / evaluation lens)

| Metric | Target (when project was active) |
|--------|----------------------------------|
| Device visibility | List online/offline, in-use, cooling state |
| Reservation API | Bearer-token REST, idle timeout, admin override |
| Android automation path | Expose `atxAgentAddress` for uiautomator2 |
| iOS automation path | Expose `wdaUrl` + optional screen WebSocket |

**Today:** treat as **reference architecture** or **fork base** only; not a greenfield default per upstream guidance.

---

## 2. Goals and Objectives

### Original Product Goals

- Replace/upgrade atx-server with **async Tornado** + clearer structure (Django-like layout).
- **Unify Android + iOS** under one hub (with separate provider repos).
- Align reservation semantics with **OpenSTF**-style APIs for familiarity.

### User Goals

- See all devices in a browser; **occupy / release** programmatically.
- Run **uiautomator2** tests against occupied Android devices using returned agent address.
- Install **APK/IPA** via provider HTTP (`source.url`).

### Product Objectives (reframed for Device Farmer context)

```
Objective 1: Device pool governance
+-- KR: REST list/filter devices (?platform=apple&usable=true)
+-- KR: POST reserve + DELETE release + idleTimeout auto-release

Objective 2: Automation handoff
+-- KR: Android source exposes atxAgentAddress + remoteConnectAddress + secret
+-- KR: iOS source exposes wdaUrl; WS screen at ${wdaUrl}/screen

Objective 3: Operational deployment
+-- KR: docker-compose for server; Docker image for android-provider
```

---

## 3. Target Audience

### Persona 1: QA / Test Automation Engineer

| Attribute | Detail |
|-----------|--------|
| Role | Writes **Python uiautomator2** tests |
| Goals | Get a **reserved** device and a working **u2 HTTP endpoint** |
| Pain Points | USB contention, unknown who holds the phone |
| Quote | "Give me the agent URL and I'll run the suite." |

### Persona 2: Device Lab Admin

| Attribute | Detail |
|-----------|--------|
| Role | Maintains machines with USB farms |
| Goals | User auth, admin **force release**, asset tags |
| Pain Points | RethinkDB ops, legacy stack |
| Quote | "I need a dashboard and API, not spreadsheets." |

### Persona 3: Mobile Developer (manual)

| Attribute | Detail |
|-----------|--------|
| Role | Remote debug on shared hardware |
| Goals | Web remote control (right-click BACK, middle HOME) |
| Pain Points | Latency, provider stability |

---

## 4. User Stories and Use Cases

### US-1: List usable devices

As a **test engineer**, I want to **GET /api/v1/devices?usable=true**, so that **I only see free online devices**.

**Acceptance Criteria:**

- Response includes `present`, `using`, `colding`, `platform`, `properties`.
- `usable` ≡ present ∧ ¬using ∧ ¬colding.

**Priority:** P0

---

### US-2: Reserve and release a device

As a **test engineer**, I want to **POST /api/v1/user/devices** with `{ "udid", "idleTimeout"? }**, so that **the device is locked to me until I release or time out**.

**Acceptance Criteria:**

- Bearer token required (`Authorization: Bearer …` from `/user`).
- **GET** `/api/v1/user/devices/{UDID}/active` refreshes activity.
- **DELETE** `/api/v1/user/devices/{UDID}` releases.

**Priority:** P0

---

### US-3: Obtain automation `source` after reservation

As a **test engineer**, I want **GET /api/v1/user/devices/{UDID}** to return **`source`**, so that **I can connect uiautomator2 or WDA**.

**Acceptance Criteria:**

- Android: `atxAgentAddress`, `remoteConnectAddress`, `whatsInputAddress`, `secret`, `url` (provider).
- iOS: shared `url`; `wdaUrl`; screen stream via WebSocket on `${wdaUrl}/screen`.

**Priority:** P0

---

### US-4: Install app via provider

As a **lab user**, I want to **POST $PROVIDER_URL/app/install?udid=…** with **apk/ipa URL**, so that **I don’t manually sideload**.

**Acceptance Criteria:**

- Uses `source.url` from occupied device payload.
- Optional `launch=true` for APK.

**Priority:** P1

---

### Use Case: Run uiautomator2 after reservation

**Actor:** Automation engineer  
**Preconditions:** Android provider running; device online; user authenticated  

**Main flow:**

1. `GET /api/v1/devices?usable=true` → pick `udid`
2. `POST /api/v1/user/devices` with `udid`
3. `GET /api/v1/user/devices/{udid}` → read `source.atxAgentAddress`
4. Configure uiautomator2 client to use agent (see [uiautomator2 docs](https://github.com/openatx/uiautomator2))
5. Execute test script (Python); poll `…/active` during long runs
6. `DELETE …/user/devices/{udid}` when done

**Alternative:** Admin passes `email` in POST body to reserve on behalf of another user.

---

## 5. Features and Requirements

### Feature 1: Web UI + authentication

**Description:** Browser-based device list and remote control; auth plugins (`simple`, `openid`, `github`).

**Functional Requirements:**

1. First logged-in user becomes **admin**
2. Admin: force release others’ sessions (ALT + double-click per README); impersonate reservation via API
3. User profile page: **personal token** for API

**Priority:** P0  
**Dependencies:** RethinkDB, Tornado

---

### Feature 2: REST API (OpenSTF-style)

**Description:** Token-authenticated JSON API for users and devices.

**Functional Requirements:**

1. `GET /api/v1/user`, `GET /api/v1/devices`, `GET /api/v1/devices/{udid}`
2. Reserve / active / release endpoints as in [API.md](https://github.com/openatx/atxserver2/blob/master/API.md)
3. Upload APK to `/uploads` (documented; parts marked TODO in upstream)

**Priority:** P0

---

### Feature 3: Android provider integration

**Description:** Separate project **atxserver2-android-provider** pushes **atx-uiautomator.apk, minicap, minitouch, atx-agent** to devices.

**Functional Requirements:**

1. Docker deployment on Linux with `--privileged`, USB passthrough
2. Optional `--owner=group|email` for **private device pools** (Beta; Android only per README)

**Priority:** P0  
**Dependencies:** Python 3.6+, **Node.js** on provider host

---

### Feature 4: iOS provider integration

**Description:** **atxserver2-ios-provider** — follow linked repo; exposes WDA URL in `source`.

**Priority:** P1  
**Dependencies:** macOS-centric tooling typical for WDA

---

### Feature 5: Remote control UX

**Description:** Mouse mapping for navigation (right = BACK, middle = HOME).

**Priority:** P2

---

### Non-Functional Requirements

#### Security

- API: Bearer tokens; 403 on bad token
- `secret` in `source` for agent auth — treat as sensitive in logs

#### Reliability

- `colding` state blocks reservation during cleanup/self-check (per API doc)

#### Platform support

| Host (server) | Notes |
|---------------|--------|
| Linux | RethinkDB recommended in README |
| docker-compose | Documented path |

| Device class | Support |
|--------------|---------|
| Android | Primary, best documented |
| iOS | Via ios-provider |
| Smart TV / other | **Out of scope** in core README |

---

## 6. Technical Specifications

### System Architecture

```
+------------------+       +------------------+
|  Browser (UI)    |       |  REST clients    |
+--------+---------+       +--------+---------+
         |                          |
         +------------+-------------+
                      |
             +--------v---------+
             |  atxserver2      |  Tornado (async)
             |  main.py         |
             +--------+---------+
                      |
             +--------v---------+
             |  RethinkDB       |
             +--------+---------+
                      ^
                      | register / heartbeat
             +--------|---------+
             |  android-provider |  (separate process / Docker)
             |  ios-provider     |
             +--------+---------+
                      |
             +--------v---------+
             |  USB / network    |
             |  phones           |
             +-------------------+
```

### Technology Stack

| Layer | Technology |
|-------|------------|
| Server language | Python (async views) |
| Web framework | Tornado |
| Database | RethinkDB (`RDB_HOST`, `RDB_PORT`, …) |
| Run (current docs) | `uv run main.py` |
| Android on-device | uiautomator2 ecosystem, minicap, minitouch, atx-agent |
| License | MIT |

### Data concepts (API)

- **Device:** `udid`, `platform` (`android` \| `apple`), flags `present`, `using`, `colding`, `properties`
- **source:** provider `url` + platform-specific endpoints (see §4 US-3)

---

## 7. Analytics and Metrics

Not a first-class product feature in OSS server. **N/A** for hub telemetry. Operators may log:

| Metric | Use |
|--------|-----|
| Reservation duration | Capacity planning |
| `colding` frequency | Provider health |

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **Project unmaintained** | High (stated by authors) | High | Prefer active stacks (GADS, internal farm, Maestro Cloud, etc.) |
| RethinkDB operational burden | Medium | Medium | Containerize; evaluate forks or migration if forking atxserver2 |
| Security of agent `secret` / tokens | Medium | High | TLS reverse proxy, secret rotation, network segmentation |
| Provider + Node/Python version drift | Medium | Medium | Pin Docker images; CI smoke tests |
| iOS path less documented than Android | Medium | Medium | Budget time for WDA/signing like any iOS farm |

---

## 9. Timeline and Milestones

### Historical

- [x] v0.2.0 release (Apr 2019 per GitHub releases)
- [x] REST API, web UI, android-provider Docker story
- [x] MIT license

### Current (2026)

- [x] Minor doc update: `uv run main.py`
- [ ] **No active roadmap** per README — “choose another platform”

### For Device Farmer integration (optional)

- [ ] Evaluate: reservation API only vs full UI deploy
- [ ] Map `atxAgentAddress` → existing **uiautomator2** worker path (strong alignment with openatx stack)

---

## 10. Open Questions and Assumptions

### Open Questions

1. **Fork vs replace:** If internal team needs this model, is forking atxserver2 cheaper than extending Device Farmer dispatcher?
2. **DB migration:** Long-term RethinkDB support vs rewriting persistence layer?

### Assumptions

1. Operators can run RethinkDB and expose hub on trusted network
2. Android tests are primarily **Python uiautomator2**, not in-server YAML
3. iOS requires separate provider expertise (signing, WDA)

### Out of Scope (product)

1. **Declarative scenario DSL** (repeat/if as server features) — client-side only
2. **Smart TV automation**
3. **Official hosted SaaS** — self-hosted only

---

## 11. Resources and Team

### Repositories

| Repo | Role |
|------|------|
| [atxserver2](https://github.com/openatx/atxserver2) | Hub + API |
| [atxserver2-android-provider](https://github.com/openatx/atxserver2-android-provider) | Android agent deploy |
| [atxserver2-ios-provider](https://github.com/openatx/atxserver2-ios-provider) | iOS |
| [uiautomator2](https://github.com/openatx/uiautomator2) | Automation client |

### Internal companion doc

- Short reference: [atxserver2-reference-and-scenario-mapping.md](../atxserver2-reference-and-scenario-mapping.md)

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD-style research (README + API.md) | Cursor |

---

## 13. Comparison Snapshot: atxserver2 vs Maestro (context)

| Dimension | Maestro | atxserver2 |
|-----------|---------|------------|
| Primary artifact | **YAML flows** on disk | **HTTP API** + web UI |
| Execution model | CLI interprets commands | **You** run Python/u2 or WDA |
| Cross-platform test syntax | Built-in | **None** (by design) |
| Device farm | Maestro Cloud (commercial) | **Self-hosted** hub + providers |
| Maintenance | Active product | **Legacy** per upstream |

Use **Maestro PRD** (`maestro-prd-v1.0.md`) for *how to write tests*; use **this PRD** for *how a Python/u2-centric reservation hub behaved*.
