# Plan: Facebook Crawl Stability

> Created: 2026-04-18
> Scope: narrow — fix flaky FB post + comment extraction on Android device farm
> Out of scope: IG/TikTok/LinkedIn (see `plans/crawling-enhancement`), Redis queue, anti-detection rotation
> Branch suggestion: `fix/fb-crawl-stability`

---

## Problem Statement

User report: "bài lấy được, bài không lấy được" — FB post + comment crawl unstable. Some posts extract, some do not. Same scenario, same device, random failure.

**Three possible failure layers (must rule out device layer first):**

1. **Device layer** — scrcpy disconnect, u2 session death, a11y service loss, ADB reconnect mid-run. `agent-boot-stability` (shipped 2026-04-17) may already fix some of this; Phase -1 runs one flake with full instrumentation to confirm.
2. **Parser silently returns empty / drops posts** — `tasks/fb_extract.py` (2412 LOC) depends on hardcoded Vietnamese strings, screen-geometry heuristics, and bounds assumptions.
3. **Scenario engine extracts from stale/partial UI** — `tasks/scenario/` step engine scrolls, taps, and dumps UIAutomator XML with fixed sleeps. No wait-for-stable-frame after scroll. Extraction runs against half-rendered viewport. Truncated/partial posts accepted into context.

**Phase -1 gates the rest**: if device layer owns the flake, this plan is cancelled and work goes into `agent-boot-stability`. Layers 2+3 may be fully or partly bypassed based on evidence.

---

## Root Causes (with file:line evidence)

### Parser (`tasks/fb_extract.py`)

| # | Cause | Evidence |
|---|-------|----------|
| P1 | Comment anchor resolution single-point: `_resolve_comment_region_anchors` requires "Bình luận" literal match; miss → returns `(None, None, None)` → every node filtered out → `[]` | fb_extract.py:1912, 1933, 1943, 1990-2001, 2003 |
| P2 | Post cluster dropped when no author AND no body, even if stats/timestamp present | fb_extract.py:954-955 |
| P3 | Body text silently zeroed if matches `_NOISE_PREFIXES` / `_NOISE_CONTAINS` (over-broad filter) | fb_extract.py:109-141, 947-950 |
| P4 | Feed-container XPath requires `RecyclerView[@scrollable="true"]` OR `StaggeredGridLayoutManager[@scrollable="true"]` OR `ListView`; fallback uses `max(containers, key=len)` — may pick wrong container silently | fb_extract.py:169-173, 638-644 |
| P5 | `_RE_TS` timestamp regex + `_MAX_TS_ANCHOR_NODE_LEN = 96` → long or non-matching timestamps break post anchor → body keeps appending past delimiter | fb_extract.py:36-52, 551-567 |
| P6 | Geometry hardcoded: x ∈ [150, 64% w], y cutoff = 200/260 — tablets, narrow devices, or layout shifts fail silently | fb_extract.py:2046, 2059-2063, 2033, 2383 |
| P7 | Hardcoded VN locale strings across parser: "Bình luận", "Nút Thích bình luận của", "Ảnh đại diện của", "đã chia sẻ" | fb_extract.py:72-79, 130, 266, 1025, 1287, 1290 |
| P8 | `_is_junk_recycler_post` can drop real posts on noise heuristic false-positive | fb_extract.py:349-429, 1100-1102 |

### Scenario Engine (`tasks/scenario/`)

| # | Cause | Evidence |
|---|-------|----------|
| S1 | Frame-settle after step is fixed 800 ms + poll ≤ 1 s; on stale frame logs warning and **continues anyway** — extract reads old XML | scenario/capture.py:56-70 |
| S2 | Blind scroll: swipe × N repeats, only `pause_seconds` between (0.4–0.7s in `fb_group_crawl.json`). No wait-for-hierarchy-stable after scroll | scenario/steps/navigation.py:127-136; scenarios/fb_group_crawl.json:120, 203 |
| S3 | Extraction retries `expand_see_more` up to 4 passes, but if posts still `unresolved_after > 0`, added to ctx with missing fields | scenario/steps/extraction.py:122-161 |
| S4 | `hierarchy_xml(force_refresh=False)` in extraction path — may return cached pre-scroll hierarchy | scenario/steps/extraction.py:63 |
| S5 | `stop_if_no_new` counts "added==0" — but added can be 0 because parser silently dropped posts (P1-P3), not because feed exhausted → loop exits early, misses real posts | scenario/steps/extraction.py:178-188 |
| S6 | Executor aborts scenario on first failed step; no per-step retry with backoff | scenario/executor.py:157-158 |
| S7 | Post bounds resolved at step start, tapped later; stale bounds if FB re-renders between find and tap | scenario/utils.py:474-498 |
| S8 | Auto-save fires only if extraction `ok=True`; empty parse → nothing persisted, data lost even when UI had posts | scenario/steps/extraction.py:87-90 |

