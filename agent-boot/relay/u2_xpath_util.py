"""u2 xpath shorthand normalization (mirrors device_farm.runtime.u2_xpath)."""
from __future__ import annotations


def string_quote(s: str) -> str:
    return repr(s)


def normalize_u2_xpath(xpath: str) -> str:
    q = (xpath or "").strip()
    if not q:
        return q
    if q.lstrip("(").startswith("/"):
        return q.rstrip("/")
    if q.startswith("@"):
        return f"//*[@resource-id={string_quote(q[1:])}]"
    if q.startswith("^"):
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
