
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


def parse_xml(xml_str: str) -> Any:
  
    if _lxml is None:
        return _std_et.fromstring(xml_str)

    xml_bytes = xml_str.encode("utf-8") if isinstance(xml_str, str) else xml_str
    try:
        return _lxml.fromstring(xml_bytes)
    except _lxml.XMLSyntaxError:
        parser = _lxml.XMLParser(recover=True, huge_tree=False)
        return _lxml.fromstring(xml_bytes, parser=parser)


def using_lxml() -> bool:
    """Return True when lxml is available and active."""
    return _lxml is not None
