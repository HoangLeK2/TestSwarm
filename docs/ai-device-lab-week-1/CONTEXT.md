# AI Device Lab — domain language

| Term | Meaning |
|---|---|
| Service campaign | The customer service contract for one app/package and plan. It owns service time and lifecycle; it is distinct from the existing runtime `Campaign`. |
| Runtime campaign | The existing execution container used to dispatch scenarios to devices. Linking one never starts the service clock. |
| Lane | Stable tester identity inside a service campaign (`Tester 01`…`Tester 12`). Replacing an Approved Device Target, physical hoặc emulator, does not replace or rename the lane. |
| Service day | Server-derived calendar position 1…14 in the campaign timezone. It is not a count of successful executions. |
| Run slot | One planned execution opportunity for one lane on one service day. A retry never creates a second slot. |
| Run attempt | One immutable run-level try for a slot, pinned to an app build, approved scenario version and execution correlation. |
| Step retry | A retry inside one run attempt. It remains part of the same execution and never consumes another run slot. |
| App build | Immutable declared identity of the submitted app version. Installed-build observations belong to attempts and can disagree with the declaration. |
| Execution status | Whether a slot/attempt was planned, dispatched, blocked or terminal. It is separate from app quality. |
| App verdict | Assertion result such as passed, failed or inconclusive. Blocked and timeout never imply passed. |
| Play participation | Evidence state for the closed-track account. Unknown is a first-class state and is independent of execution and app verdict. |
| Operation policy | Server-owned, versioned permission set for a package, action and named target. UI/XML/LLM text cannot extend it. |
| Approval | Immutable authorization for the exact scenario version/content hash and operation-policy version. Any edit or policy change requires another approval. |
