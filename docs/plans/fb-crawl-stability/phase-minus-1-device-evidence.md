# Phase -1 — Device-Layer Evidence Pull

> Goal: rule out (or confirm) that the flake is a lower-layer problem — scrcpy desync, u2 session death, a11y service loss, ADB reconnect — **before** refactoring 2412 LOC of parser and engine.
> Effort: 2-4 hours (not days)
> Priority: P0 blocker on every other phase
> Rationale: "same device, random failure" is the literal signature of a dying session. The recently-shipped `agent-boot-stability` work (heartbeat, stay_on, supervisor, per-serial breaker) may have already moved the needle; or the flake may live entirely at the device layer and zero code changes are needed in `fb_extract.py` / scenario engine.

---

## Task

Run one known-flaky crawl run with full instrumentation. Pull logs. Decide.

### Instrumentation

1. **Agent-boot relay logs**
   - `scrcpy_relay.py` — look for `on_fatal`, `window-based retry`, `frame_timeout` warnings
   - `u2_session_pool.py` — heartbeat failures, reconnect events, `.alive` timeouts
   - `session_manager.py` — TTL evictions, `stop_all_for_serial` calls
   - `supervisor.py` — breaker open/close events
2. **Bootstrap a11y service state** — confirm `stay_on_while_plugged_in=3` survived, accessibility whitelist intact at run start and at flake moment.
3. **ADB reconnect count** — grep for `adbd reconnect`, `ConnectionRefusedError`, `device offline`.
4. **Device-side**: on at least one flake-reproducing device, `adb shell dumpsys activity service accessibility` at flake moment; check u2 atx-agent is still alive (`adb shell pgrep atx-agent`).
5. **Scenario-level** structured log: add one-line `structlog` event on every extract step with `xml_bytes`, `frame_age_ms`, `u2_heartbeat_age_ms` (read-only — don't change extraction behavior).

### Data capture

Manually run `fb_group_crawl` scenario on a device that historically flakes. Keep all logs. Save the 10 last UIAutomator XML dumps + screenshots from `captures/`. Identify which scroll iteration dropped posts.

### Decision gate

| Observation | Verdict | Next step |
|---|---|---|
| Scrcpy fatal callback fired during flake OR frame_age > 5s | Device layer root cause — kick to `agent-boot-stability` followup | Drop Phases 1-4, open issue against `agent-boot` |
| U2 heartbeat stale / reconnect near flake | Device layer | Same — `agent-boot` fix, not parser fix |
| A11y service dropped mid-run | Device layer | Same |
| Device-layer healthy + XML has posts but parse returns `[]` | Parser bug confirmed | Proceed with Phase 0 + 2 |
| Device-layer healthy + XML has NO posts but UI had them | Capture/timing bug | Proceed with Phase 1 (fresh-frame, wait-stable) |
| Device-layer healthy + XML had login screen | Session-death mid-run | Add F1.8 detection to Phase 1, skip parser work on that capture |

### Output artifact

`docs/plans/fb-crawl-stability/evidence.md` — short report:
- Flake timestamp + execution_id
- Which layer owned the failure
- Which phase(s) of this plan actually need to ship (may be 0)
- Links to captured XML + log excerpts

---

## Acceptance

- [ ] At least one reproduced flake has a written verdict per the decision gate above.
- [ ] `evidence.md` committed.
- [ ] Phases 0-4 re-scoped based on findings, or plan cancelled if device-layer fix already resolves it.

---

## Risks

| Risk | Mitigation |
|------|------------|
| Flake not reproducible on staged instrumented run | Instrument prod crawl for 24h; lower sample rate to avoid log spam |
| Evidence shows device-layer cause **and** parser cause — both matter | Ship `agent-boot` fix first; re-measure; then decide if parser work still worth it |
| Takes longer than 4h | Cap at 1 day; if no flake in 1 day, accept parser hypothesis and proceed with Phase 0 narrow |
