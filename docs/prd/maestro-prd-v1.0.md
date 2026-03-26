# Maestro - Product Requirements Document

---

- **Product Name:** Maestro
- **Version:** 2.3.0
- **Author:** Maestro Team
- **Last Updated:** 2026-03-26
- **Status:** In Development

---

## 1. Executive Summary

### Product Overview

Maestro is an open-source, cross-platform UI/end-to-end testing framework for mobile and web applications. It provides a unified, YAML-based testing syntax that works across Android, iOS, and web platforms — enabling teams to write human-readable, resilient test flows without platform-specific code.

### Problem Statement

Mobile and web UI testing is fragmented, brittle, and complex:

- **Platform fragmentation**: Teams must learn and maintain separate toolchains (Espresso/UIAutomator for Android, XCTest for iOS, Selenium/Playwright for web).
- **Test flakiness**: Traditional UI tests are unreliable due to timing issues, asynchronous rendering, and element identification failures.
- **High barrier to entry**: Existing frameworks require deep programming knowledge, making test creation inaccessible to QA engineers and non-developers.
- **Slow iteration**: Code-based test frameworks require compilation, slowing the feedback loop during development.

### Success Criteria

| Metric | Target |
|--------|--------|
| Cross-platform coverage | Android, iOS, and Web from a single flow file |
| Test flakiness rate | < 2% on stable apps |
| Time to first test | < 10 minutes from install |
| Community adoption | Growing open-source contributor base |

---

## 2. Goals and Objectives

### Business Goals

- Establish Maestro as the go-to UI testing framework for mobile-first teams.
- Drive adoption of Maestro Cloud (commercial offering) through open-source CLI usage.
- Reduce the cost and complexity of mobile app quality assurance across the industry.

### User Goals

- Write one set of tests that works across platforms.
- Eliminate flaky tests without manual retries or sleep hacks.
- Enable non-developers (QA, product) to author and read tests.
- Integrate UI tests into CI/CD pipelines with minimal setup.

### Product Objectives (OKRs)

```
Objective 1: Make mobile UI testing accessible to all team members
+-- KR 1.1: 43+ YAML commands covering all common UI interactions
+-- KR 1.2: Zero compilation required - interpreted flow execution
+-- KR 1.3: Visual Studio (IDE) for no-code test authoring

Objective 2: Deliver reliable, flake-free test execution
+-- KR 2.1: Built-in automatic waiting with configurable timeouts
+-- KR 2.2: Smart element selection with multiple selector strategies
+-- KR 2.3: Retry and tolerance mechanisms at command and flow level

Objective 3: Enable AI-augmented testing capabilities
+-- KR 3.1: AI-powered visual assertions (assertWithAI)
+-- KR 3.2: AI-driven defect detection (assertNoDefectsWithAI)
+-- KR 3.3: AI text extraction from screenshots (extractTextWithAI)
```

---

## 3. Target Audience

### Persona 1: QA Engineer

| Attribute | Detail |
|-----------|--------|
| Role | QA / Test Automation Engineer |
| Tech Proficiency | Medium |
| Goals | Write reliable UI tests without deep mobile development knowledge |
| Pain Points | Flaky tests, platform-specific tooling, long feedback loops |
| Current Solutions | Appium, Detox, manual testing |
| Quote | "I just want to describe what the user does and verify it works." |

### Persona 2: Mobile Developer

| Attribute | Detail |
|-----------|--------|
| Role | Android/iOS Developer |
| Tech Proficiency | High |
| Goals | Quickly validate UI flows during development without heavyweight frameworks |
| Pain Points | Espresso/XCTest boilerplate, slow test compilation, device management |
| Current Solutions | Platform-native test frameworks, manual smoke testing |
| Quote | "I need tests that run fast and don't break every time I change a layout." |

### Persona 3: CI/CD Engineer

| Attribute | Detail |
|-----------|--------|
| Role | DevOps / Platform Engineer |
| Tech Proficiency | High |
| Goals | Integrate mobile testing into automated pipelines |
| Pain Points | Complex device farm setup, unreliable test results blocking releases |
| Current Solutions | Firebase Test Lab, AWS Device Farm, custom scripts |
| Quote | "If a test fails in CI, I need to trust it's a real bug, not infrastructure noise." |

