# OpenSTF (STF) — Product Requirements Document (Research)

---

- **Product Name:** STF (Smartphone Test Farm)
- **Version:** 3.4.2 (Docker Hub) / 3.4.1 (npm) — last under **OpenSTF** org per README
- **Author / Maintainer:** OpenSTF project (historically CyberAgent; community + sponsors)
- **Last Updated:** 2026-03-28
- **Status:** **No active development** in [openstf](https://github.com/openstf) org; continuation tracked under **[DeviceFarmer](https://github.com/DeviceFarmer)** fork(s)

---

## 1. Executive Summary

### Product Overview

**STF** is a **browser-based** platform to **control, debug, and share** Android phones (and related gadgets) over the network. It provides real-time **screen streaming** (minicap), **touch/input** (minitouch), **APK drag-and-drop**, **shell**, **logcat**, **remote ADB** (`adb connect` via `remoteConnect` API), **inventory** (who uses which device), **booking & partitioning** (groups, schedules), and a **Swagger-documented REST API** with **OAuth2 bearer tokens**.

### Problem Statement

Organizations with **dozens to hundreds** of USB-connected devices need:

- Remote access **without physical possession** of each phone
- **Shared lab** with visibility into availability and ownership
- **Automation** hooks so CI can obtain a device and run ADB/Appium workflows

STF solves **device plane + manual QA + ADB bridging**; it does **not** provide a declarative cross-platform test language (contrast **Maestro**) or an internal **scenario JSON** engine (contrast **Device Farmer**).

### Success Criteria (historical)

| Metric | Target |
|--------|--------|
| Stream FPS | Up to ~30–40 FPS (device/host dependent) |
| API | Reserve / release / remoteConnect documented |
| Scale | Originally built for **160+** devices (README lore) |

**Today:** evaluate **DeviceFarmer** fork for fixes/modern stack; treat **openstf/stf** as reference or legacy deploy.

---

## 2. Goals and Objectives

### Original Goals

- Central **web UI** for all connected Android devices
- **minicap/minitouch**-based low-latency control
- **Enterprise-style** booking & partitioning (admin, groups, quotas)
- **Simple REST API** for automation (aligned with what **atxserver2** later mimicked)

### User Goals

- Click “Use” → control device; “Stop using” → release
- Generate **API token** in Settings → call REST from CI
- **POST remoteConnect** → `adb connect` → run **Appium** or **uiautomator2** locally

### OKRs (interpreted)

```
Objective 1: Lab visibility
+-- KR: Device list with present/offline/unauthorized states
+-- KR: Search by IMEI, version, operator, group, ...

Objective 2: Remote dev parity
+-- KR: adb shell, logcat, file explorer, port reverse (minirev)
+-- KR: Chrome remote debug workflow documented

Objective 3: Governance
+-- KR: Booking & partitioning (time-bounded groups)
+-- KR: Admin user/device management
```

---

## 3. Target Audience

### Persona 1: Manual QA / Developer

| Attribute | Detail |
|-----------|--------|
| Goals | Reproduce bugs on shared hardware remotely |
| Uses | Browser control, keyboard typing, screenshots |
| Pain | USB flakiness, hub power (README troubleshooting) |

### Persona 2: Automation Engineer

| Attribute | Detail |
|-----------|--------|
| Goals | Reserve device via API, `adb connect`, run tests |
| Uses | `POST /user/devices`, `POST .../remoteConnect`, [stf-appium-example](https://github.com/openstf/stf-appium-example) |
| Pain | Token lifecycle, ADB authorize, STF+IDE double-device quirks (README FAQ) |

### Persona 3: Lab Admin

| Attribute | Detail |
|-----------|--------|
| Goals | Partitions, bookings, quotas, user CRUD |
| Pain | Security model **not** hardened for hostile tenants (README **security note**) |

---

## 4. User Stories and Use Cases

### US-1: List and filter devices

As a **user**, I want **GET /api/v1/devices** with optional **fields** query, so that **I can find a free device**.

**Priority:** P0

---

### US-2: Reserve device

As a **user**, I want **POST /api/v1/user/devices** with `{ "serial", "timeout"? }**, so that **the device is locked to me** (timeout in ms per API doc).

**Priority:** P0

---

### US-3: Remote ADB for automation

As an **automation engineer**, I want **POST /api/v1/user/devices/{serial}/remoteConnect**, so that **I receive remoteConnectUrl** and run **`adb connect`**.

**Priority:** P0  
**Note:** ADB keys should be registered in STF settings first (per API doc).

---

### US-4: Release device

As a **user**, I want **DELETE /api/v1/user/devices/{serial}**, so that **others can use the device**.

**Priority:** P0

---

### Use Case: CI job with Appium

1. Create access token in STF UI (OAuth2).
2. Poll `GET /api/v1/devices` until target `serial` is `ready` and not `using`.
3. `POST /user/devices` with serial + timeout.
4. `POST .../remoteConnect` → `adb connect $url`.
5. Run Appium/uiautomator2 against connected device (see upstream example repo).
6. `DELETE .../remoteConnect` (optional) and `DELETE /user/devices/{serial}`.

---

## 5. Features and Requirements

### Feature 1: Real-time remote control

**Description:** minicap screen stream; minitouch multitouch; meta keys; copy/paste (limitations on old devices / non-Latin).

**Priority:** P0

---

### Feature 2: ADB & developer tooling

**Description:** Shell commands with live output; logcat; file explorer; reverse port forwarding (minirev); browser picker; Chrome remote debug.

**Priority:** P0

---

### Feature 3: Booking & partitioning

**Description:** Admin-level **groups**: devices + users + schedule; long-running **partitioning** vs time-bounded **booking**; see `GroupFeature.pdf` referenced in README.

**Priority:** P1 (enterprise differentiator)

---

### Feature 4: REST API (Swagger)

**Description:** OAuth2 bearer tokens; Swagger UI / `swagger.json`; client generation.

**Priority:** P0 for automation

**References:** [doc/API.md](https://github.com/openstf/stf/blob/master/doc/API.md)

---

### Feature 5: Inventory & admin

**Description:** Battery, locate-device (red screen), hardware specs, Play Store account rudiments; admin user/device management.

**Priority:** P1

---

### Non-Functional Requirements

#### Security (explicit README caveats)

- Internal traffic **often unencrypted**
- Malicious user with deep knowledge may **control devices not theirs** in classic deployment — **not** safe as multi-tenant SaaS without hardening
- Devices **not fully wiped** between users — test accounts only

#### Platform

| Role | Notes |
|------|--------|
| **Server OS** | Linux/CoreOS-class recommended; **macOS** discouraged for production (ADB issues) |
| **Client browser** | Modern browser for UI |
| **Android** | README lists **2.3.3 (API 10) – 9.0 (API 28)** — dated; fork may differ |

#### Dependencies (legacy README)

- Node.js **8.x** (pinned old)
- RethinkDB **≥ 2.2**
- GraphicsMagick, ZeroMQ, Protocol Buffers, yasm, pkg-config, ADB

---

## 6. Technical Specifications

### Process architecture

STF runs as **multiple independent Node processes** (provider, processor, app, auth, storage plugins, etc.); production uses **systemd** units; dev uses **`stf local`** helper.

### Architecture (logical)

```
+-------------+     +------------------+
|  Browser    |     |  REST / Swagger  |
+------+------+     +---------+--------+
       |                      |
       +----------+-----------+
                  |
           +------v------+
           |  STF core   |  Node.js services
           +------+------+
                  |
    +-------------+-------------+
    |             |             |
+---v---+   +-----v----+   +----v----+
| Rethink|   | ZeroMQ / |   | Provider|
|  DB    |   | messaging|   | workers |
+--------+   +----------+   +----+----+
                                   |
                            +------v------+
                            | USB devices  |
                            | + minicap/..|
                            +-------------+
```

### API authentication

- **OAuth 2.0** access tokens from UI (**Settings → Keys**)
- Header: `Authorization: Bearer <token>`

### Automation integration

- **remoteConnect** returns address for **`adb connect`**
- Official pointer: **[stf-appium-example](https://github.com/openstf/stf-appium-example)**

---

## 7. Analytics and Metrics

OSS project; optional **Open Collective** funding mentioned in README. No built-in product analytics described.

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| **OpenSTF org unmaintained** | High (stated) | High | Use **[DeviceFarmer](https://github.com/DeviceFarmer)** fork or alternate (GADS, etc.) |
| Old Node 8 / dependency chain | High | High CVE / build pain | Migrate to maintained fork |
| Weak security model | High in default README | Critical for internet-facing | Private network, VPN, audit fork patches |
| USB instability | Medium | Medium | Powered hubs, README hardware guide |
| `adb connect` + STF local dev quirks | Medium | Medium | Whitelist serial for `stf local` per FAQ |

---

## 9. Timeline and Milestones

### Historical

- [x] Mature feature set, 13k+ stars, widely deployed
- [x] Last OpenSTF release **3.4.x** (2020 per search snippet)

### Current

- [ ] Active line: **DeviceFarmer** organisation (per README banner)
- [ ] OpenSTF org: **no active development**

---

## 10. Open Questions and Assumptions

### Open Questions

1. Which **DeviceFarmer** repository is the canonical successor for your OS/Android range?
2. Does your lab still need **booking/partitioning** or only simple reservation?

### Assumptions

1. Target devices are **test phones**, not personal data-safe
2. Automation uses **ADB after remoteConnect**, not STF-native DSL

### Out of Scope (STF core)

1. **iOS device farm** (not STF core — see GADS / other tools)
2. **Declarative scenario** `repeat`/`if` — client-side or Device Farmer
3. **Hosted STF-as-a-Service** security without major hardening

---

## 11. Resources and Team

- **Repository:** [github.com/openstf/stf](https://github.com/openstf/stf)
- **API:** [doc/API.md](https://github.com/openstf/stf/blob/master/doc/API.md)
- **Appium example:** [stf-appium-example](https://github.com/openstf/stf-appium-example)
- **Successor org:** [DeviceFarmer](https://github.com/DeviceFarmer)
- **Internal short ref:** [stf-reference-and-scenario-mapping.md](../stf-reference-and-scenario-mapping.md)

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-28 | 1.0 | Initial PRD-style research (README + API.md) | Cursor |

---

## 13. Comparison: STF vs atxserver2 vs GADS vs Maestro

| Dimension | STF (OpenSTF) | atxserver2 | GADS | Maestro |
|-----------|----------------|------------|------|---------|
| **Primary focus** | Android browser lab + API | Tornado hub + u2/WDA **source** | Go Hub + Appium + TV | YAML UI tests |
| **iOS** | No (core) | Provider repo | Yes (WDA) | Yes |
| **API style** | OAuth2 + remoteConnect | Bearer + atxAgentAddress | Per-device Appium URL | N/A (CLI) |
| **Upstream status** | OpenSTF org **paused** | **Paused** (openatx) | **Active** | **Active** |
| **License** | See repo `LICENSE` | MIT | AGPL + proprietary UI | OSS CLI + cloud |

**Lineage:** atxserver2 API docs **explicitly reference** [STF API design](https://github.com/openstf/stf/blob/master/doc/API.md) — same reservation mental model, different implementation stack.
