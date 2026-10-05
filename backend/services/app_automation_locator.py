"""Semantic locator scoring for app automation profiles."""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from runtime.xml_utils import XML_PARSE_ERRORS, parse_xml
from services.app_automation_profile import AppAutomationProfile, LocatorCandidate, SemanticLocator


_BOUNDS_RE = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


@dataclass(frozen=True)
class HierarchyNode:
    raw: Any
    text: str
    desc: str
    resource_id: str
    class_name: str
    bounds: dict[str, int] | None

    def get(self, key: str, default: Any = None) -> Any:
        if key == "text":
            return self.text
        if key == "content-desc":
            return self.desc
        if key == "resource-id":
            return self.resource_id
        if key == "class":
            return self.class_name
        if key == "bounds":
            if not self.bounds:
                return default
            return "[{left},{top}][{right},{bottom}]".format(**self.bounds)
        return self.raw.get(key, default)


@dataclass(frozen=True)
class HierarchySnapshot:
    nodes: list[HierarchyNode]


@dataclass(frozen=True)
class LocatorResolution:
    matched: bool
    locator_name: str
    score: float
    reason: str
    fallback_level: str
    candidate_count: int
    bounds: dict[str, int] | None = None
    selector: dict[str, Any] | None = None


@dataclass(frozen=True)
class _ScoredNode:
    node: Any
    score: float
    reason: str
    fallback_level: str
    selector: dict[str, Any] | None
    bounds: dict[str, int] | None


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _node_text(node: Any) -> str:
    return str(node.get("text") or "")


def _node_desc(node: Any) -> str:
    return str(node.get("content-desc") or "")


def _node_resource_id(node: Any) -> str:
    return str(node.get("resource-id") or "")


def _node_class(node: Any) -> str:
    return str(node.get("class") or "")


def _parse_bounds(raw: str | None) -> dict[str, int] | None:
    if not raw:
        return None
    match = _BOUNDS_RE.search(raw)
    if not match:
        return None
    left, top, right, bottom = (int(part) for part in match.groups())
    return {"left": left, "top": top, "right": right, "bottom": bottom}


def _bounds_from_ocr_bbox(raw: dict[str, Any]) -> dict[str, int] | None:
    bbox = raw.get("bbox") if isinstance(raw.get("bbox"), dict) else raw
    try:
        x = int(bbox.get("x", bbox.get("left", 0)))
        y = int(bbox.get("y", bbox.get("top", 0)))
        w = int(bbox.get("w", bbox.get("width", 0)))
        h = int(bbox.get("h", bbox.get("height", 0)))
    except Exception:
        return None
    if w <= 0 or h <= 0:
        return None
    return {"left": x, "top": y, "right": x + w, "bottom": y + h}


def build_hierarchy_snapshot(hierarchy_xml: str) -> HierarchySnapshot:
    """Parse hierarchy XML once and precompute cheap node attributes."""
    root = parse_xml(hierarchy_xml)
    return HierarchySnapshot(
        nodes=[
            HierarchyNode(
                raw=node,
                text=str(node.get("text") or ""),
                desc=str(node.get("content-desc") or ""),
                resource_id=str(node.get("resource-id") or ""),
                class_name=str(node.get("class") or ""),
                bounds=_parse_bounds(node.get("bounds")),
            )
            for node in root.iter()
        ]
    )


def build_ocr_snapshot(ocr_results: list[dict[str, Any]] | None) -> HierarchySnapshot:
    """Build pseudo nodes from OCR boxes returned by agent-boot."""
    nodes: list[HierarchyNode] = []
    for index, item in enumerate(ocr_results or []):
        text = str(item.get("text") or "").strip()
        bounds = _bounds_from_ocr_bbox(item)
        if not text or not bounds:
            continue
        nodes.append(
            HierarchyNode(
                raw={"index": index, "text": text, "class": "ocr.text"},
                text=text,
                desc="",
                resource_id="",
                class_name="ocr.text",
                bounds=bounds,
            )
        )
    return HierarchySnapshot(nodes=nodes)


def _center(bounds: dict[str, int] | None) -> tuple[float, float] | None:
    if not bounds:
        return None
    return ((bounds["left"] + bounds["right"]) / 2, (bounds["top"] + bounds["bottom"]) / 2)


def _distance(a: dict[str, int] | None, b: dict[str, int] | None) -> float:
    ca = _center(a)
    cb = _center(b)
    if ca is None or cb is None:
        return math.inf
    return math.hypot(ca[0] - cb[0], ca[1] - cb[1])


def _bounds_with_offset(
    bounds: dict[str, int] | None,
    tap_offset: tuple[int, int] | None,
) -> dict[str, int] | None:
    if not bounds or not tap_offset:
        return bounds
    center = _center(bounds)
    if center is None:
        return bounds
    x = int(round(center[0] + tap_offset[0]))
    y = int(round(center[1] + tap_offset[1]))
    return {"left": x, "top": y, "right": x, "bottom": y}


