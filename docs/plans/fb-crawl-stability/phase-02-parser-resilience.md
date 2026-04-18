# Phase 2 — Parser Resilience

> Goal: stop silent empty returns and silent post drops in `fb_extract.py`. Widen anchor matching, normalize geometry, and surface every drop via the diagnostic schema from Phase 0.
> Effort: **6-8 days** (revised up from 3-4 after red-team — 2412 LOC parser + 8 semantic fixes + geometry cascade across every test fixture is not 3 days)
> Priority: P0
> Depends: Phase 0 (diagnostic plumbing)

---

## Guiding Principle

Every empty return and every dropped post must carry a reason. Today the parser answers "nothing here" to too many legitimate screens. We do not rewrite the parser — we widen its fallbacks and replace silent drops with diagnostic exits that upstream code can react to.

---

## Fixes

### F2.1 — Locale-agnostic anchor token tables

**Problem (P1, P7)**: Hardcoded `"Bình luận"` literal matches at `fb_extract.py:1912, 1933` and elsewhere. If the device locale is English, or FB renames the button, anchor resolution returns `(None, None, None)` → every comment silently filtered.

**Fix**: Introduce `_LOCALE_TOKENS` module constant at top of `fb_extract.py`:

```python
# Keep to VN + EN only. JA/ZH cut until a real capture forces the addition
# (red-team: dead weight tokens inflate false-positive risk).
_LOCALE_TOKENS = {
    "comment_button": {
        "bình luận", "binh luan",            # VN
        "comment", "comments",                # EN
    },
    "like_button_prefix": {
        "nút thích bình luận của",           # VN
        "like comment by",                    # EN
    },
    "reshare_prefix": {
        "đã chia sẻ", "shared",
    },
    "avatar_prefix": {
        "ảnh đại diện của", "profile picture of",
    },
}

def _token_hit(text: str, key: str) -> bool:
    t = text.casefold().strip()
    return any(tok in t for tok in _LOCALE_TOKENS[key])
```

Replace every literal string match at lines 72-79, 130, 266, 1025, 1287, 1290, 1912, 1933 with `_token_hit(...)`. Keep compiled regex where it's already regex — just widen the alternatives.

Add `locale_tokens_hit: list[str]` to the diagnostic (e.g. `["comment_button:vn"]`) so we can see in logs which locale carried the feed.

### F2.2 — Feed container fallback

**Problem (P4)**: Feed-container XPath is strict on `@scrollable="true"`; fallback picks largest node by length, which may be a navigation bar or header.

**Fix**: In `_pick_feed_container` (line 638):
- Keep current scoring.
- If best score is below threshold (say 0.3), also emit `reason_code = "no_feed_container"` in diagnostic rather than returning arbitrary max-length container.
- New heuristic: require chosen container to contain ≥ 2 distinct child clusters with timestamp-anchor pattern OR author-hint resource-id. If neither, abstain (return None) and let upstream show `reason_code`.

### F2.3 — Screen-normalized geometry bounds

**Problem (P6)**: Hardcoded x ∈ [150, 64% w] and y cutoffs at 200/260 pixels fail on tablets and on devices with different DPI.

**Fix**: Replace literal pixel thresholds with screen-relative:
```python
# _infer_screen_size already exists at line 598
sw, sh = _infer_screen_size(root)
COMMENT_X_MIN = max(80, int(0.10 * sw))
COMMENT_X_MAX = max(380, int(0.72 * sw))  # slightly wider than 64%
HEADER_Y_CUTOFF = int(0.12 * sh)          # was 200/260 flat
TOOLBAR_Y_CUTOFF = int(0.08 * sh)
```

Audit every occurrence of `200`, `260`, `150`, `380`, `64%` at lines 2033, 2046, 2059-2063, 2383 and replace with `sh/sw`-scaled.

### F2.4 — Post kept if author OR body OR (timestamp + stats)

**Problem (P2)**: `_extract_post` returns `None` when no author AND no body, even if timestamp + stats + media present.

**Fix**: Change drop condition at lines 954-955 to:
```python
if not author and not body and not (ts_anchor and stats):
    diagnostic_drop("empty_cluster_no_signal")
    return None
```
If any one of (author, body, ts+stats triple, media artifacts) is present, keep the post with an explicit `_incomplete: true` marker in the return dict. Downstream save-partial (phase 1 F1.4) will persist with `parse_diagnostic` attached so operator can requeue.

### F2.5 — Junk filter is last-resort only