### Persona 4: Engineering Manager / Tech Lead

| Attribute | Detail |
|-----------|--------|
| Role | Team Lead managing mobile delivery |
| Tech Proficiency | Medium-High |
| Goals | Ship mobile apps faster with confidence in quality |
| Pain Points | QA bottlenecks, no cross-platform test reuse, scaling test execution |
| Current Solutions | Multiple testing tools per platform, manual regression |
| Quote | "We need one solution the whole team can use, not three different frameworks." |

---

## 4. User Stories and Use Cases

### US-1: Write a Cross-Platform Test Flow

As a **QA engineer**,
I want to **write a single YAML test flow** that runs on both Android and iOS,
so that **I don't have to maintain separate test suites per platform**.

**Acceptance Criteria:**

Given a YAML flow file with `launchApp` and UI interaction commands
When I run `maestro test flow.yaml` targeting an Android emulator
Then the flow executes successfully against the Android app

Given the same YAML flow file
When I run `maestro test flow.yaml` targeting an iOS simulator
Then the flow executes successfully against the iOS app

**Priority:** P0
**Story Points:** 8

---

### US-2: Assert UI Element Visibility

As a **mobile developer**,
I want to **assert that specific UI elements are visible after an action**,
so that **I can verify my UI renders correctly**.

**Acceptance Criteria:**

Given an app is running on a connected device
When I include `assertVisible: "Welcome"` in my flow
Then Maestro waits (up to the configured timeout) for an element with text "Welcome" to appear
And the step passes if found, or fails with a clear error message if not

**Priority:** P0
**Story Points:** 3

---

### US-3: Use AI-Powered Visual Assertions

As a **QA engineer**,
I want to **use AI to verify that a screen looks correct without pixel-perfect comparisons**,
so that **I can catch visual regressions without brittle screenshot diffs**.

**Acceptance Criteria:**

Given an app screen is displayed
When I include `assertWithAI` with a natural language assertion (e.g., "the login form has two input fields and a blue submit button")
Then Maestro captures a screenshot, sends it to an AI model, and returns pass/fail with reasoning

**Priority:** P1
**Story Points:** 5

---

### US-4: Run Tests in CI/CD Pipeline

As a **CI/CD engineer**,
I want to **run Maestro tests as part of my build pipeline**,
so that **UI regressions are caught before merging**.

**Acceptance Criteria:**

Given Maestro CLI is installed in the CI environment
When I run `maestro test --format junit flows/`
Then all flow files in the directory execute sequentially
And results are output in JUnit XML format for CI integration
And the process exits with code 0 on success, non-zero on failure

**Priority:** P0
**Story Points:** 5

---

### US-5: Visually Design Tests with Maestro Studio

As a **QA engineer with limited coding experience**,
I want to **use a visual IDE to build test flows by inspecting and interacting with the app**,
so that **I can create tests without writing YAML by hand**.

**Acceptance Criteria:**

Given a device/emulator is connected
When I run `maestro studio`
Then a web-based IDE opens showing a live device screenshot
And I can click elements to generate tap commands
And I can inspect the view hierarchy to find element selectors
And I can export the flow as a YAML file

**Priority:** P1
**Story Points:** 13

---

### Use Case: End-to-End Login Flow Test

**Actor:** QA Engineer
**Trigger:** New build is deployed to a test environment
**Preconditions:** App is installed on a connected device/emulator

**Main Flow:**
1. QA engineer writes a YAML flow: `launchApp`, `tapOn: "Email"`, `inputText: "user@test.com"`, `tapOn: "Password"`, `inputText: "secret"`, `tapOn: "Login"`, `assertVisible: "Dashboard"`
2. Runs `maestro test login-flow.yaml`
3. Maestro launches the app, executes each command with automatic waiting
4. All assertions pass; test reports success

**Alternative Flows:**
- If `assertVisible` times out: Maestro reports failure with a screenshot of the current state
- If the app crashes: Maestro detects the crash and reports it with stack trace (if available)

**Postconditions:** Test result (pass/fail) with screenshots is available for review

---

## 5. Features and Requirements

### Feature 1: YAML-Based Flow Engine

