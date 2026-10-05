"""Semantic action names and human sentences for account activity logs.

The DSL step type says how a step is implemented (``tap_selector``); an operator
needs to know what the account did (``comment.section_open``). This table is the
only place the two are connected.

Names are ``<entity>.<operation>`` and deliberately platform-neutral: the same
``comment.submit`` covers platforms that support comment submission. A scenario node can
declare its own name via ``semantic_action`` when the step type alone cannot
say — ``tap_selector`` is a click, and nothing in the selector tells us whether
that click opens comments or reports a post. Guessing the meaning from the
selector can target the wrong row; the node
author knows, so let them say it.

Steps not in this table are technical (extract, wait, control flow) and produce
no account-activity line.
"""
from __future__ import annotations

from typing import Any

# step type -> (semantic action, human sentence template)
_STEP_ACTIONS: dict[str, tuple[str, str]] = {
    # app lifecycle
    "launch_app": ("app.open", "Opened app {target}"),
    "stop_app": ("app.close", "Closed app {target}"),
    "clear_app": ("app.clear_data", "Cleared app data for {target}"),
    "wait_app": ("app.wait_foreground", "Waited for {target} to reach the foreground"),
    "open_url": ("app.open_url", "Opened {target}"),
    "install_apk": ("app.install", "Installed {target}"),
    "key": ("navigation.key", "Pressed {target}"),
    # generic UI operations
    "tap": ("ui.click", "Tapped {target}"),
    "tap_ratio": ("ui.click", "Tapped {target}"),
    "tap_position": ("ui.click", "Tapped {target}"),
    "tap_selector": ("ui.click", "Clicked {target}"),
    "tap_image": ("ui.click", "Clicked image {target}"),
    "tap_xml_match": ("ui.click", "Clicked {target}"),
    "double_tap": ("ui.double_click", "Double-tapped {target}"),
    "long_tap_selector": ("ui.long_press", "Long-pressed {target}"),
    "drag": ("ui.drag", "Dragged {target}"),
    "pinch": ("ui.pinch", "Pinched {target}"),
    "swipe_ratio": ("ui.swipe", "Swiped {target}"),
    "scroll_down": ("ui.scroll", "Scrolled {target}"),
    "scroll_to": ("ui.scroll", "Scrolled to {target}"),
    # text entry
    "input_text": ("ui.input", "Entered text into the focused field {target}"),
    "input_selector": ("ui.input", "Entered text into {target}"),
    "set_clipboard": ("ui.clipboard_set", "Copied text to the clipboard"),
    "fill_form": ("form.fill", "Filled in the form {target}"),
    # session
    "login_if_needed": ("session.login", "Signed in {target}"),
    "platform_session_gate": ("session.gate", "Checked the signed-in session {target}"),
    # domain / social
    "social_select_target": ("target.select", "Picked target {target}"),
    "social_open_comments": ("comment.section_open", "Opened the comment section on {target}"),
    "social_find_comment_button": ("comment.locate", "Located the comment control on {target}"),
    "social_tap_comment_target": ("comment.input_focus", "Focused the comment box on {target}"),
    "social_apply_comment_filter": ("filter.apply", "Applied comment filter {target}"),
    "social_open_author_from_post_match": ("profile.open", "Opened author profile {target}"),
    "social_open_commenter_from_post_match": ("profile.open", "Opened commenter profile {target}"),
    "social_connect_visible_people": ("connection.request", "Sent connection requests {target}"),
    "social_scan_posts_interact": ("post.interact", "Interacted with feed posts {target}"),
    "social_sync_connections": ("connection.sync", "Synced the connection list"),
    "connection_request": ("connection.request", "Sent a connection request to {target}"),
    "community_membership": ("community.join", "Joined community {target}"),
    "content_interaction": ("post.interact", "Interacted with {target}"),
}

