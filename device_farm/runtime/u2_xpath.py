"""
u2_xpath.py — uiautomator2-compatible XPath normalization and helpers.

Mirrors openatx/uiautomator2 ``strict_xpath`` / ``XPath`` sugar so callers can pass
``@com.example:id/foo``, bare text, ``%contains%``, etc.
"""
from __future__ import annotations

import re
from typing import Any, Optional, Tuple


class XPathElementNotFoundError(RuntimeError):
    """Raised when XPathSelector.get() / click(timeout=…) cannot find a match."""

    def __init__(self, selector: Any) -> None:
        self.selector = selector
        expr = getattr(selector, "_value", None) or selector
        super().__init__(f"XPathElementNotFoundError: {expr!r}")


def string_quote(s: str) -> str:
    return repr(s)


def normalize_u2_xpath(xpath: str) -> str:
    """
    Convert u2 shorthand xpath to a full XPath expression (ElementTree-safe).

    Supported forms (aligned with uiautomator2 ``strict_xpath``):
    - ``@resource-id`` → ``//*[@resource-id='…']``
    - ``^pattern`` → text/content-desc/resource-id regex match (literal fallback)
    - ``%substring%`` → contains on text or content-desc
    - ``%suffix`` / ``prefix%`` → ends-with / starts-with
    - bare string → matches text, content-desc, or resource-id
    - already absolute/relative xpath → unchanged (after strip)
    """
    orig = xpath
    q = (xpath or "").strip()
    if not q:
        return q

    if q.lstrip("(").startswith("/"):
        return q.rstrip("/")

    if q.startswith("@"):
        return f"//*[@resource-id={string_quote(q[1:])}]"

    if q.startswith("^"):
        # ElementTree has no re: namespace — literal match on text / content-desc / resource-id.
        pat = string_quote(q[1:])
        return (
            f"//*[@text={pat} or @content-desc={pat} or @resource-id={pat}]"
        )

    if q.startswith("%") and q.endswith("%") and len(q) > 2:
        inner = string_quote(q[1:-1])
        return f"//*[contains(@text, {inner}) or contains(@content-desc, {inner})]"

    if q.startswith("%"):
        text = string_quote(q[1:])
        return f"//*[contains(@text, {text}) or contains(@content-desc, {text})]"

    if q.endswith("%"):
        text = string_quote(q[:-1])
        return (
            f"//*[starts-with(@text, {text}) or starts-with(@content-desc, {text})]"
        )

    lit = string_quote(q)
    return f"//*[@text={lit} or @content-desc={lit} or @resource-id={lit}]"


def parse_xpath_eid(eid: str) -> Tuple[str, int]:
    """
    Parse internal eid formats:
    - ``xpath::{expr}``
    - ``xpath::{index}::{expr}``
    """
    if not eid.startswith("xpath::"):
        raise ValueError(f"not an xpath eid: {eid!r}")
    rest = eid[7:]
    if "::" in rest:
        idx_s, _, expr = rest.partition("::")
        if idx_s.isdigit():
            return expr, int(idx_s)
    return rest, 0


def format_xpath_eid(expr: str, index: int = 0) -> str:
    if index <= 0:
        return f"xpath::{expr}"
    return f"xpath::{index}::{expr}"


def node_bounds(node: Any) -> Optional[dict]:
    bounds_str = (node.get("bounds") or "") if node is not None else ""
    nums = [int(n) for n in re.findall(r"-?\d+", bounds_str)]
    if len(nums) != 4:
        return None
    return {"left": nums[0], "top": nums[1], "right": nums[2], "bottom": nums[3]}


def node_center(bounds: dict) -> Tuple[int, int]:
    cx = (bounds["left"] + bounds["right"]) // 2
    cy = (bounds["top"] + bounds["bottom"]) // 2
    return cx, cy
