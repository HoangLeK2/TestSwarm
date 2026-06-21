# Phase 2 - Policy And UI Semantics

Status: Done
Priority: P1
Effort: 2h

## Objective

Make backend validation and frontend labels match the new runtime semantics so operators understand that recovery can repeat per incident while a global safety cap still exists.

## Related Files

- `/Users/hoangle/farm/device-farm/device_farm/services/execution/recovery_policy.py`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/lib/recovery-policy-editor-model.ts`
- `/Users/hoangle/farm/device-farm/front-end/src/features/campaigns/components/recovery-policy-editor.tsx`
- `/Users/hoangle/farm/device-farm/front-end/messages/vi.json`
- `/Users/hoangle/farm/device-farm/front-end/messages/en.json`

## Policy Decisions

Recommended semantics:

- `rule.max_attempts`: maximum recovery attempts for one incident matched by that rule.
- `max_attempts_per_step`: maximum recovery attempts for one failed step execution incident.
- `max_total_attempts`: maximum recovery attempts for the whole scenario run.

For loop-heavy campaigns, the current default `max_total_attempts=8` can still stop recovery after eight total incidents. Update this deliberately instead of hiding it:

- Backend default: raise from `8` to `100` for new policies.
- Backend max: raise from `100` to `10000`.
- Frontend: show `max_total_attempts` as "Tong so lan va loi toi da trong mot lan chay" / "Total recovery safety cap per run".
- Frontend: show rule attempts as "Moi lan loi" / "Per incident".

If the product wants truly unlimited recovery, model that later as an explicit opt-in value such as `0 = unlimited`, but do not add unlimited behavior in this fix.

## Implementation Steps

1. Run GitNexus impact analysis before changing `parse_recovery_policy`.
2. Update policy defaults and clamps in `recovery_policy.py`.
3. Update frontend policy editor model clamps to match backend values.
4. Update Vietnamese and English labels so users can distinguish per-incident caps from the total safety cap.
5. Keep generated API types unchanged unless schema values or names change.

## UX Notes

The UI should communicate two separate controls:

- Per incident: how many times the system can try to fix the same failure.
- Whole run: the safety cap that prevents a broken 999999-loop campaign from recovering forever.

Do not add a new graph node, modal, or workflow type for this change.

## Success Criteria

- New campaign recovery policies are suitable for long loops by default.
- Existing campaigns keep their saved policy values.
- Operators can tell why recovery stopped: per-incident cap versus total run cap.

## Completed

- Raised backend `max_total_attempts` default to `100` and max clamp to `10000`.
- Frontend editor now preserves `max_total_attempts` and `max_attempts_per_step`.
- UI labels distinguish per-incident attempts from the total run safety cap.