---

## Approach

Fix in this order (later phases depend on earlier):

1. **Phase -1 — Device-layer evidence** (blocker). Run 1 flake with scrcpy/u2/a11y/ADB instrumentation. Decide which layer owns it. If device layer: cancel this plan, move to `agent-boot-stability`. 2-4 hours, not days.
2. **Phase 0 — Observability (minimal)**. File-only failure bundles at `captures/_failures/<exec_id>/<ts>/` + `parse_diagnostic` tuple return from parser entrypoints + `extraction_result` structlog event. **No DB table, no API, no CLI** (cut from original; use existing captures/ dir pattern — 90% of debugging value at 10% of cost). Remaining effort: ~4h.
3. **Phase 1 — Scenario reliability**. Fresh hierarchy, wait-for-stable, reject stale-frame extract, per-step retry (**reuse tenacity already wired in agent-boot**), save-partial-on-empty, **session-death detection** (F1.8 — break + flag execution FAILED_ACCOUNT_DEAD when parser returns `reason_code=login_screen` or similar).
4. **Phase 2 — Parser resilience**. VN + EN only (cut JA/ZH until a real capture forces us). Multi-account dedup key `(execution_id, account_id)`. Geometry normalize. `_incomplete` marker scoped to content.meta only — no UI/API surface changes in this plan.
5. **Phase 3 — Regression corpus & tests**. Golden fixtures, contract tests, recall invariants. `replay_capture.py` only if existing `test_captures_parse_persist_accuracy` cannot already reproduce.
6. **Phase 4 — Resume correctness**. Checkpoint by post-persist, resume dedup seed by `(execution_id, account_id)`, cancel-preserves-state.

**Independence rule**: Phase 1 F1.1, F1.2, F1.6, F1.7 do **not** depend on Phase 0 — they can ship as a first PR immediately after Phase -1 clears, measured for impact before committing to the full Phase 0 + 2 spend.

---

## Phase Overview

| Phase | Name | Priority | Effort | Depends | Status |
|-------|------|----------|--------|---------|--------|
| -1 | Device-layer evidence pull (kill-switch gate) | P0 | 2-4h | — | Not started |
| 0 | Observability (file-only bundles + diagnostic tuple) | P0 | 4h | -1 | Not started |
| 1 | Scenario reliability + session-death detection | P0 | 2-3 days | -1 | Not started |
| 2 | Parser resilience (VN+EN, geometry, multi-account dedup) | P0 | **6-8 days** | 0 | Not started |
| 3 | Regression corpus + contract tests | P1 | 1-2 days | 1, 2 | Not started |
| 4 | Resume correctness (post-persist checkpoint, (exec,acct) dedup) | P1 | 1 day | 1 | Not started |

Total (if Phase -1 says "proceed"): **11-15 days**. Phase 1 quick-path subset (F1.1/2/6/7 + quick wins) can ship in 1 day immediately after Phase -1 for early recall lift.

---

## Dependency Graph

```
Phase -1 (Device evidence) ─── kill-switch gate
    ↓
    ├── verdict: device layer  →  cancel plan, work lives in agent-boot-stability
    └── verdict: parser/engine →  proceed
            ↓
        Phase 0 (file-only obs) ─┬─→ Phase 1 (engine) ─┐
                                 │                      ├─→ Phase 3 ─→ Phase 4
                                 └─→ Phase 2 (parser) ──┘
        (Phase 1 F1.1/2/6/7 can ship in parallel with Phase 0)
```

---

## File Ownership Matrix

| File / Module | P0 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| `tasks/scenario/capture.py` | ✏️ | ✏️ | | | |
| `tasks/scenario/executor.py` | ✏️ | ✏️ | | | |
| `tasks/scenario/steps/extraction.py` | ✏️ | ✏️ | ✏️ | | ✏️ |
| `tasks/scenario/steps/navigation.py` | | ✏️ | | | |
| `tasks/scenario/steps/wait.py` | | ✏️ | | | |
| `tasks/scenario/utils.py` | | ✏️ | | | |
| `tasks/fb_extract.py` | ✏️ diag hooks | | ✏️ | | |
| `tasks/base_extract.py` | | | ✏️ | | |
| `services/content_store.py` | | ✏️ save-partial | | | |
| `db/crud/execution.py` | ✏️ failure bundle ref | | | | ✏️ checkpoint-by-post |
| `db/migrations/` | ✏️ new: failure_bundles | | | | |
| `tests/test_fb_extract_progressive.py` | | | | ✏️ | |
| `tests/test_captures_parse_persist_accuracy.py` | | | | ✏️ | |
| `tests/test_scenario_retry.py` (new) | | | | ✏️ new | |
| `captures/_golden/` (new dir) | | | | ✏️ seed | |

