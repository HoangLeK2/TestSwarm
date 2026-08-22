"""Guard: pixel arithmetic on a moving UI must be a decision, not a habit.

Six separate production failures in one device session had the same root: code
that reasoned about *where* something was instead of *what* it was.

===================================  =====================================
site                                 what it did
===================================  =====================================
``_fb_visible_person_row_labels``    grouped labels within 200px of each
                                     other, welding two people's names into
                                     ``'Anh Bui Nguyễn Hoài Sơn'``
``_fb_pending_request_near``         verified around the tap point, so a
                                     request that really was sent reported
                                     as a failure
tap in ``_flow_fb_connect_...``      reused coordinates from an older dump;
                                     a banner shifted the page underneath
``_fb_nearby_labels(760)``           pulled in the next post's text
``len(action_buttons) == 1``         counted buttons on screen — a profile
                                     page always has more than one
"take the topmost button"            stops being the owner's the moment the
                                     page is scrolled: friends a stranger
===================================  =====================================

Pixels are not banned. A screen is a plane and some questions are genuinely
geometric — an overlay does cover the bottom of the screen. What is banned is
using them *without saying so*. Every function that does pixel arithmetic must
appear in ``_GEOMETRY_APPROVED`` with a reason, which is the point where a
reviewer gets to ask "why is position the right question here?".

The alternatives already exist and should be reached for first:

``_fb_person_row_scope``        read a row from the card subtree, not a band
``_fb_profile_owner_connection`` anchor to the owner's name, not to a position
``_fb_still_offering_add_friend`` verify by identity, not by proximity
``_fb_dedupe_action_buttons``   collapse nested duplicates instead of counting
"""

from __future__ import annotations

import ast
from pathlib import Path

from relay import u2_executor as _u2_executor

_EXECUTOR_SOURCE = Path(_u2_executor.__file__)

# A pixel-sized literal. Below this, a constant is an index, a count or a small
# ratio rather than a distance on screen.
_PIXEL_THRESHOLD = 8

# Names that hold or produce screen coordinates. Arithmetic mixing one of these
# with a pixel-sized constant is what this guard is looking for.
_GEOMETRY_NAMES = (
    "bounds",
    "top",
    "bottom",
    "left",
    "right",
    "tap_x",
    "tap_y",
    "center_x",
    "center_y",
    "y_padding",
    "x_padding",
    "screen_bottom",
    "screen_right",
    "width",
    "height",
)

# Functions allowed to reason in pixels, and why position is the right question
# there. Adding a name here is a deliberate act; a reviewer should read the
# reason and push back if identity would have worked.
_GEOMETRY_APPROVED: dict[str, str] = {
    # Genuinely geometric: these answer "where on the screen", which has no
    # identity-based equivalent.
    "_fb_overlay_bounds": (
        "A bottom sheet IS a geometric fact: a wide node anchored to the bottom "
        "edge. Detecting it by resource-id was worse — Facebook renames ids "
        "between builds, and the covered content stays in the hierarchy."
    ),
    "_fb_screen_right": "Reads the screen width off the hierarchy.",
    "_fb_scroll_profile_to_top": "Swipe coordinates; a swipe has no identity.",
    "_fb_dedupe_action_buttons": (
        "Collapses one control reported at several nesting levels; two nodes "
        "are the same control when their centres coincide."
    ),
    "_fb_label_at_point": (
        "Answers 'what is under this exact tap', which is a question about a "
        "point by definition. Picks the smallest covering node, not a band."
    ),
    "_fb_guarded_click": "Passes a tap point through to _fb_label_at_point.",
    # Position used as a tiebreaker AFTER identity has already selected the
    # target. This is the safe pattern: geometry orders, identity decides.
    "_fb_profile_owner_connection": (
        "Identity picks the owner's name first; distance only chooses between "
        "controls already known to belong below it and above any suggestion "
        "heading. Position never selects the target on its own."
    ),
    "_fb_profile_suggestion_top": (
        "Returns the y of a heading found by label, so a caller can exclude "
        "everything under it. The heading is identified, not located."
    ),
    # Known debt. These are the sites the six failures came from; they still
    # read bands and are listed so nobody has to rediscover them.
    "_fb_nearby_labels": (
        "DEBT: still a ±y band around a post. Should read the post card "
        "subtree the way _fb_person_row_scope reads a person row."
    ),
    "_fb_same_row_labels": (
        "DEBT: 180px band. Superseded by _fb_person_row_scope on the friend "
        "surfaces; still used by the older post flows."
    ),
    "_fb_visible_person_row_labels": (
        "DEBT: the band-based row reader that welded two names together. Kept "
        "only as the fallback when the card subtree cannot be resolved."
    ),
    "_fb_author_candidate_near_post": (
        "DEBT: searches a band above the action bar for the author's name."
    ),
    "_fb_dismiss_friend_suggestion_prompt": (
        "DEBT: finds the close button by size and corner. It is guarded by a "
        "label check, but the size limits are still magic numbers."
    ),
    "_fb_see_more_bounds_near": (
        "DEBT: accepts a 'Xem thêm' link within 80px of the post it belongs "
        "to. Should be the post card subtree."
    ),
    "_fb_visible_post_candidates": (
        "DEBT: pairs a comment button with the like button within 180px. Both "
        "belong to the same action row, which the tree already says."
    ),
    "_fb_dedupe_post_candidates": (
        "DEBT: treats two candidates within 220px as the same post. A post "
        "fingerprint (_fb_post_fingerprint) is the identity-based answer."
    ),
    "_fb_connection_state_near": (
        "DEBT: reads the connection state within 260px of the tap point. "
        "Superseded by _fb_still_offering_add_friend, which asks about the "
        "target by name; this remains for the flows not yet migrated."
    ),
    "_fb_commenter_author_nodes": (
        "DEBT: skips nodes above y=260 to avoid the sheet header. The header "
        "is identifiable by label (_FB_COMMENTS_HEADER_TOKENS)."
    ),
    "_fb_search_suggestion_bounds": (
        "DEBT: skips nodes above y=280 to avoid the search bar itself."
    ),
    "_fb_open_friend_suggestions_surface": (
        "DEBT: finds the back/close control by corner and size. The label "
        "check next to it is what actually makes this safe."
    ),
    "_flow_fb_select_people_profile": (
        "DEBT: nudges the tap point inside the name label rather than tapping "
        "its centre, because the centre can land on an overlapping control. "
        "The offsets are tuned to one device's density."
    ),
}


