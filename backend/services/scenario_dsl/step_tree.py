"""Recursive traversal of the authored scenario step tree (DF-T-04-002).

Validation used to look at `steps[]` only. Everything a branch or a loop holds —
which is where the real work of a nurture scenario lives — was never checked, so
a nested node could ship with no `id` at all. That is not cosmetic: the durable
account-action ledger keys a claim by step id and refuses the claim without one,
so a `connection_request` nested three levels deep failed with "Enabled account
action ledger requires execution id and stable step id" and the friend request
was never sent. A duplicate nested id is worse — two distinct actions collapse
onto one idempotency key and the second is silently dropped as already done.

What counts as an authored step here is deliberately narrow: a dict that carries
a non-empty `type` and sits inside one of the containers the runtime executes.
Runtime-generated and configuration objects — a `random_pick` branch wrapper, a
`login_if_needed` profile recipe, a step's `config` block — are not steps and are
never yielded, so a caller cannot demand an id from something that has no place
to put one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterator

# Keys the runtime executes as a list of authored steps.
NESTED_STEP_LIST_KEYS: tuple[str, ...] = (
    "steps",
    "then",
    "else",
    "else_steps",
    "completion_steps",
)

# Keys holding exactly one authored step rather than a list.
NESTED_STEP_KEYS: tuple[str, ...] = ("completion_verify",)

# `random_pick` wraps its children: branches[].steps. The branch dict itself
# carries a weight, not a type, and is not a step.
BRANCH_CONTAINER_KEY = "branches"


@dataclass(frozen=True, slots=True)
class AuthoredStep:
    """One authored step plus where it sits in the tree."""

    step: dict[str, Any]
    location: str
    depth: int

    @property
    def step_id(self) -> str:
        return str(self.step.get("id") or "").strip()

    @property
    def step_type(self) -> str:
        return str(self.step.get("type") or "").strip()


def _is_authored_step(value: Any) -> bool:
    return isinstance(value, dict) and bool(str(value.get("type") or "").strip())


def iter_authored_steps(
    steps: Any,
    *,
    root: str = "steps",
    depth: int = 0,
) -> Iterator[AuthoredStep]:
    """Yield every authored step in `steps`, depth-first, parents before children."""
    if not isinstance(steps, list):
        return
    for index, step in enumerate(steps):
        if not _is_authored_step(step):
            continue
        location = f"{root}[{index}]"
        yield AuthoredStep(step=step, location=location, depth=depth)

        for key in NESTED_STEP_LIST_KEYS:
            yield from iter_authored_steps(
                step.get(key), root=f"{location}.{key}", depth=depth + 1
            )
        for key in NESTED_STEP_KEYS:
            nested = step.get(key)
            if _is_authored_step(nested):
                yield AuthoredStep(
                    step=nested, location=f"{location}.{key}", depth=depth + 1
                )
        branches = step.get(BRANCH_CONTAINER_KEY)
        if isinstance(branches, list):
            for branch_index, branch in enumerate(branches):
                if not isinstance(branch, dict):
                    continue
                yield from iter_authored_steps(
                    branch.get("steps"),
                    root=f"{location}.{BRANCH_CONTAINER_KEY}[{branch_index}].steps",
                    depth=depth + 1,
                )


def _derive_step_id(anchor: str | None, container: str, index: int) -> str:
    if anchor is None:
        return f"step_{index}"
    return f"{anchor}__{container}_{index}"


def _unique_step_id(base: str, used: set[str]) -> str:
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}_{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _assign_ids_in_list(
    steps: Any, *, anchor: str | None, container: str, used: set[str]
) -> Any:
    if not isinstance(steps, list):
        return steps
    return [
        _assign_ids_in_step(
            step, anchor=anchor, container=container, index=index, used=used
        )
        if _is_authored_step(step)
        else step
        for index, step in enumerate(steps)
    ]


def _assign_ids_in_step(
    step: dict[str, Any],
    *,
    anchor: str | None,
    container: str,
    index: int,
    used: set[str],
) -> dict[str, Any]:
    out = dict(step)
    step_id = str(out.get("id") or "").strip()
    if not step_id:
        step_id = _unique_step_id(_derive_step_id(anchor, container, index), used)
        out.pop("id", None)
        out = {"id": step_id, **out}

    for key in NESTED_STEP_LIST_KEYS:
        if isinstance(out.get(key), list):
            out[key] = _assign_ids_in_list(
                out[key], anchor=step_id, container=key, used=used
            )
    for key in NESTED_STEP_KEYS:
        nested = out.get(key)
        if _is_authored_step(nested):
            out[key] = _assign_ids_in_step(
                nested, anchor=step_id, container=key, index=0, used=used
            )
    branches = out.get(BRANCH_CONTAINER_KEY)
    if isinstance(branches, list):
        out[BRANCH_CONTAINER_KEY] = [
            {
                **branch,
                "steps": _assign_ids_in_list(
                    branch["steps"],
                    anchor=step_id,
                    container=f"branch{branch_index}",
                    used=used,
                ),
            }
            if isinstance(branch, dict) and isinstance(branch.get("steps"), list)
            else branch
            for branch_index, branch in enumerate(branches)
        ]
    return out


def assign_missing_step_ids(steps: Any, *, root: str = "steps") -> Any:
    """Give every authored step an id, deriving one where the author left none.

    Returns a new tree; the input is never mutated, so a module-level template
    spec can be passed straight in.

    The derived id is anchored to the nearest ancestor that *does* carry one:
    ``seed_friends_cycle__then_0__steps_2``. That keeps a generated id readable
    back to a place in the scenario, and keeps a rename of one authored id from
    silently renumbering an unrelated branch.

    Derivation is structural, never random. The builtin templates are rewritten
    from their code spec on every startup, so a random id would hand the same
    step a different name on each deploy — precisely the instability an id
    exists to prevent. Being structural also makes this idempotent: running it
    twice changes nothing.

    Known limit, and the reason hand-written ids still matter: a derived id
    moves when a sibling is inserted above it. Within one execution that is
    harmless — the step tree is frozen into the workflow input at dispatch, and
    ``stable_action_key`` scopes a ledger claim by execution id. Across two
    versions of a scenario it means the two runs of "the same" step cannot be
    joined by id. Steps that write to the ledger — ``connection_request``,
    ``content_interaction``, ``community_membership`` — should therefore be
    given an explicit id by whoever authors them.
    """
    used = {
        item.step_id for item in iter_authored_steps(steps, root=root) if item.step_id
    }
    return _assign_ids_in_list(steps, anchor=None, container=root, used=used)


def find_steps_missing_id(steps: Any, *, root: str = "steps") -> list[AuthoredStep]:
    """Authored steps with no usable `id`, at any depth."""
    return [item for item in iter_authored_steps(steps, root=root) if not item.step_id]


def find_duplicate_step_ids(
    steps: Any, *, root: str = "steps"
) -> dict[str, list[str]]:
    """Map each repeated step id to the locations that claim it, at any depth."""
    seen: dict[str, list[str]] = {}
    for item in iter_authored_steps(steps, root=root):
        if item.step_id:
            seen.setdefault(item.step_id, []).append(item.location)
    return {sid: locs for sid, locs in seen.items() if len(locs) > 1}


def count_step_ids(steps: Any, *, root: str = "steps") -> Counter[str]:
    """How often each authored id appears, at any depth."""
    return Counter(
        item.step_id for item in iter_authored_steps(steps, root=root) if item.step_id
    )