---

## Quick Wins (< 1 day, ship as one PR after Phase -1 clears)

1. **Force-refresh XML in extraction step** — flip `hierarchy_xml(force_refresh=True)` in `steps/extraction.py:63`. **30 min**. Measure frame_age + u2 health before/after (Phase -1 instrumentation must confirm this doesn't thrash a11y).
2. **Wait-for-stable-hierarchy after scroll** — insert `wait_stable` in `fb_group_crawl.json` (~4 locations). **30 min**.
3. **Per-empty-parse XML dump to `captures/_failures/`** — env `FB_CAPTURE_FAILURES=1`, cap N=50 per execution. **45 min**.
4. **Locale widening (VN+EN only)** — `{"bình luận", "comment", "comments"}` tuple match at `fb_extract.py:1912, 1933`. Validate against existing corpus — reject if it changes baseline post count on any golden XML. **1 hr**.
5. **Save partial posts on empty return** — `extraction.py:87-90` — flush `ctx["posts"]` via `content_store.save_batch_idempotent` even when current step yields nothing. **1 hr**.
6. **Stop-if-no-new only counts `reason_code="ok"`** — gate at `extraction.py:178-188` (requires tiny diagnostic shim from Phase 0). **30 min**.

**Acceptance of Quick Wins**: one run on test group with recall diff logged. If recall doesn't move ≥ 10 pp vs baseline → don't invest in Phase 0+2 yet; re-read Phase -1 evidence.

---

## Acceptance Criteria

**Measurement note**: end-to-end recall "UI visible vs DB persisted" requires a ground-truth oracle we do not have. Practical proxies:
- **Diff-of-runs recall**: run the same scenario twice on same group + account within 1 hour; posts unique to run A but missing in run B ≠ 0 means at least one run dropped posts. Target: ≤ 5% asymmetric drops.
- **Golden replay**: parser-on-fixed-XML, measured in Phase 3. Target: 100% invariant match.
- **Failure ratio**: `failure_bundles` (file count) / `executions` → baseline now, target ≥ 70% reduction.

A "stable" crawl =
- Diff-of-runs recall ≥ 95% on test group.
- **Zero silent empty-parse** on valid XML; every empty parse carries a `reason_code` in logs.
- **Partial posts always saved** before scenario abort.
- **Session-death detected** within 2 scroll iterations and flagged (execution status → `FAILED_ACCOUNT_DEAD`), not silently retried.
- **Comment extraction**: ≥ 80% of visible comment rows persisted on known-good captures.
- Regression suite: every captured failure XML becomes a test case.

---

## Phase Files

- [Phase -1: Device-Layer Evidence](phase-minus-1-device-evidence.md) — **gate; run first**
- [Phase 0: Observability (minimal)](phase-00-observability.md)
- [Phase 1: Scenario Engine Hardening + Session-Death Detection](phase-01-scenario-hardening.md)
- [Phase 2: Parser Resilience](phase-02-parser-resilience.md)
- [Phase 3: Regression Corpus & Tests](phase-03-regression-tests.md)
- [Phase 4: Resume Correctness](phase-04-resume-correctness.md)

---

## Risks & Tradeoffs

| Risk | Mitigation |
|------|------------|
| Force-refresh XML slower per step (~200-500ms) | Accept — correctness > throughput for crawl |
| Wait-for-stable adds latency | Bound by `wait_stable` max-timeout (5s); if timeout hit, log + continue |
| Parser widening (multi-locale) may introduce false positives (matching wrong buttons) | Each locale string must be tested against corpus; reject if it increases junk post count |
| Save-partial may persist posts with `caption=null` | Flag in `content.meta.parse_diagnostic` so downstream can filter or re-crawl |
| Corpus tests grow large | Keep golden XML gzipped; test selects by manifest not by glob |

---

## Out of Scope (deferred)

- IG / TikTok / LinkedIn parsers → existing `plans/crawling-enhancement` phase 3
- Redis task queue, anti-detection pool, bloom dedup → crawling-enhancement phases 1, 2, 5
- LLM universal extractor → crawling-enhancement phase 4
- OCR / ai_vision improvements
- Account rotation / cooldown beyond current `services/account_manager.py`