def _pixel_constant(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
        and abs(node.value) > _PIXEL_THRESHOLD
    )


def _geometry_expr(node: ast.expr) -> bool:
    """True when the expression reads a coordinate."""
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and inner.id.casefold() in _GEOMETRY_NAMES:
            return True
        if isinstance(inner, ast.Attribute) and inner.attr.casefold() in _GEOMETRY_NAMES:
            return True
        if isinstance(inner, ast.Subscript) and isinstance(inner.value, ast.Name):
            if inner.value.id.casefold() in _GEOMETRY_NAMES:
                return True
    return False


def _pixel_arithmetic(tree: ast.AST) -> list[tuple[int, str]]:
    """Every place a coordinate is combined with a pixel-sized constant."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv)
        ):
            operands = (node.left, node.right)
            if any(_pixel_constant(item) for item in operands) and any(
                _geometry_expr(item) for item in operands
            ):
                found.append((node.lineno, "coordinate +/- pixel constant"))
        elif isinstance(node, ast.Compare):
            parts = [node.left, *node.comparators]
            if any(_pixel_constant(item) for item in parts) and any(
                _geometry_expr(item) for item in parts
            ):
                found.append((node.lineno, "coordinate compared to pixel constant"))
    return found


def _enclosing_functions(tree: ast.AST) -> dict[int, str]:
    owner: dict[int, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for line in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                # Inner functions win: they are the tighter scope.
                owner[line] = node.name
    return owner


def _violations() -> list[str]:
    tree = ast.parse(_EXECUTOR_SOURCE.read_text(encoding="utf-8"))
    owners = _enclosing_functions(tree)
    out: list[str] = []
    for line, what in _pixel_arithmetic(tree):
        owner = owners.get(line, "<module>")
        if owner in _GEOMETRY_APPROVED:
            continue
        out.append(f"{_EXECUTOR_SOURCE.name}:{line} in {owner}: {what}")
    return sorted(set(out))


def test_pixel_reasoning_is_declared() -> None:
    violations = _violations()
    assert not violations, (
        "This function reasons about position on a UI that moves under it. "
        "Prefer identity: _fb_person_row_scope reads a row from the card "
        "subtree, _fb_profile_owner_connection anchors to the owner's name, "
        "_fb_still_offering_add_friend verifies by who the row is about. If "
        "geometry really is the right question, add the function to "
        "_GEOMETRY_APPROVED with the reason:\n  " + "\n  ".join(violations)
    )


def test_approved_list_has_no_dead_entries() -> None:
    """An approval for a function that no longer exists is stale paperwork."""
    tree = ast.parse(_EXECUTOR_SOURCE.read_text(encoding="utf-8"))
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    missing = sorted(set(_GEOMETRY_APPROVED) - defined)
    assert not missing, (
        f"_GEOMETRY_APPROVED names functions that no longer exist: {missing}"
    )


def test_every_approval_states_a_reason() -> None:
    empty = sorted(name for name, why in _GEOMETRY_APPROVED.items() if not why.strip())
    assert not empty, f"an approval without a reason is just a mute button: {empty}"


def test_known_debt_is_still_labelled_as_debt() -> None:
    """The band-based readers are on the list as debt, not as good design.

    If one of them is rewritten to read the tree, its entry should leave the
    list entirely rather than lose the DEBT prefix and look sanctioned.
    """
    for name in ("_fb_nearby_labels", "_fb_visible_person_row_labels"):
        reason = _GEOMETRY_APPROVED.get(name, "")
        assert reason.startswith("DEBT:"), (
            f"{name} reads a pixel band around a target. It is tolerated, not "
            f"endorsed — keep the DEBT: prefix or rewrite it to read the tree."
        )


def test_the_guard_itself_catches_the_original_bug() -> None:
    """The construct that produced 'Anh Bui Nguyễn Hoài Sơn'."""
    band_reader = ast.parse(
        "def f(bounds, node_bounds):\n"
        "    top = bounds[1]\n"
        "    return abs(node_bounds[1] - top) < 200\n"
    )
    assert _pixel_arithmetic(band_reader), (
        "the AST rule no longer recognises band-based row reading"
    )
    stale_tap = ast.parse("def f(tap_y):\n    return tap_y - 240\n")
    assert _pixel_arithmetic(stale_tap)
    # Quiet on the shapes that are not pixel reasoning.
    assert not _pixel_arithmetic(ast.parse("def f(items):\n    return len(items) > 3\n"))
    assert not _pixel_arithmetic(
        ast.parse("def f(bounds):\n    return bounds[0], bounds[1]\n")
    )
    assert not _pixel_arithmetic(
        ast.parse("def f(bottom, screen):\n    return bottom >= screen * 0.97\n")
    )
