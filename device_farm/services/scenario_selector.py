"""
scenario_selector.py — Normalize and resolve scenario selector specs.

Supports nested ``selector`` objects with optional ``conditions``, ``instance``,
and uiautomator2 ``chain`` ops (child/sibling/relative/child_by_text).
Legacy flat ``by``/``value`` on steps remain readable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from runtime.u2_xpath import normalize_u2_xpath

# Mask bits aligned with u2_jsonrpc (android-uiautomator-server Selector protocol)
_MASK_TEXT = 0x01
_MASK_TEXT_CONTAINS = 0x02
_MASK_TEXT_MATCHES = 0x04
_MASK_TEXT_STARTSWITH = 0x08
_MASK_CLASS_NAME = 0x10
_MASK_DESCRIPTION = 0x40
_MASK_DESCRIPTION_CONTAINS = 0x80
_MASK_DESCRIPTION_STARTSWITH = 0x200
_MASK_CHECKABLE = 0x400
_MASK_CHECKED = 0x800
_MASK_CLICKABLE = 0x1000
_MASK_SCROLLABLE = 0x4000
_MASK_ENABLED = 0x8000
_MASK_FOCUSED = 0x20000
_MASK_SELECTED = 0x40000
_MASK_PACKAGE_NAME = 0x80000
_MASK_RESOURCE_ID = 0x200000
_MASK_INDEX = 0x800000
_MASK_INSTANCE = 0x1000000

_BY_TO_RPC_FIELD: Dict[str, Tuple[str, int]] = {
    "text": ("text", _MASK_TEXT),
    "textContains": ("textContains", _MASK_TEXT_CONTAINS),
    "textMatches": ("textMatches", _MASK_TEXT_MATCHES),
    "textStartsWith": ("textStartsWith", _MASK_TEXT_STARTSWITH),
    "resource-id": ("resourceId", _MASK_RESOURCE_ID),
    "id": ("resourceId", _MASK_RESOURCE_ID),
    "resourceId": ("resourceId", _MASK_RESOURCE_ID),
    "class name": ("className", _MASK_CLASS_NAME),
    "className": ("className", _MASK_CLASS_NAME),
    "description": ("description", _MASK_DESCRIPTION),
    "content-desc": ("description", _MASK_DESCRIPTION),
    "accessibility id": ("description", _MASK_DESCRIPTION),
    "descriptionContains": ("descriptionContains", _MASK_DESCRIPTION_CONTAINS),
    "descriptionStartsWith": ("descriptionStartsWith", _MASK_DESCRIPTION_STARTSWITH),
    "descriptionStartswith": ("descriptionStartsWith", _MASK_DESCRIPTION_STARTSWITH),
    "package": ("packageName", _MASK_PACKAGE_NAME),
    "packageName": ("packageName", _MASK_PACKAGE_NAME),
}

_BOOL_FIELDS: Dict[str, int] = {
    "checkable": _MASK_CHECKABLE,
    "checked": _MASK_CHECKED,
    "clickable": _MASK_CLICKABLE,
    "scrollable": _MASK_SCROLLABLE,
    "enabled": _MASK_ENABLED,
    "focused": _MASK_FOCUSED,
    "selected": _MASK_SELECTED,
}

_SELECTOR_STEP_TYPES = frozenset({
    "tap", "tap_selector", "wait_element", "assert_element",
    "input_selector", "long_tap_selector", "scroll_to", "if_element",
})


@dataclass
class ScenarioSelectorSpec:
    by: str = "text"
    value: str = ""
    conditions: Dict[str, Any] = field(default_factory=dict)
    instance: Optional[int] = None
    index: Optional[int] = None
    xpath: Optional[str] = None
    chain: Optional[Dict[str, Any]] = None
    bounds: Optional[Any] = None

    def is_empty(self) -> bool:
        return not (self.value or "").strip() and not self.xpath and not self.chain

    def primary_by_value(self) -> Tuple[str, str]:
        if self.xpath:
            return "xpath", self.xpath
        return self.by, self.value


def _coerce_conditions(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if v is not None}


def _parse_selector_dict(raw: Dict[str, Any]) -> ScenarioSelectorSpec:
    by = str(raw.get("by") or "text").strip()
    value = str(raw.get("value") or "").strip()
    conditions = _coerce_conditions(raw.get("conditions"))
    inst = raw.get("instance")
    idx = raw.get("index")
    xpath = raw.get("xpath")
    if xpath is not None:
        xpath = normalize_u2_xpath(str(xpath).strip()) or None
    elif by == "xpath" and value:
        value = normalize_u2_xpath(value)
    chain = raw.get("chain")
    if isinstance(chain, list) and chain:
        chain = chain[0] if isinstance(chain[0], dict) else None
    elif not isinstance(chain, dict):
        chain = None
    return ScenarioSelectorSpec(
        by=by,
        value=value,
        conditions=conditions,
        instance=int(inst) if inst is not None else None,
        index=int(idx) if idx is not None else None,
        xpath=xpath,
        chain=chain,
        bounds=raw.get("bounds"),
    )


def _xpath_uses_volatile_bounds(value: str) -> bool:
    return bool(value) and "@bounds=" in value


def normalize_step_selector(step: Dict[str, Any]) -> Optional[ScenarioSelectorSpec]:
    """Extract selector from a scenario step (nested or legacy flat)."""
    if not isinstance(step, dict):
        return None
    nested = step.get("selector")
    if isinstance(nested, dict) and nested:
        spec = _parse_selector_dict(nested)
        if not spec.is_empty():
            if spec.by == "xpath" and _xpath_uses_volatile_bounds(spec.value or ""):
                import logging
                logging.getLogger(__name__).warning(
                    "selector xpath uses volatile @bounds (re-pick from screen or use fallback): %r",
                    (spec.value or "")[:120],
                )
            return spec
    by = str(step.get("by") or "").strip()
    value = str(step.get("value") or "").strip()
    if by and value:
        return ScenarioSelectorSpec(by=by, value=value)
    return None


def normalize_element_condition(cond: Dict[str, Any]) -> Optional[ScenarioSelectorSpec]:
    if not isinstance(cond, dict):
        return None
    if "selector" in cond and isinstance(cond["selector"], dict):
        spec = _parse_selector_dict(cond["selector"])
        if not spec.is_empty():
            return spec
    by = str(cond.get("by") or "text").strip()
    value = str(cond.get("value") or "").strip()
    if value:
        return ScenarioSelectorSpec(by=by, value=value)
    return None


def get_step_fallback(step: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    fb = step.get("fallback")
    if isinstance(fb, dict):
        rx = fb.get("rx")
        ry = fb.get("ry")
        if rx is not None and ry is not None:
            return float(rx), float(ry)
    rx = step.get("fallback_rx")
    ry = step.get("fallback_ry")
    if rx is not None and ry is not None:
        return float(rx), float(ry)
    return None, None


def spec_has_chain(spec: ScenarioSelectorSpec) -> bool:
    return bool(spec.chain and isinstance(spec.chain, dict) and spec.chain.get("op"))


def spec_to_agent_payload(spec: ScenarioSelectorSpec) -> Dict[str, Any]:
    """JSON-serializable payload for agent-boot u2_executor."""
    out: Dict[str, Any] = {
        "by": spec.by,
        "value": spec.value,
    }
    if spec.conditions:
        out["conditions"] = dict(spec.conditions)
    if spec.instance is not None:
        out["instance"] = spec.instance
    if spec.index is not None:
        out["index"] = spec.index
    if spec.xpath:
        out["xpath"] = spec.xpath
    if spec.chain:
        out["chain"] = spec.chain
    return out


def _apply_field(sel: Dict[str, Any], mask: int, field: str, value: Any, m: int) -> Tuple[Dict[str, Any], int]:
    sel[field] = value
    return sel, mask | m


def spec_to_rpc_selector(spec: ScenarioSelectorSpec) -> Dict[str, Any]:
    """Build uiautomator2 JSON-RPC selector dict (mask + fields)."""
    if spec.xpath or spec.by == "xpath":
        # XPath uses separate code path; return marker for callers
        return {"_xpath": spec.xpath or spec.value}

    conditions: Dict[str, Any] = dict(spec.conditions)
    by, value = spec.by, spec.value
    if by and value and by not in ("xpath",):
        # Merge primary by/value into conditions unless already present
        field_key = _BY_TO_RPC_FIELD.get(by, (by, 0))[0]
        if field_key not in conditions and by not in conditions:
            conditions[by] = value

    mask = 0
    sel: Dict[str, Any] = {}

    for key, val in conditions.items():
        if val is None:
            continue
        if key in _BOOL_FIELDS and isinstance(val, bool):
            if val:
                field_name = key
                sel, mask = _apply_field(sel, mask, field_name, True, _BOOL_FIELDS[key])
            continue
        if key in ("instance", "index"):
            try:
                sel[key] = int(val)
                mask |= _MASK_INSTANCE if key == "instance" else _MASK_INDEX
            except (TypeError, ValueError):
                pass
            continue
        if key in _BY_TO_RPC_FIELD:
            field_name, m = _BY_TO_RPC_FIELD[key]
            sel, mask = _apply_field(sel, mask, field_name, val, m)
        elif key in _BOOL_FIELDS:
            if val:
                sel, mask = _apply_field(sel, mask, key, True, _BOOL_FIELDS[key])

    if spec.instance is not None:
        sel["instance"] = int(spec.instance)
        mask |= _MASK_INSTANCE
    if spec.index is not None:
        sel["index"] = int(spec.index)
        mask |= _MASK_INDEX

    if not sel:
        sel, mask = _apply_field(sel, mask, "text", value or "", _MASK_TEXT)
    sel["mask"] = mask
    return sel


def spec_eid(spec: ScenarioSelectorSpec) -> str:
    by, val = spec.primary_by_value()
    return f"{by}::{val}"


def _target_to_kwargs(target: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(target, dict):
        return {}
    t_spec = _parse_selector_dict(target) if target.get("by") or target.get("value") else None
    if t_spec and not t_spec.is_empty():
        rpc = spec_to_rpc_selector(t_spec)
        if "_xpath" in rpc:
            return {"xpath": rpc["_xpath"]}
        kwargs = {k: v for k, v in rpc.items() if k != "mask"}
        return kwargs
    cond = _coerce_conditions(target.get("conditions"))
    kwargs: Dict[str, Any] = {}
    for k, v in cond.items():
        if k in _BY_TO_RPC_FIELD:
            kwargs[_BY_TO_RPC_FIELD[k][0]] = v
        elif k in ("className", "resourceId", "text", "description"):
            kwargs[k] = v
    for k in ("className", "resourceId", "text", "description", "clickable"):
        if k in target and target[k] is not None and k not in kwargs:
            kwargs[k] = target[k]
    return kwargs


def compile_chain_to_xpath(spec: ScenarioSelectorSpec) -> Optional[str]:
    """Best-effort XPath for chain specs when agent-boot is unavailable."""
    if not spec_has_chain(spec):
        if spec.by == "xpath" or spec.xpath:
            return spec.xpath or spec.value
        return None

    chain = spec.chain or {}
    op = str(chain.get("op") or "").strip()
    anchor_xpath = _anchor_xpath(spec)
    if not anchor_xpath:
        return None

    if op == "relative":
        direction = str(chain.get("direction") or "right").strip().lower()
        target = chain.get("target") or {}
        t_kw = _target_to_kwargs(target)
        cls = t_kw.get("className") or t_kw.get("class")
        if cls:
            # Simplified: following sibling with class (not true geometric relative)
            return f"{anchor_xpath}/following-sibling::*[contains(@class,'{cls.split('.')[-1]}')][1]"
        text = t_kw.get("text")
        if text:
            escaped = text.replace("'", "\\'")
            return f"{anchor_xpath}/following-sibling::*[@text='{escaped}'][1]"
        return None

    if op == "child":
        target = chain.get("target") or {}
        t_kw = _target_to_kwargs(target)
        parts = [anchor_xpath]
        if t_kw.get("resourceId"):
            parts.append(f"//*[@resource-id='{t_kw['resourceId']}']")
        elif t_kw.get("text"):
            escaped = str(t_kw["text"]).replace("'", "\\'")
            parts.append(f"//*[@text='{escaped}']")
        elif t_kw.get("className"):
            parts.append(f"//*[@class='{t_kw['className']}']")
        return "/".join(parts) if len(parts) > 1 else None

    if op == "sibling":
        target = chain.get("target") or {}
        t_kw = _target_to_kwargs(target)
        if t_kw.get("text"):
            escaped = str(t_kw["text"]).replace("'", "\\'")
            return f"{anchor_xpath}/following-sibling::*[@text='{escaped}'][1]"
        return None

    if op == "child_by_text":
        text = str(chain.get("text") or "").replace("'", "\\'")
        return f"{anchor_xpath}//*[@text='{text}'][1]"

    if op == "child_by_description":
        desc = str(chain.get("description") or "").replace("'", "\\'")
        return f"{anchor_xpath}//*[@content-desc='{desc}'][1]"

    return None


def _anchor_xpath(spec: ScenarioSelectorSpec) -> Optional[str]:
    if spec.xpath or spec.by == "xpath":
        xp = spec.xpath or spec.value
        return xp if xp.startswith("/") else f"//*[@text='{xp.replace(chr(39), chr(92)+chr(39))}']"
    by, value = spec.by, spec.value
    escaped = value.replace("'", "\\'")
    if by in ("text",):
        xp = f"//*[@text='{escaped}']"
    elif by in ("resource-id", "id", "resourceId"):
        xp = f"//*[@resource-id='{escaped}']"
    elif by in ("description", "content-desc"):
        xp = f"//*[@content-desc='{escaped}']"
    elif by in ("class name", "className"):
        xp = f"//*[@class='{escaped}']"
    else:
        xp = f"//*[@text='{escaped}']"
    if spec.instance is not None and spec.instance > 0:
        xp = f"({xp})[{int(spec.instance) + 1}]"
    return xp


def selector_summary(spec: ScenarioSelectorSpec) -> str:
    by, val = spec.primary_by_value()
    parts = [f"{by}={val!r}"]
    if spec.conditions:
        parts.append(f"conditions={spec.conditions!r}")
    if spec.instance is not None:
        parts.append(f"instance={spec.instance}")
    if spec_has_chain(spec):
        parts.append(f"chain={spec.chain!r}")
    return " ".join(parts)