def _node_selector(node: Any) -> dict[str, Any] | None:
    rid = _node_resource_id(node).strip()
    if rid:
        return {"by": "resource-id", "value": rid}
    text = _node_text(node).strip()
    if text:
        return {"by": "text", "value": text}
    desc = _node_desc(node).strip()
    if desc:
        return {"by": "description", "value": desc}
    return None


def _matches_by_value(node: Any, by: str, value: str) -> bool:
    if by in {"resource-id", "id", "resourceId"}:
        return _node_resource_id(node) == value
    if by == "text":
        return _node_text(node) == value
    if by in {"description", "content-desc", "accessibility id"}:
        return _node_desc(node) == value
    if by in {"class name", "className"}:
        return _node_class(node) == value
    if by == "textContains":
        return value in _node_text(node)
    if by == "descriptionContains":
        return value in _node_desc(node)
    return False


def _region_matches(bounds: dict[str, int] | None, region: str | None, screen: tuple[int, int] | None) -> bool:
    if not region or not screen or not bounds:
        return True
    cx, cy = _center(bounds) or (0, 0)
    width, height = screen
    if region == "top":
        return cy <= height * 0.35
    if region == "bottom":
        return cy >= height * 0.65
    if region == "left":
        return cx <= width * 0.40
    if region == "right":
        return cx >= width * 0.60
    if region == "center":
        return width * 0.25 <= cx <= width * 0.75 and height * 0.25 <= cy <= height * 0.75
    if region == "form":
        return height * 0.15 <= cy <= height * 0.90
    return True


def _score_direct_candidate(
    nodes: list[HierarchyNode],
    candidate: LocatorCandidate,
    screen: tuple[int, int] | None,
) -> list[_ScoredNode]:
    scored: list[_ScoredNode] = []
    class_name_is_filter = bool(
        candidate.class_name
        and (
            candidate.by
            or candidate.value
            or candidate.resource_id_contains
            or candidate.description_contains
        )
    )
    for node in nodes:
        bounds = node.bounds
        if not _region_matches(bounds, candidate.region, screen):
            continue
        if class_name_is_filter and _node_class(node) != candidate.class_name:
            continue

        if candidate.by and candidate.value and _matches_by_value(node, candidate.by, candidate.value):
            scored.append(_ScoredNode(node, 1.0, f"{candidate.by} exact match", "exact", _node_selector(node), bounds))
            continue

        rid_contains = _norm(candidate.resource_id_contains)
        if rid_contains and rid_contains in _norm(_node_resource_id(node)):
            scored.append(_ScoredNode(node, 0.90, "resource_id_contains match", "resource_id_contains", _node_selector(node), bounds))
            continue

        desc_contains = _norm(candidate.description_contains)
        if desc_contains and desc_contains in _norm(_node_desc(node)):
            scored.append(_ScoredNode(node, 0.82, "description_contains match", "description_contains", _node_selector(node), bounds))
            continue

        if candidate.class_name and _node_class(node) == candidate.class_name:
            scored.append(_ScoredNode(node, 0.55, "class_name match", "class_name", _node_selector(node), bounds))
    return scored


def _score_text_near_candidate(
    nodes: list[HierarchyNode],
    candidate: LocatorCandidate,
    screen: tuple[int, int] | None,
) -> list[_ScoredNode]:
    if not candidate.text_near:
        return []
    labels = []
    expected = [_norm(text) for text in candidate.text_near]
    for node in nodes:
        text = _norm(_node_text(node)) or _norm(_node_desc(node))
        if text and any(label and label in text for label in expected):
            labels.append((node.bounds, node))
    if not labels:
        return []

    target_nodes = []
    for node in nodes:
        if candidate.target_class and _node_class(node) != candidate.target_class:
            continue
        bounds = node.bounds
        if not bounds:
            continue
        if not _region_matches(bounds, candidate.region, screen):
            continue
        target_nodes.append((bounds, node))

    scored: list[_ScoredNode] = []
    for bounds, node in target_nodes:
        nearest_label = min(labels, key=lambda item: _distance(bounds, item[0]), default=None)
        if nearest_label is None:
            continue
        label_bounds, _ = nearest_label
        nearest = _distance(bounds, label_bounds)
        if not math.isfinite(nearest):
            continue
        score = max(0.0, 0.86 - min(nearest, 800.0) / 4000.0)
        label_center = _center(label_bounds)
        target_center = _center(bounds)
        if label_center and target_center:
            vertical_delta = abs(label_center[1] - target_center[1])
            if vertical_delta <= 70:
                score += 0.06
            elif vertical_delta > 120:
                score -= 0.08
        if score >= 0.55:
            selector = _node_selector(node)
            if selector is None and not candidate.allow_coordinate_fallback:
                continue
            scored.append(_ScoredNode(node, score, "text_near target_class match", "text_near", selector, bounds))
    return scored


