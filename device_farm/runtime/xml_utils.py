
from __future__ import annotations

import xml.etree.ElementTree as _std_et
from typing import Any

try:
    from lxml import etree as _lxml
except ImportError:
    _lxml = None

if _lxml is not None:
    XML_PARSE_ERRORS = (_std_et.ParseError, _lxml.XMLSyntaxError)
else:
    XML_PARSE_ERRORS = (_std_et.ParseError,)

# Boolean attributes whose default value is "false".
# When the value IS "false" we can drop the attribute entirely — readers that
# need a truthy check already handle missing-attribute as false.
_BOOL_ATTRS_DEFAULT_FALSE = frozenset({
    "checkable", "checked", "clickable", "enabled",
    "focusable", "focused", "long-clickable", "password",
    "scrollable", "selected",
})

# String attributes that carry no information when empty.
_EMPTY_STRING_ATTRS = frozenset({
    "text", "resource-id", "content-desc", "package",
    # UIAutomator2-specific flag — always "true" when present, never needed downstream
    "NAF",
})


def parse_xml(xml_str: str) -> Any:

    if _lxml is None:
        return _std_et.fromstring(xml_str)

    xml_bytes = xml_str.encode("utf-8") if isinstance(xml_str, str) else xml_str
    try:
        return _lxml.fromstring(xml_bytes)
    except _lxml.XMLSyntaxError:
        parser = _lxml.XMLParser(recover=True, huge_tree=False)
        return _lxml.fromstring(xml_bytes, parser=parser)


def trim_hierarchy_xml(xml_str: str) -> str:
    """Strip redundant attributes from a UIAutomator2 hierarchy XML string.

    UIAutomator2's dumpWindowHierarchy writes every boolean attribute as
    "false" and every string attribute as "" for the vast majority of nodes.
    These defaults account for ~50% of the raw XML size and add no information.

    This function:
    - Removes boolean attributes whose value is "false" (default — callers
      that need a truthy check already treat missing-attribute as false).
    - Removes string attributes that are empty ("") or the "NAF" flag.
    - Preserves tree structure, ``bounds``, ``class``, and ``index`` intact
      so xpath selectors and bounds-based logic continue to work.

    Returns the trimmed XML string.  Falls back to the original string if
    lxml is not installed or parsing fails (never raises).
    """
    if not xml_str or _lxml is None:
        return xml_str
    try:
        xml_bytes = xml_str.encode("utf-8") if isinstance(xml_str, str) else xml_str
        try:
            root = _lxml.fromstring(xml_bytes)
        except _lxml.XMLSyntaxError:
            parser = _lxml.XMLParser(recover=True, huge_tree=False)
            root = _lxml.fromstring(xml_bytes, parser=parser)

        for node in root.iter():
            attrib = node.attrib
            to_delete = []
            for attr, val in attrib.items():
                if attr in _BOOL_ATTRS_DEFAULT_FALSE and val == "false":
                    to_delete.append(attr)
                elif attr in _EMPTY_STRING_ATTRS and (not val or val == "true"):
                    # empty string → no info; NAF="true" → not needed downstream
                    to_delete.append(attr)
            for attr in to_delete:
                del attrib[attr]

        return _lxml.tostring(root, encoding="unicode", xml_declaration=False)
    except Exception:
        return xml_str  # safe fallback


def using_lxml() -> bool:
    """Return True when lxml is available and active."""
    return _lxml is not None