# (step type, discriminator value) -> (semantic action, template). A step type
# that covers several operations picks the precise one from its own config.
_ACTION_OVERRIDES: dict[tuple[str, str], tuple[str, str]] = {
    ("content_interaction", "like"): ("post.like", "Liked {target}"),
    ("content_interaction", "unlike"): ("post.unlike", "Removed the like on {target}"),
    ("content_interaction", "share"): ("post.share", "Shared {target}"),
    ("content_interaction", "comment"): ("comment.submit", "Commented on {target}"),
    ("content_interaction", "follow"): ("profile.follow", "Followed {target}"),
    ("content_interaction", "unfollow"): ("profile.unfollow", "Unfollowed {target}"),
    ("key", "back"): ("navigation.back", "Went back"),
    ("key", "home"): ("navigation.home", "Went to the home screen"),
    ("key", "enter"): ("ui.submit", "Submitted with the enter key"),
}

# Which step field distinguishes the operations above.
_DISCRIMINATOR_FIELD: dict[str, str] = {
    "content_interaction": "action",
    "key": "key",
}

# Steps whose payload is user content. Their label is a length, never the text:
# a comment body in a rotating log file is a privacy liability, and the full
# value is already kept in account_actions.result.comment_text under redaction.
_TEXT_ENTRY_STEPS = frozenset({"input_text", "input_selector", "set_clipboard"})

_LABEL_RESULT_KEYS = ("display_name", "matched_label", "target_label", "external_entity_id")
_LABEL_STEP_KEYS = ("package", "component", "url", "key", "target_label", "name")

_MAX_LABEL_CHARS = 120

# Wording for a node-declared `semantic_action`. Domain names win over the
# generic UI names, so `ui.click` never shadows `post.open`.
_TEMPLATE_BY_ACTION: dict[str, str] = {
    action: template
    for action, template in (
        *_STEP_ACTIONS.values(),
        *_ACTION_OVERRIDES.values(),
    )
    if not action.startswith("ui.")
}
_TEMPLATE_BY_ACTION.update({
    # Declared-only names: no step type produces these on its own, because only
    # the node author knows a tap opens the feed rather than a menu.
    "feed.open": "Opened the feed {target}",
    "feed.refresh": "Refreshed the feed",
    "post.open": "Opened post {target}",
    "search.open": "Opened search",
    "search.submit": "Searched for {target}",
    "search.result_open": "Opened search result {target}",
    "filter.open": "Opened the filter menu",
    "filter.select": "Selected filter {target}",
    "profile.open": "Opened profile {target}",
    "comment.submit": "Submitted a comment on {target}",
})