def _score_ocr_near_candidate(
    nodes: list[HierarchyNode],
    ocr_nodes: list[HierarchyNode],
    candidate: LocatorCandidate,
    screen: tuple[int, int] | None,
) -> list[_ScoredNode]:
    if not candidate.ocr_near or not ocr_nodes:
        return []

    expected = _norm(candidate.ocr_near)
    labels = [
        node
        for node in ocr_nodes
        if expected
        and expected in _norm(_node_text(node))
        and _region_matches(node.bounds, candidate.region, screen)
    ]
    if not labels:
        return []

    if not candidate.target_class and not candidate.class_name:
        return [
            _ScoredNode(
                label,
                0.88,
                "ocr_near text match",
                "ocr_near",
                None,
                _bounds_with_offset(label.bounds, candidate.tap_offset),
            )
            for label in labels
        ]

    target_class = candidate.target_class or candidate.class_name
    target_nodes = [
        node
        for node in nodes
        if target_class
        and _node_class(node) == target_class
        and node.bounds
        and _region_matches(node.bounds, candidate.region, screen)
    ]
    scored: list[_ScoredNode] = []
    for target in target_nodes:
        nearest_label = min(
            labels,
            key=lambda label: _distance(target.bounds, label.bounds),
            default=None,
        )
        if nearest_label is None:
            continue
        nearest = _distance(target.bounds, nearest_label.bounds)
        if not math.isfinite(nearest):
            continue
        score = max(0.0, 0.84 - min(nearest, 800.0) / 4000.0)
        label_center = _center(nearest_label.bounds)
        target_center = _center(target.bounds)
        if label_center and target_center:
            vertical_delta = abs(label_center[1] - target_center[1])
            if vertical_delta <= 70:
                score += 0.06
            elif vertical_delta > 120:
                score -= 0.08
        if score < 0.55:
            continue
        selector = _node_selector(target)
        if selector is None and not candidate.allow_coordinate_fallback:
            continue
        scored.append(
            _ScoredNode(
                target,
                score,
                "ocr_near target_class match",
                "ocr_near",
                selector,
                _bounds_with_offset(
                    target.bounds,
                    candidate.tap_offset if selector is None else None,
                ),
            )
        )
    return scored


def _score_candidate(
    nodes: list[HierarchyNode],
    candidate: LocatorCandidate,
    screen: tuple[int, int] | None,
    *,
    ocr_nodes: list[HierarchyNode] | None = None,
) -> list[_ScoredNode]:
    scored = _score_direct_candidate(nodes, candidate, screen)
    scored.extend(_score_text_near_candidate(nodes, candidate, screen))
    scored.extend(_score_ocr_near_candidate(nodes, ocr_nodes or [], candidate, screen))
    return scored


def resolve_semantic_locator(
    profile: AppAutomationProfile,
    locator_name: str,
    hierarchy_xml: str,
    *,
    screen: tuple[int, int] | None = None,
    snapshot: HierarchySnapshot | None = None,
    ocr_results: list[dict[str, Any]] | None = None,
) -> LocatorResolution:
    """Resolve a named semantic locator against a u2 hierarchy dump."""
    locator = profile.semantic_locators.get(locator_name)
    if locator is None:
        return LocatorResolution(False, locator_name, 0.0, "unknown locator", "none", 0)
    if snapshot is None:
        try:
            snapshot = build_hierarchy_snapshot(hierarchy_xml)
        except XML_PARSE_ERRORS as exc:
            return LocatorResolution(False, locator_name, 0.0, f"invalid hierarchy xml: {exc}", "none", 0)
    nodes = snapshot.nodes
    ocr_nodes = build_ocr_snapshot(ocr_results).nodes if ocr_results is not None else []
    scored: list[_ScoredNode] = []
    for candidate in locator.candidates:
        scored.extend(_score_candidate(nodes, candidate, screen, ocr_nodes=ocr_nodes))
    scored.sort(key=lambda item: item.score, reverse=True)
    if not scored:
        return LocatorResolution(False, locator_name, 0.0, "no candidates matched", "none", 0)

    best = scored[0]
    if best.score < locator.min_score:
        return LocatorResolution(False, locator_name, best.score, "best candidate below min_score", best.fallback_level, len(scored), best.bounds, best.selector)

    if _is_ambiguous(scored, locator):
        return LocatorResolution(False, locator_name, best.score, "ambiguous candidates", best.fallback_level, len(scored), best.bounds, best.selector)

    return LocatorResolution(True, locator_name, best.score, best.reason, best.fallback_level, len(scored), best.bounds, best.selector)


def _is_ambiguous(scored: list[_ScoredNode], locator: SemanticLocator) -> bool:
    if locator.allow_ambiguous or len(scored) < 2:
        return False
    best, second = scored[0], scored[1]
    if best.score < locator.min_score or second.score < locator.min_score:
        return False
    if best.selector == second.selector and best.bounds == second.bounds:
        return False
    threshold = (
        0.12
        if best.fallback_level in {"text_near", "ocr_near"}
        or second.fallback_level in {"text_near", "ocr_near"}
        else 0.03
    )
    return abs(best.score - second.score) < threshold
