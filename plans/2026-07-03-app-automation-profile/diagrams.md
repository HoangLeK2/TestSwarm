# App Automation Profile Diagrams

## Recommendation

Use Mermaid for this phase.

- Mermaid: best for repo docs, architecture review, PR diff, and iterative design.
- Draw.io: better later for polished stakeholder diagrams or UI-heavy documentation.

## System Architecture

```mermaid
flowchart TB
  User[User / Campaign Builder] --> FE[Frontend Flow Editor]
  FE --> API[Scenario API + Validation]
  API --> Profile[AppAutomationProfile Contract]
  Profile --> Runner[Scenario Runtime]

  Runner --> Watcher[Popup Watcher Evaluator]
  Runner --> Locator[Semantic Locator Resolver]
  Runner --> Steps[Scenario Step Dispatcher]

  Watcher --> Snapshot[HierarchySnapshot]
  Locator --> Snapshot
  Snapshot --> U2XML[u2 Hierarchy XML]

  Steps --> U2[u2 Executor]
  U2 --> Device[Android App]

  Runner --> Events[Execution Events]
  Events --> Monitor[Campaign Monitor]
  Runner --> Artifacts[Screenshot / XML / Locator Trace]
  Artifacts --> Monitor
```

## Runtime Flow

```mermaid
sequenceDiagram
  participant C as Campaign Runtime
  participant P as AppAutomationProfile
  participant D as DeviceClient/u2
  participant S as HierarchySnapshot
  participant W as Watcher Evaluator
  participant L as Locator Resolver
  participant M as Monitor

  C->>P: Load profile for package
  C->>D: Capture hierarchy XML
  D-->>C: XML + package/activity/screen
  C->>S: Build snapshot once

  C->>W: Evaluate popup watchers
  W-->>C: 0..1 watcher trigger
  alt watcher matched
    C->>D: Execute safe watcher action
    C->>M: Emit watcher event
    C->>D: Refresh hierarchy XML
    C->>S: Rebuild snapshot
  end

  C->>L: Resolve semantic locator
  L-->>C: selector/bounds/score/reason
  alt selector resolved
    C->>D: Tap/input by selector
  else explicit coordinate fallback
    C->>D: Tap by bounds center
  else ambiguous or low score
    C->>M: Emit failed locator trace
  end

  C->>M: Emit step result + artifacts
```

## Locator Decision Tree

```mermaid
flowchart TD
  Start[Resolve locator name] --> Exists{Locator exists?}
  Exists -- No --> FailUnknown[Fail: unknown locator]
  Exists -- Yes --> Snapshot[Use HierarchySnapshot]

  Snapshot --> Exact{Exact by/value match?}
  Exact -- Yes --> Stable[Return stable selector]
  Exact -- No --> Rid{resource_id_contains?}
  Rid -- Yes --> Stable
  Rid -- No --> TextNear{text_near + target_class?}

  TextNear -- Yes --> Score[Score nearby target nodes]
  TextNear -- No --> Other[description/class/region filters]
  Other --> Score

  Score --> Min{score >= min_score?}
  Min -- No --> FailLow[Fail: below min_score]
  Min -- Yes --> Ambig{ambiguous?}
  Ambig -- Yes --> FailAmbig[Fail: ambiguous candidates]
  Ambig -- No --> Selector{stable selector exists?}

  Selector -- Yes --> Stable
  Selector -- No --> Coord{allow_coordinate_fallback?}
  Coord -- Yes --> Bounds[Return bounds fallback]
  Coord -- No --> FailNoSelector[Fail: no executable selector]
```

## Popup Watcher Safety Flow

```mermaid
flowchart TD
  Step[Before/After Scenario Step] --> Scope{Package/activity/screen scope matches?}
  Scope -- No --> Skip[Skip watcher]
  Scope -- Yes --> Enabled{Watcher enabled?}
  Enabled -- No --> Skip
  Enabled -- Yes --> Budget{Cooldown and max trigger ok?}
  Budget -- No --> Skip
  Budget -- Yes --> Parse[Use or build HierarchySnapshot]

  Parse --> Match{Condition matches XML?}
  Match -- No --> Skip
  Match -- Yes --> Unsafe{Unsafe action?}
  Unsafe -- Yes --> Explicit{allow_unsafe true?}
  Explicit -- No --> Block[Blocked by validation]
  Explicit -- Yes --> Trigger[Return trigger metadata]
  Unsafe -- No --> Trigger

  Trigger --> One[Default: one trigger per evaluation]
  One --> Log[Emit watcher event to monitor]
```

## Implementation Roadmap

```mermaid
gantt
  title App Automation Profile Rollout
  dateFormat  YYYY-MM-DD
  axisFormat  %m-%d

  section Foundation
  Plan and scout                     :done, p1, 2026-07-03, 1d
  Profile contract                   :active, p2, 2026-07-03, 1d
  Locator resolver                   :active, p3, 2026-07-03, 1d
  Watcher evaluator                  :active, p4, 2026-07-03, 1d

  section Runtime Wiring
  Scenario schema step types         :p5, after p4, 2d
  Execute_step_with_retry watcher hook :p6, after p5, 2d
  Login and form-fill steps          :p7, after p6, 2d

  section Observability
  Monitor event payload              :p8, after p7, 1d
  Frontend monitor rendering         :p9, after p8, 1d

  section Quality
  Performance benchmarks             :p10, after p9, 1d
  Subagent review and live smoke      :p11, after p10, 1d
```