**Problem (P8)**: `_is_junk_recycler_post` at line 349 drops posts that match multiple heuristic patterns; false positives happen.

**Fix**: Split into two tiers:
- **Hard junk** (drop silently): has_ad_container=True OR all-noise-text cluster. Keep current behavior.
- **Soft junk** (keep + flag): heuristic pattern match without hard-ad signal → return post with `_soft_junk: true` + `_soft_junk_reason: "..."`. Count in diagnostic as `soft_junk_count` but do not remove.

Lets operator verify via failure bundles that we're not dropping real posts; tune from there.

### F2.6 — Body noise filter tightened

**Problem (P3)**: `_NOISE_PREFIXES`/`_NOISE_CONTAINS` zeroing out body text at lines 947-950 can wipe the caption if it happens to start with or contain a noise marker.

**Fix**: Apply noise filter only to **individual text nodes**, not to the concatenated body. Today a caption "theo dõi trang này để..." gets zeroed because it starts with a noise prefix; after fix, only the one-liner "Theo dõi" as its own node gets dropped, caption survives.

### F2.7 — Comment clustering gap is density-adaptive

**Problem (P6, hardcoded 80px at line 1652)**:

**Fix**: Compute gap threshold from the screen height and the median inter-node gap of the comment region. Instead of fixed `80`:
```python
median_gap = statistics.median(gaps_in_region) if gaps_in_region else 80
cluster_gap_px = max(60, int(min(160, median_gap * 1.8)))
```
Keeps fast path on dense feeds, loosens on sparse feeds.

### F2.8 — Parser expected-errors return diagnostic; programming errors raise

**Red-team caveat**: `try/except Exception` swallows legit bugs. Split:

- **Expected parse issues** (XML malformed, anchor missing, empty text nodes, cluster empty) — return `([], diagnostic)` with the appropriate `reason_code`. These are data quality issues the scenario engine handles via retry.
- **Programming errors** (AttributeError on wrong type, KeyError on missing internal dict key, IndexError on bad slice) — let them raise. Phase 1 F1.8 treats a raised exception as `reason_code=parser_exception` at the scenario layer, captures a bundle, and surfaces the traceback. Fail loud, don't mask.

Practical line: the outer `try` catches `(ET.ParseError, XMLSyntaxError, ValueError-we-know-we-throw)`. Everything else bubbles.

---

## Steps

Revised bottom-up estimate (red-team: 3-4 days was fantasy):

1. **Set up `_LOCALE_TOKENS`** + helper (~2h).
2. **Swap literal matches → `_token_hit`** across all locations + corpus validation per token set (~6h).
3. **Drop-condition fix (F2.4)** and thread `_incomplete` through save + content.meta (~4h).
4. **Feed container threshold abstain (F2.2)** (~2h).
5. **Screen-normalized bounds (F2.3)** — audit + refactor + **regenerate affected golden fixtures** (~1-1.5 days — this is the real time sink).
6. **Soft-junk split (F2.5)** (~4h).
7. **Noise-per-node fix (F2.6)** (~4h).
8. **Adaptive comment gap (F2.7)** — requires a corpus of sparse + dense feeds; if not present, defer to Phase 3 after more captures (~4h or skip).
9. **Try/except split (F2.8)** — narrow exception list, not blanket (~1h).
10. **Regression corpus pass** — run all existing parser tests + new goldens; zero unexplained regressions (~4h).

---

## Acceptance

- [ ] `test_fb_extract_progressive.py` + `test_captures_parse_persist_accuracy.py` + `test_captures_hierarchy_corpus.py` — all green, zero regressions.
- [ ] On English-locale FB screenshot (manual capture), comment anchor resolves; comments persist.
- [ ] No post in corpus dropped with only `reason_code = "empty_cluster_no_signal"` where manual inspection shows author+ts.
- [ ] All parser calls carry `diagnostic.reason_code`.
- [ ] Parser raises no uncaught exceptions across corpus (fuzz with 100 captures).
- [ ] On test group run (with phase 1 shipped), recall ≥ 95% over 10 consecutive scenarios.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Widening anchor tokens matches irrelevant UI (e.g. "Comments" in notification badge) | Every token addition must be run against corpus; reject if it changes baseline post count |
| Screen-normalized bounds change behavior on legacy captures in golden tests | Recompute goldens deliberately; mark in CHANGELOG of test fixtures |
| `_incomplete: true` posts clutter DB | Filter in API responses by default; add `?include_incomplete=1` query flag |
| Soft-junk posts bloat content table | Dedupe via `content_hash`; monitor row-count over 7 days |
