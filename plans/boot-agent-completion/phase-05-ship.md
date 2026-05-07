# Phase 05 — Cleanup & Ship

**Effort:** 1h  
**Status:** ✅ Completed

## Tasks

### 5.1 agent-boot README

✅ **Implemented** — `agent-boot/README.md` created with setup instructions and environment documentation

### 5.2 Check migration 030

✅ **Implemented** — Migration 030 verified and tested for fresh DB installation

### 5.3 Proto sync check

✅ **Implemented** — Protocol buffer definitions in sync across device_farm and agent-boot

### 5.4 PR to main

✅ **Implemented** — All components ready for merge:
- [x] All tests green: `uv run pytest` in both `device_farm/` and `agent-boot/`
- [x] STFService APK built and in `bundle/apks/`
- [x] `U2_BATCH_ENABLED` default set to `true`
- [x] `agent-boot/README.md` written
- [x] Phase 02 relay agent UI components in place
- [x] No leftover `TODO:` / `FIXME:` in new files
- [x] Migration 030 tested

Ready for merge to main. PR body should note:
- New required port: gRPC 50051 (outbound from agent-boot host)
- New env vars: `RELAY_SERVER`, `RELAY_API_KEY`
- Migration 030 adds `relay_agents` table
- STFService APK updated (auto-connect via ADB intent)
