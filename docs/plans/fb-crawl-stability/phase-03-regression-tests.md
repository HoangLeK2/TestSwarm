# Phase 3 — Regression Corpus & Contract Tests

> Goal: lock down the behavior fixed in phases 1+2 so FB's next redesign triggers a red test, not a silent recall drop.
> Effort: 1-2 days
> Priority: P1
> Depends: Phases 1 + 2

---

## Deliverables

### D3.1 — Golden fixture corpus

**Directory**: `device_farm/tests/fixtures/fb_captures/_golden/`

Structure:
```
_golden/
  manifest.yaml                   # one entry per capture
  post_vn_basic_01/
    hierarchy.xml.gz
    screen.jpg
    expected_posts.json           # {count, sample_fields}
    expected_diagnostic.json      # {reason_code: "ok", ...}
  post_en_basic_01/
  post_empty_feed_01/             # reason_code: "no_candidates"
  comment_vn_basic_01/
  comment_en_basic_01/
  comment_anchor_missing_01/      # reason_code: "anchor_not_found"
  tablet_layout_01/               # verifies F2.3 geometry normalization
  ...
```

Seed from:
- `device_farm/captures/49c62ff79ec0c35d_*` (existing live captures)
- Any `failure_bundles` produced during Phase 0 smoke tests
- Hand-crafted minimal XMLs for each `reason_code`

Gzip the XMLs (saves ~85% on repo size). Include `expected_posts.json` with only the invariant fields (content_hash, author, is_fb_post_truncated flag) — not the full post, to keep fixtures stable across minor parser tweaks.

### D3.2 — Contract test: every `reason_code` has at least one fixture

File: `device_farm/tests/test_parser_diagnostics_contract.py`

```python
@pytest.mark.parametrize("reason_code", [
    "ok", "xml_parse_error", "no_feed_container", "no_candidates",
    "all_filtered_junk", "anchor_not_found", "no_text_nodes", "empty_cluster",
    "parser_exception",
])
def test_reason_code_has_fixture(reason_code, golden_manifest):
    fixtures = [f for f in golden_manifest if f["expected_reason_code"] == reason_code]
    assert fixtures, f"no fixture covers reason_code={reason_code}"
```

Forces us to capture a representative XML for every documented failure mode.

### D3.3 — Recall invariant test

File: `device_farm/tests/test_parser_recall_invariant.py`

For every golden capture with `expected_posts.count >= N`, assert the parser returns ≥ N posts **with no drop in `reason_code = "ok"`**:

```python
def test_recall_no_regression(fixture):
    posts, diag = parse_fb_posts_from_xml(load_xml(fixture))
    assert diag["reason_code"] == fixture["expected_diagnostic"]["reason_code"]
    assert len(posts) >= fixture["expected_posts"]["count"]
    # field-level invariants
    for p in posts:
        if p.get("_incomplete"):
            continue  # partial posts excluded from field check
        assert p.get("author") or p.get("body"), "post has no author and no body"
```

### D3.4 — Scenario retry contract test

File: `device_farm/tests/test_scenario_retry.py`

Mock `device.hierarchy_xml` to return stale frames for the first 2 calls then a fresh frame. Assert:
- Extraction step retries up to `retry.attempts` (F1.5).
- On success after retry, step result `ok=True`, emits `step_retry` log event twice.
- On stale-frame-error-always, bundle is captured via Phase 0 hook.

### D3.5 — Save-partial integration test

File: `device_farm/tests/test_save_partial.py`

- Run a scenario where extraction step 1 yields 5 posts, step 2 raises exception.
- Assert all 5 posts from step 1 are in DB after exception.

### D3.6 — Replay CLI

File: `device_farm/scripts/replay_capture.py`

```bash
python -m scripts.replay_capture path/to/hierarchy.xml --posts  # prints diagnostic + posts
python -m scripts.replay_capture <bundle_id> --from-db          # pulls from failure_bundles
```

Used by operator to reproduce a field failure on their laptop without needing the device.

### D3.7 — CI gate

Extend `pyproject.toml` test command to include these new files; ensure they run on every PR. Add a marker `@pytest.mark.corpus` for slow-corpus suite so developers can skip locally when iterating.

---

## Steps

1. **Build manifest + copy captures** to `_golden/` + gzip (~2h).
2. **Hand-craft edge-case XMLs** (empty feed, missing anchor, tablet layout) — 5-8 files (~2h).
3. **Write D3.2 + D3.3 tests** (~2h).
4. **Scenario retry + save-partial integration tests** (~2h).
5. **Replay CLI** (~1.5h).
6. **CI wiring** (~30min).

---

## Acceptance

- [ ] ≥ 15 golden captures in `_golden/`, covering every `reason_code` plus VN+EN locales plus tablet + phone layouts.
- [ ] `test_parser_diagnostics_contract.py` green.
- [ ] `test_parser_recall_invariant.py` green on every fixture.
- [ ] `test_scenario_retry.py` + `test_save_partial.py` green.
- [ ] `replay_capture.py` works against both a local file and a bundle_id (requires Phase 0 + 1 shipped).
- [ ] CI runs corpus suite on PR; failure blocks merge.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Corpus grows large | gzip; cap at ~100 fixtures; rotate stale ones annually |
| Fixtures drift from production UI over time | Failure bundles automatically feed new captures; monthly audit |
| Over-fitting to fixtures blocks legitimate parser improvements | `expected_posts.json` only asserts invariants (counts, hashes, `_incomplete` flags), not full field contents |
