# WVR-12 — Temporary single-device acceptance waiver

## Decision

Status: `ACTIVE`  
Authorized by: product owner instruction in the working session  
Effective date: `2026-10-04`  
Scope: implementation, automated verification, integration QA and local/staging acceptance for ADL-01…21.

While this waiver is active, one healthy Approved Device Target is sufficient for device-execution acceptance. The target may be a physical Android device or an isolated Android Emulator under the Approved Device Target contract.

## Invariants that remain

- The product model keeps 12 logical lanes, 14 service days and 168 planned slots. No migration, API or scheduler may hard-code the temporary capacity of one.
- Reservation remains atomic for the requested cohort size. Tests for 12-or-zero allocation, overlap exclusion, quota and bounded concurrency remain mandatory.
- One emulator cannot impersonate 12 simultaneous devices. Evidence must report `observed_device_count=1` and `capacity_waiver=WVR-12`.
- Multi-device load results are `WAIVED`, not fabricated or inferred from sequential replay.
- Play-account continuity, provider/payment, private storage, independent review, real-time 14-day chronology and deployment/recovery gates are outside this waiver.

## Task interpretation

Any acceptance item whose only unmet condition is “12 devices/phones/targets” may pass with one Approved Device Target plus WVR-12 evidence. Functional correctness, tenant isolation, failure handling, recovery, capture integrity and performance observations still have to pass. A `PHYSICAL_ONLY` test remains physical-only.

## Exit

The waiver expires when the product owner revokes it or before a release claims measured 12-device production capacity. Removing the waiver requires a 12-instance rehearsal; it does not require redesigning the domain model.