**Description:** Core execution engine that interprets YAML flow files and translates them into platform-specific device interactions.

**User Value:** Write tests in a simple, human-readable format without code compilation.

**Functional Requirements:**
1. Parse YAML flow files with 43+ supported commands
2. Support variable interpolation (`${VAR}`) and environment variables
3. Support flow composition via `runFlow` (sub-flows)
4. Support conditional execution, loops (`repeat`), and retry logic
5. Support JavaScript evaluation via `evalScript` and inline scripts
6. Apply automatic waiting before each interaction (configurable timeout)

**Acceptance Criteria:**

Given a valid YAML flow file
When executed via `maestro test`
Then each command is interpreted and dispatched to the appropriate platform driver
And the engine waits for the app to settle before each action
And variables are resolved from environment, CLI args, or `defineVariables`

**Priority:** P0 (Must)
**Effort:** XL
**Dependencies:** Platform drivers (Android, iOS, Web)

**Edge Cases:**
- Malformed YAML: Report parse error with line number
- Undefined variable: Fail with clear error naming the variable
- Infinite loop in `repeat`: Respect max iteration limits

---

### Feature 2: Multi-Platform Driver Architecture

**Description:** Abstraction layer (`Driver` interface) with platform-specific implementations for Android, iOS, and Web.

**User Value:** Same test works across all platforms without modification.

**Functional Requirements:**
1. `Driver` interface defines unified API: tap, swipe, scroll, input text, assert, screenshot, view hierarchy
2. Android driver communicates via gRPC to an on-device UIAutomator/JUnit server (`maestro-server.apk`)
3. iOS driver communicates via HTTP to an XCTest runner on the simulator/device
4. Web driver uses Selenium WebDriver for browser automation
5. Automatic device discovery and connection management

**Acceptance Criteria:**

Given a YAML flow with `tapOn: "Submit"`
When executed on Android
Then the Android driver uses gRPC to find and tap the element via UIAutomator

Given the same flow
When executed on iOS
Then the iOS driver uses HTTP/XCTest to find and tap the element

**Priority:** P0 (Must)
**Effort:** XL
**Dependencies:** Android SDK, Xcode/XCTest, Selenium

---

### Feature 3: Smart Element Selection

**Description:** Flexible, multi-strategy element selector system for reliably identifying UI elements.

**User Value:** Find elements by text, ID, position, traits, or relationships — reducing selector fragility.

**Functional Requirements:**
1. Match by text (exact, regex, contains)
2. Match by accessibility ID / resource ID (regex)
3. Positional selectors: `below`, `above`, `leftOf`, `rightOf`, `childOf`, `containsChild`, `containsDescendants`
4. Trait-based matching: `enabled`, `selected`, `checked`, `focused`, `clickable`
5. Size-based matching with tolerance
6. Index-based selection for duplicate matches
7. CSS selectors for web platform
8. Visibility percentage filtering

**Acceptance Criteria:**

Given multiple "Submit" buttons on screen
When I use `tapOn` with `below: "Payment Section"` and `index: 0`
Then Maestro selects only the first "Submit" button below the "Payment Section" element

**Priority:** P0 (Must)
**Effort:** L

---

### Feature 4: Maestro Studio (Visual IDE)

**Description:** Web-based visual IDE for interactive test design, element inspection, and flow authoring.

**User Value:** Build tests visually without writing YAML by hand; inspect element hierarchy in real-time.

**Functional Requirements:**
1. Ktor backend serves React SPA and proxies device interactions
2. Live device screenshot display with clickable element overlay
3. View hierarchy inspector with element attribute details
4. Command palette for generating YAML commands from interactions
5. AI-assisted command generation
6. Drag-and-drop flow reordering
7. Export flow as `.yaml` file

**Acceptance Criteria:**

Given a connected device
When I launch `maestro studio`
Then a browser opens showing the device screen
And I can click an element to see its selectors (text, ID, position)
And I can add the interaction as a step in my flow

**Priority:** P1 (Should)
**Effort:** XL
**Dependencies:** Connected device/emulator, Ktor server

---

### Feature 5: AI-Powered Testing

**Description:** Integration with AI models (Anthropic Claude, OpenAI GPT) for visual assertions, defect detection, and text extraction from screenshots.

