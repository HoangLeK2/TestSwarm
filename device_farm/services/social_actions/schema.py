"""Schema v1 for what a social capability node hands to the next node.

A scenario passes state between nodes through variables — `_post_scan` feeds
`social_open_commenter_from_post_match`, which feeds `_people_target`, which
gates `connection_request`. Until now the payload was whatever the Facebook
resolver happened to return, so the contract between two capability nodes was
"whatever Facebook does today". A second platform could not fill it without
copying Facebook's field names, and a change on the Facebook side could silently
change what the next node reads.

Schema v1 pins three things on every payload:

- `schema_version` — so a reader can tell which contract it is holding.
- `platform` — so a payload names the adapter that produced it instead of being
  assumed to be Facebook.
- `proof` — the evidence the decision rests on, gathered in one place. What
  `connection_request` needs to know is "was this person verified, and by what",
  and that must not be spread across whichever keys the resolver used.

Person payloads additionally carry `identity`: who this is, separate from how we
came to believe it.

**The envelope is additive.** Every key the resolver returned stays where it
was, at the top level. A run that started before this change keeps working, and
a reader that still looks at `target["verified"]` keeps reading the same value.
The readers here accept both shapes so the transition needs no flag day.

Deliberately *not* included: nothing here changes what the ledger hashes.
`stable_target()` reads only `name`, `target_type`, `target_id` and `source`
from a verified target, so adding `identity`/`proof`/`schema_version` cannot
move the idempotency key of an action already recorded.
"""

from __future__ import annotations

from typing import Any

SOCIAL_SCHEMA_VERSION = 1

# Fields that describe *who* a person target is.
_IDENTITY_KEYS: tuple[str, ...] = (
    "target_type",
    "target_id",
    "display_name",
    "name",
    "profile_url",
    "source",
    "row_text",
)

# Fields that describe *why* we believe a target or a scan result.
_TARGET_PROOF_KEYS: tuple[str, ...] = (
    "verified",
    "confidence",
    "score",
    "reason",
    "message",
    "matched_keywords",
    "matched_common",
    "selected_bounds",
    "action_bounds",
    "profile_opened",
    "comment_sheet_opened",
    "source_post_target_id",
    "candidate_count",
)

_SCAN_PROOF_KEYS: tuple[str, ...] = (
    "verified",
    "reason",
    "message",
    "target_count",
    "interacted_count",
    "liked_count",
    "commented_count",
    "candidate_count",
    "screens_scanned",
    "scrolls",
)


def _pick(payload: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: payload[key] for key in keys if key in payload}


def _merged_proof(
    payload: dict[str, Any], keys: tuple[str, ...], *, verified: bool
) -> dict[str, Any]:
    proof = _pick(payload, keys)
    proof["verified"] = verified
    existing = payload.get("proof")
    if isinstance(existing, dict):
        # A payload that already carries proof wins: it came from a producer
        # that knows the contract, and it may know more than we can infer.
        proof.update(existing)
        proof.setdefault("verified", verified)
    return proof


def content_scan_payload(
    payload: dict[str, Any] | None,
    *,
    platform: str,
) -> dict[str, Any]:
    """Wrap a `content_scan` result (`_post_scan`) in the v1 envelope."""
    source = dict(payload or {})
    actions = source.get("actions")
    return {
        **source,
        "schema_version": SOCIAL_SCHEMA_VERSION,
        "platform": str(platform or source.get("platform") or ""),
        "actions": list(actions) if isinstance(actions, list) else [],
        "proof": _merged_proof(
            source, _SCAN_PROOF_KEYS, verified=source.get("verified") is True
        ),
    }


def people_target_payload(
    payload: dict[str, Any] | None,
    *,
    platform: str,
    verified: bool | None = None,
) -> dict[str, Any]:
    """Wrap a person/post target (`_people_target`) in the v1 envelope."""
    source = dict(payload or {})
    is_verified = (
        source.get("verified") is True if verified is None else bool(verified)
    )
    identity = _pick(source, _IDENTITY_KEYS)
    existing_identity = source.get("identity")
    if isinstance(existing_identity, dict):
        identity.update(existing_identity)
    return {
        **source,
        "schema_version": SOCIAL_SCHEMA_VERSION,
        "platform": str(platform or source.get("platform") or ""),
        "verified": is_verified,
        "identity": identity,
        "proof": _merged_proof(source, _TARGET_PROOF_KEYS, verified=is_verified),
    }


# --- readers -----------------------------------------------------------------
#
# These accept a v1 payload and a payload written before v1 existed. A scenario
# can be mid-run when the code changes underneath it, so "old shape" is not a
# migration window — it is a value already sitting in a running execution.


def read_actions(payload: Any) -> list[dict[str, Any]] | None:
    """The scanned actions, or None when the payload carries no action list.

    None and `[]` mean different things to the caller: "this variable was never
    a scan result" versus "the scan found nothing", so they stay distinct.
    """
    if not isinstance(payload, dict):
        return None
    actions = payload.get("actions")
    if isinstance(actions, list):
        return actions
    return None


def read_verified(payload: Any) -> bool:
    """Whether a target payload claims verification, in either shape."""
    if not isinstance(payload, dict):
        return False
    proof = payload.get("proof")
    if isinstance(proof, dict) and "verified" in proof:
        return proof.get("verified") is True
    return payload.get("verified") is True


def read_identity(payload: Any) -> dict[str, Any]:
    """Who the target is; reconstructed from top-level keys for old payloads."""
    if not isinstance(payload, dict):
        return {}
    identity = payload.get("identity")
    if isinstance(identity, dict) and identity:
        return identity
    return _pick(payload, _IDENTITY_KEYS)


def read_proof(payload: Any) -> dict[str, Any]:
    """The evidence behind the payload; reconstructed for old payloads."""
    if not isinstance(payload, dict):
        return {}
    proof = payload.get("proof")
    if isinstance(proof, dict) and proof:
        return proof
    keys = _SCAN_PROOF_KEYS if "actions" in payload else _TARGET_PROOF_KEYS
    return _merged_proof(payload, keys, verified=payload.get("verified") is True)


def read_platform(payload: Any, default: str = "") -> str:
    if not isinstance(payload, dict):
        return default
    return str(payload.get("platform") or default)


def read_schema_version(payload: Any) -> int | None:
    """The declared version, or None for a payload written before v1."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("schema_version")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
