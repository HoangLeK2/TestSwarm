from __future__ import annotations

import re
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from services.social_actions.contract import (
    Bounds,
    SocialActionObservation,
    UnsupportedSocialAction,
)

_BOUNDS_RE = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")


def _normalized(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", value or "").replace("Đ", "D").replace("đ", "d")
    return " ".join(
        "".join(ch for ch in raw if not unicodedata.combining(ch))
        .casefold()
        .split()
    )


def _parse_bounds(value: str | None) -> Bounds | None:
    match = _BOUNDS_RE.fullmatch((value or "").strip())
    if not match:
        return None
    left, top, right, bottom = (int(part) for part in match.groups())
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _matches(label: str, aliases: frozenset[str]) -> bool:
    return label in aliases or any(
        label.startswith((f"{alias},", f"{alias}.", f"{alias} ·"))
        for alias in aliases
    )


def _is_near(bounds: Bounds | None, target: Bounds | None) -> bool:
    if target is None:
        return True
    if bounds is None:
        return False
    left, top, right, bottom = bounds
    t_left, t_top, t_right, t_bottom = target
    margin = max(24, t_bottom - t_top)
    return not (
        right < t_left - margin
        or left > t_right + margin
        or bottom < t_top - margin
        or top > t_bottom + margin
    )


@dataclass(frozen=True, slots=True)
class _UiNode:
    labels: tuple[str, ...]
    bounds: Bounds | None
    selected: bool
    checked: bool
    clickable: bool


def _nodes(hierarchy_xml: str) -> list[_UiNode]:
    root = ET.fromstring(hierarchy_xml)
    result: list[_UiNode] = []
    for element in root.iter():
        labels = tuple(
            dict.fromkeys(
                label
                for label in (
                    _normalized(element.attrib.get("text")),
                    _normalized(element.attrib.get("content-desc")),
                )
                if label
            )
        )
        if not labels:
            continue
        result.append(
            _UiNode(
                labels=labels,
                bounds=_parse_bounds(element.attrib.get("bounds")),
                selected=element.attrib.get("selected") == "true",
                checked=element.attrib.get("checked") == "true",
                clickable=element.attrib.get("clickable") == "true",
            )
        )
    return result


_LIKE_AVAILABLE = frozenset({"like", "thich", "nut thich"})
_LIKE_ACTIVE = frozenset(
    {
        "unlike",
        "remove like",
        "bo thich",
        "bo cam xuc thich",
        "da thich",
        "da nhan nut thich",
        "nut bo thich",
    }
)
_COMMENT_AVAILABLE = frozenset({"comment", "binh luan", "nut binh luan"})
_COMMENT_OPEN = frozenset(
    {
        "write a comment",
        "comment as",
        "viet binh luan",
        "viet binh luan cong khai",
        "binh luan cong khai",
    }
)
_SHARE_AVAILABLE = frozenset({"share", "chia se", "nut chia se"})
_SHARE_OPEN = frozenset(
    {
        "share now",
        "share to your story",
        "write post",
        "copy link",
        "send in messenger",
        "chia se ngay",
        "nut chia se ngay",
        "chia se len tin cua ban",
        "viet bai",
        "sao chep lien ket",
        "gui bang messenger",
    }
)
_FRIEND_AVAILABLE = frozenset({"add friend", "them ban be", "nut them ban be"})
_FRIEND_PENDING = frozenset(
    {
        "cancel request",
        "cancel friend request",
        "request sent",
        "huy loi moi",
        "huy yeu cau",
        "da gui loi moi",
        "nut huy loi moi",
    }
)
_FRIEND_CONNECTED = frozenset({"friends", "ban be"})
_JOIN_AVAILABLE = frozenset({"join", "join group", "tham gia", "tham gia nhom"})
_JOIN_PENDING = frozenset(
    {
        "pending",
        "cancel request",
        "request sent",
        "dang cho",
        "huy yeu cau",
        "da gui yeu cau",
    }
)
_JOIN_ACTIVE = frozenset({"joined", "leave group", "da tham gia", "roi nhom"})


class FacebookSocialActionAdapter:
    platform = "facebook"

    def observe(
        self,
        *,
        action_type: str,
        action: str,
        hierarchy_xml: str,
        near_bounds: Bounds | None = None,
    ) -> SocialActionObservation:
        nodes = [
            node
            for node in _nodes(hierarchy_xml)
            if _is_near(node.bounds, near_bounds)
        ]
        if action_type == "content_interaction":
            if action == "like":
                return self._observe(
                    nodes,
                    active=_LIKE_ACTIVE,
                    pending=frozenset(),
                    available=_LIKE_AVAILABLE,
                    active_state="liked",
                    pending_state="",
                    selected_available_state="liked",
                )
            if action == "comment":
                return self._observe_open_panel(
                    nodes,
                    active=_COMMENT_OPEN,
                    available=_COMMENT_AVAILABLE,
                    active_state="comment_opened",
                )
            if action == "share":
                return self._observe_open_panel(
                    nodes,
                    active=_SHARE_OPEN,
                    available=_SHARE_AVAILABLE,
                    active_state="share_opened",
                )
            raise UnsupportedSocialAction(
                f"facebook content_interaction does not support action={action!r}"
            )
        if action_type == "connection_request":
            if action != "request":
                raise UnsupportedSocialAction(
                    f"facebook connection_request does not support action={action!r}"
                )
            return self._observe(
                nodes,
                active=_FRIEND_CONNECTED,
                pending=_FRIEND_PENDING,
                available=_FRIEND_AVAILABLE,
                active_state="connected",
                pending_state="request_pending",
            )
        if action_type == "community_membership":
            if action != "join":
                raise UnsupportedSocialAction(
                    f"facebook community_membership does not support action={action!r}"
                )
            return self._observe(
                nodes,
                active=_JOIN_ACTIVE,
                pending=_JOIN_PENDING,
                available=_JOIN_AVAILABLE,
                active_state="member",
                pending_state="join_pending",
            )
        raise UnsupportedSocialAction(f"unknown social action type {action_type!r}")

    @staticmethod
    def _observe(
        nodes: list[_UiNode],
        *,
        active: frozenset[str],
        pending: frozenset[str],
        available: frozenset[str],
        active_state: str,
        pending_state: str,
        selected_available_state: str | None = None,
    ) -> SocialActionObservation:
        active_matches: list[tuple[_UiNode, str, str]] = []
        available_matches: list[tuple[_UiNode, str]] = []
        for node in nodes:
            for label in node.labels:
                if _matches(label, active):
                    active_matches.append((node, label, active_state))
                    break
                if pending_state and _matches(label, pending):
                    active_matches.append((node, label, pending_state))
                    break
                if _matches(label, available):
                    available_matches.append((node, label))
                    break

        # An available action is stronger evidence than unrelated state labels
        # elsewhere on the screen. Never pick an arbitrary item from a feed.
        bounded = [
            (node, label)
            for node, label in available_matches
            if node.bounds is not None
        ]
        actionable = [
            (node, label)
            for node, label in bounded
            if node.clickable
        ] or bounded
        if len(actionable) > 1:
            return SocialActionObservation(state="ambiguous")
        if len(actionable) == 1:
            node, label = actionable[0]
            if selected_available_state and (node.selected or node.checked):
                return SocialActionObservation(
                    state=selected_available_state,
                    matched_label=label,
                    satisfied=True,
                )
            return SocialActionObservation(
                state="available",
                target_bounds=node.bounds,
                matched_label=label,
            )

        # Facebook commonly exposes the same state on a clickable button and
        # its non-clickable text child. Prefer the actionable node so one visual
        # control is not misclassified as multiple targets.
        bounded_active = [
            (node, label, state)
            for node, label, state in active_matches
            if node.bounds is not None
        ]
        actionable_active = [
            (node, label, state)
            for node, label, state in bounded_active
            if node.clickable
        ] or bounded_active
        if len(actionable_active) > 1:
            return SocialActionObservation(state="ambiguous")
        if len(actionable_active) == 1:
            node, label, state = actionable_active[0]
            return SocialActionObservation(
                state=state,
                target_bounds=node.bounds,
                matched_label=label,
                satisfied=True,
            )
        if len(active_matches) > 1:
            return SocialActionObservation(state="ambiguous")
        if len(active_matches) == 1:
            node, label, state = active_matches[0]
            return SocialActionObservation(
                state=state,
                target_bounds=node.bounds,
                matched_label=label,
                satisfied=True,
            )

        if available_matches:
            return SocialActionObservation(state="target_without_bounds")
        return SocialActionObservation(state="not_found")

    @staticmethod
    def _observe_open_panel(
        nodes: list[_UiNode],
        *,
        active: frozenset[str],
        available: frozenset[str],
        active_state: str,
    ) -> SocialActionObservation:
        active_matches: list[tuple[_UiNode, str]] = []
        available_matches: list[tuple[_UiNode, str]] = []
        for node in nodes:
            for label in node.labels:
                if _matches(label, active):
                    active_matches.append((node, label))
                    break
                if _matches(label, available):
                    available_matches.append((node, label))
                    break

        if active_matches:
            node, label = active_matches[0]
            return SocialActionObservation(
                state=active_state,
                target_bounds=node.bounds,
                matched_label=label,
                satisfied=True,
            )

        bounded = [
            (node, label)
            for node, label in available_matches
            if node.bounds is not None
        ]
        actionable = [
            (node, label)
            for node, label in bounded
            if node.clickable
        ] or bounded
        if len(actionable) > 1:
            return SocialActionObservation(state="ambiguous")
        if len(actionable) == 1:
            node, label = actionable[0]
            return SocialActionObservation(
                state="available",
                target_bounds=node.bounds,
                matched_label=label,
            )
        if available_matches:
            return SocialActionObservation(state="target_without_bounds")
        return SocialActionObservation(state="not_found")