**User Value:** Assert complex visual states in natural language; catch visual defects without pixel comparisons.

**Functional Requirements:**
1. `assertWithAI`: Pass a natural language assertion and a screenshot to an AI model; return pass/fail with reasoning
2. `assertNoDefectsWithAI`: Analyze a screenshot for visual defects (overlapping elements, truncated text, misalignment)
3. `extractTextWithAI`: Extract structured text from a screenshot region using AI
4. Support multiple AI providers (Anthropic, OpenAI) with configurable API keys
5. Graceful degradation if AI service is unavailable

**Acceptance Criteria:**

Given `assertWithAI: "The shopping cart shows 3 items"`
When executed during a flow
Then Maestro captures a screenshot, sends it to the configured AI provider
And returns pass if the AI confirms the assertion, fail otherwise
And includes the AI's reasoning in the test output

**Priority:** P1 (Should)
**Effort:** L
**Dependencies:** AI provider API keys, network access

---

### Feature 6: CLI and CI/CD Integration

**Description:** Full-featured command-line interface for running tests, managing devices, and integrating with CI/CD systems.

**User Value:** Run tests locally or in pipelines with standard tooling and output formats.

**Functional Requirements:**
1. `maestro test` - Run flow files or directories of flows
2. `maestro studio` - Launch visual IDE
3. `maestro record` - Record device interactions
4. `maestro cloud` - Upload and run tests on Maestro Cloud
5. `maestro query` - Query device state
6. JUnit XML output format for CI integration
7. Exit codes: 0 (success), non-zero (failure)
8. Device selection via `--device` flag
9. Environment variable injection via `--env KEY=VALUE`
10. Analytics opt-in via PostHog integration

**Acceptance Criteria:**

Given Maestro is installed
When I run `maestro test --format junit --output results/ flows/`
Then all flows execute and results are written as JUnit XML to `results/`
And the exit code reflects overall pass/fail status

**Priority:** P0 (Must)
**Effort:** L

---

### Non-Functional Requirements

#### Performance
| Metric | Target |
|--------|--------|
| CLI startup time | < 3 seconds |
| Command execution latency | < 500ms per command (excluding app response time) |
| Screenshot capture | < 1 second |
| View hierarchy retrieval | < 2 seconds |

#### Security
- No sensitive data stored in flow files (environment variables for secrets)
- AI API keys managed via environment variables, not configuration files
- gRPC communication between CLI and device is local-only (no network exposure)
- No telemetry of test content; analytics limited to usage patterns (opt-in)

#### Scalability
- Single device per CLI instance (Maestro Cloud for parallel execution)
- Support for running multiple CLI instances concurrently on different devices
- Flow files are stateless and parallelizable

#### Reliability
- Automatic retry on transient device communication failures
- Graceful handling of app crashes during test execution
- Configurable command timeouts (default + per-command overrides)

#### Accessibility
- YAML flow format is screen-reader friendly (plain text)
- Maestro Studio follows WCAG AA guidelines
- Keyboard navigation support in Studio IDE

#### Platform Support

**Host OS:**
| Platform | Support |
|----------|---------|
| macOS | Full (Android + iOS + Web) |
| Linux | Android + Web |
| Windows | Android + Web |

**Target Platforms:**
| Platform | Driver | Communication |
|----------|--------|---------------|
| Android (API 24+) | UIAutomator via gRPC | Local gRPC |
| iOS (14+) | XCTest via HTTP | Local HTTP |
| Web (Chromium) | Selenium WebDriver | Local HTTP |

---

## 6. Technical Specifications

### System Architecture