def _clip(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return text[:_MAX_LABEL_CHARS]


# Dropped from the end of a sentence whose target turned out to be unknown.
# "Sent a connection request to" is a sentence that stops mid-thought; the
# reader is left waiting for a name that the screen never gave us.
_DANGLING_TAIL = frozenset({"on", "to", "into", "for", "with", "from", "in", "at", "the"})


def _finish_sentence(template: str, label: str) -> str:
    sentence = " ".join(template.format(target=label).split())
    if label:
        return sentence
    words = sentence.split()
    while words and words[-1].casefold() in _DANGLING_TAIL:
        words.pop()
    return " ".join(words)


def _target_label(step: dict[str, Any], result: dict[str, Any]) -> str:
    """Name the thing acted on, never the content typed into it."""
    step_type = str(step.get("type") or "")
    if step_type in _TEXT_ENTRY_STEPS:
        typed = result.get("typed_text")
        if typed is None:
            typed = step.get("text")
        length = len(str(typed or ""))
        return f"({length} chars)" if length else ""
    for key in _LABEL_RESULT_KEYS:
        value = result.get(key)
        if value not in (None, "", [], {}):
            return _clip(value)
    for key in _LABEL_STEP_KEYS:
        value = step.get(key)
        if value not in (None, "", [], {}):
            return _clip(value)
    # Selector steps: the selector value is the closest thing to a name the
    # operator can act on ("Comment", "com.x:id/add_friend").
    value = step.get("value") or step.get("selector")
    if isinstance(value, dict):
        value = value.get("value") or value.get("text")
    return _clip(value) if value else ""


def describe(step: dict[str, Any], result: dict[str, Any] | None = None) -> tuple[str, str] | None:
    """Return ``(semantic_action, human_sentence)`` or None for technical steps."""
    if not isinstance(step, dict):
        return None
    result = result if isinstance(result, dict) else {}
    step_type = str(step.get("type") or "")

    declared = str(step.get("semantic_action") or "").strip()
    entry = _STEP_ACTIONS.get(step_type)
    discriminator = _DISCRIMINATOR_FIELD.get(step_type)
    if discriminator:
        raw = str(step.get(discriminator) or "").strip().casefold()
        entry = _ACTION_OVERRIDES.get((step_type, raw), entry)
    if entry is None and not declared:
        return None

    action, template = entry or ("", "{target}")
    if declared:
        # Follow the declared name's own wording. Without this a node declaring
        # comment.section_open on a tap_selector still read "Clicked Comment",
        # which is the implementation talking, not the account.
        action = declared
        template = _TEMPLATE_BY_ACTION.get(declared, template)
    label = _target_label(step, result)
    return action, _finish_sentence(template, label) or action


def semantic_action(step: dict[str, Any], result: dict[str, Any] | None = None) -> str | None:
    described = describe(step, result)
    return described[0] if described else None


# Actions that earn a row in account_actions. Deliberately domain-level only:
# every ledger write costs a database session, and a row per `ui.click` would
# put a synchronous write behind every tap while telling an operator nothing the
# account_activity log line does not already say.
LEDGER_ACTIONS: frozenset[str] = frozenset({
    "app.open",
    "session.login",
    "post.open",
    "post.like",
    "post.unlike",
    "post.share",
    "comment.submit",
    "profile.open",
    "profile.follow",
    "profile.unfollow",
    "filter.apply",
    "search.submit",
    "connection.request",
    "community.join",
})

_TARGET_TYPE_BY_ENTITY = {
    "app": "app",
    "session": "app",
    "post": "post",
    "comment": "post",
    "profile": "profile",
    "filter": "filter",
    "search": "search",
    "connection": "person",
    "community": "community",
}



# Actions whose target is a person, post or profile: the identity must come from
# what the screen reported, never from the selector that was tapped. A failed
# connection.request otherwise files a row against "Add Friend" — the name of
# the button — as though that were the person. Same reasoning as
# Identify by identity, and when the screen
# did not name the target, record nothing rather than something wrong.
_TARGET_MUST_BE_IDENTIFIED = frozenset({
    "post.open",
    "post.like",
    "post.unlike",
    "post.share",
    "comment.submit",
    "profile.open",
    "profile.follow",
    "profile.unfollow",
    "connection.request",
    "community.join",
})

# Identity fields, in precedence order. Selector values are deliberately absent.
_IDENTITY_RESULT_KEYS = ("external_entity_id", "target_id", "display_name", "matched_label")
_IDENTITY_STEP_KEYS = ("package", "component", "url")


def ledger_target(
    action: str, step: dict[str, Any], result: dict[str, Any]
) -> dict[str, Any] | None:
    """Target dict for a ledger row, or None when nothing identifies it.

    A row whose target cannot be named is worse than no row: ``stable_action_key``
    hashes the target, so an unnamed one collapses every occurrence of the step
    into a single record.
    """
    target_id = ""
    for key in _IDENTITY_RESULT_KEYS:
        target_id = str(result.get(key) or "").strip()
        if target_id:
            break
    if not target_id:
        for key in _IDENTITY_STEP_KEYS:
            target_id = str(step.get(key) or "").strip()
            if target_id:
                break
    label = _target_label(step, result)
    if not target_id:
        if action in _TARGET_MUST_BE_IDENTIFIED:
            return None
        # A filter or a search box is identified by its own wording, which is
        # what the selector holds.
        target_id = label
    if not target_id:
        return None
    return {
        "action": action,
        "target_type": _TARGET_TYPE_BY_ENTITY.get(action.split(".", 1)[0], "unknown"),
        "target_id": target_id[:_MAX_LABEL_CHARS],
        "label": label or target_id[:_MAX_LABEL_CHARS],
        "source": "scenario_step",
    }


def known_step_types() -> frozenset[str]:
    """Step types this table covers — used by the coverage guard test."""
    return frozenset(_STEP_ACTIONS) | {step_type for step_type, _ in _ACTION_OVERRIDES}