```
                    +-------------------+
                    |   YAML Flow Files |
                    +--------+----------+
                             |
                    +--------v----------+
                    |   Maestro CLI     |  (PicoCLI, Kotlin)
                    +--------+----------+
                             |
                    +--------v----------+
                    |   Orchestra       |  (Flow interpreter, JS engine)
                    +--------+----------+
                             |
                    +--------v----------+
                    |   Maestro Client  |  (Unified Device API)
                    +--------+----------+
                             |
              +--------------+--------------+
              |              |              |
     +--------v---+  +------v-----+  +-----v------+
     |  Android   |  |    iOS     |  |    Web     |
     |  Driver    |  |   Driver   |  |   Driver   |
     |  (gRPC)    |  |   (HTTP)   |  | (Selenium) |
     +--------+---+  +------+-----+  +-----+------+
              |              |              |
     +--------v---+  +------v-----+  +-----v------+
     | UIAutomator|  |  XCTest    |  | Chromium   |
     | Server APK |  |  Runner    |  | WebDriver  |
     +------------+  +------------+  +------------+
```

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Kotlin 2.2.0 (JVM, Java 17) |
| Build | Gradle (multi-module, version catalog) |
| CLI Framework | PicoCLI |
| HTTP Server | Ktor 2.3.6 + Netty |
| HTTP Client | OkHttp 4.12.0, Ktor Client |
| RPC | gRPC 1.50.2 + Protocol Buffers (proto3) |
| Serialization | Jackson (YAML, JSON, XML), Kotlinx Serialization |
| JavaScript | GraalVM JS 24.2.0 (Rhino fallback) |
| Web Automation | Selenium 4.40.0 |
| AI Integration | Anthropic Claude API, OpenAI API |
| Frontend (Studio) | React 18, TypeScript, Tailwind CSS 3, Radix UI |
| Logging | Log4j2 + SLF4J |
| Testing | JUnit 5, Mockk, Google Truth |
| Analytics | PostHog |
| Packaging | Shadow JAR, JReleaser |

### Data Models

**MaestroCommand** (union type, 43+ fields):
Core command model representing any YAML command. Each field maps to a specific command class (e.g., `TapOnElementCommand`, `AssertConditionCommand`, `LaunchAppCommand`).

**ElementSelector**:
```
textRegex        : String?       # Match by text (regex)
idRegex          : String?       # Match by resource/accessibility ID
size             : SizeSelector? # Match by dimensions
below            : ElementSelector? # Positional: below another element
above            : ElementSelector? # Positional: above another element
leftOf           : ElementSelector? # Positional: left of another element
rightOf          : ElementSelector? # Positional: right of another element
childOf          : ElementSelector? # Hierarchical: child of another element
containsChild    : ElementSelector? # Contains matching child
containsDescendants : List<ElementSelector>? # Contains matching descendants
traits           : List<Trait>?  # enabled, selected, checked, focused
index            : Int?          # Nth match
css              : String?       # CSS selector (web only)
```

**TreeNode** (view hierarchy):
```
attributes : Map<String, String>  # text, id, bounds, class, etc.
children   : List<TreeNode>       # Recursive child nodes
clickable  : Boolean
enabled    : Boolean
focused    : Boolean
checked    : Boolean
selected   : Boolean
```

**DeviceInfo**:
```
widthPixels  : Int
heightPixels : Int
widthGrid    : Int    # Logical pixels
heightGrid   : Int
platform     : Platform  # ANDROID | IOS | WEB
```

### gRPC Service Definition (Android)

Key RPCs defined in `maestro_android.proto`:
- `DeviceInfo` - Query device properties
- `ViewHierarchy` - Get UI element tree
- `Tap` / `TapWithTimeout` - Touch interactions
- `InputText` / `EraseAllText` - Text input
- `Swipe` - Swipe gestures
- `Screenshot` - Capture screen
- `LaunchApp` / `StopApp` / `ClearAppState` - App lifecycle
- `SetLocation` - Mock GPS location
- `SetPermissions` - Grant/revoke permissions
- `AddMedia` - Push media files to device

---

## 7. Analytics and Metrics

### Key Performance Indicators

| Category | Metric | Target |
|----------|--------|--------|
| Adoption | CLI installs / month | Growing MoM |
| Activation | Users who run first test within 1 hour of install | > 60% |
| Engagement | Tests executed / user / week | > 20 |
| Retention | Users active after 30 days | > 40% |
| Quality | Test flakiness rate (Maestro infrastructure) | < 2% |
| Cloud conversion | % of CLI users who try Maestro Cloud | > 10% |

### Event Tracking (PostHog)

| Event | Description | Priority |
|-------|-------------|----------|
| `cli_install` | CLI installed successfully | P0 |
| `test_executed` | A flow was run | P0 |
| `test_result` | Pass/fail outcome | P0 |
| `studio_launched` | Studio IDE opened | P1 |
| `cloud_upload` | Test uploaded to Maestro Cloud | P0 |
| `ai_assertion_used` | AI-powered command executed | P1 |
| `error_occurred` | CLI error by type | P1 |

---

## 8. Risks and Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| iOS driver instability due to Apple XCTest changes | Medium | High | Maintain close tracking of Xcode releases; automated compatibility tests |
| AI provider API changes or downtime | Medium | Medium | Multi-provider support (Anthropic + OpenAI); graceful degradation |
| Android fragmentation (OEM-specific behaviors) | High | Medium | Community bug reports; device-specific workarounds in driver |
| GraalVM JS engine compatibility issues | Low | Medium | Rhino fallback engine; comprehensive JS test suite |
| Selenium/WebDriver breaking changes | Medium | Low | Pin versions; web driver is secondary platform |
| Competition from platform-native test improvements | Medium | Medium | Focus on cross-platform value prop and developer experience |
| Open-source maintenance burden | High | Medium | Clear contribution guidelines; modular architecture for community PRs |

---

## 9. Timeline and Milestones

### Current State (v2.3.0)

- [x] Core YAML flow engine with 43+ commands
- [x] Android driver (gRPC + UIAutomator)
- [x] iOS driver (XCTest + HTTP)
- [x] Web driver (Selenium)
- [x] Maestro Studio (React + Ktor)
- [x] AI-powered assertions (Claude, GPT)
- [x] CLI with CI/CD output formats
- [x] Smart element selectors (positional, trait-based)
- [x] JavaScript evaluation (GraalVM + Rhino)
- [x] Variable system and flow composition

### Future Roadmap (Potential)

**Phase: Expansion**
- [ ] Enhanced AI testing capabilities (visual regression, auto-healing selectors)
- [ ] Expanded web platform support
- [ ] Performance testing integration
- [ ] Network mocking and interception
- [ ] Improved multi-device orchestration
- [ ] Plugin/extension system for community contributions

---

## 10. Open Questions and Assumptions

### Open Questions

1. **AI provider strategy**: Should Maestro standardize on one AI provider or maintain multi-provider support long-term?
   - Options: Single provider (simpler), multi-provider (resilient), bring-your-own-model
   - Recommendation: Multi-provider with a default

2. **Web platform investment level**: How much should web driver capabilities be expanded vs. focusing on mobile?
   - Context: Selenium dependency adds complexity; web testing has strong existing tools

3. **Plugin architecture**: Should Maestro support community plugins for custom commands and drivers?
   - Impact: Would enable extensibility but adds maintenance burden

### Assumptions

1. Users have Android SDK / Xcode installed for respective platform testing
2. Devices/emulators/simulators are pre-configured and accessible via ADB / Xcode
3. AI features require users to provide their own API keys
4. Network connectivity available for AI features and Maestro Cloud
5. Java 17+ runtime available on host machine

### Out of Scope

1. **Native desktop app testing** (macOS, Windows, Linux desktop apps) - Not in current roadmap
2. **Load / performance testing** - Maestro is for functional UI testing
3. **API-only testing** - Maestro focuses on UI; API testing tools exist
4. **Test management / reporting dashboard** - Handled by Maestro Cloud (commercial)
5. **Device farm management** - Handled by Maestro Cloud

---

## 11. Resources and Team

### Repository

- **Codebase:** Kotlin multi-module Gradle project
- **Modules:** 16+ modules (CLI, client, orchestra, drivers, studio, AI, utils, proto, tests)
- **License:** Open-source (CLI and libraries)
- **Commercial:** Maestro Studio (desktop app), Maestro Cloud (SaaS)

### Distribution

| Channel | Format |
|---------|--------|
| Install script | `curl get.maestro.mobile.dev` |
| Homebrew | Tap-based installation |
| Native installers | macOS, Windows, Linux |
| Shadow JAR | Self-contained executable |

---

## 12. Change Log

| Date | Version | Changes | Author |
|------|---------|---------|--------|
| 2026-03-26 | 1.0 | Initial PRD generated from source code analysis | Claude |
