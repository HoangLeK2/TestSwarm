"""Tests for u2-compatible XPath normalization and JSON-RPC XPathSelector."""
from __future__ import annotations

import unittest
from unittest.mock import Mock

from runtime.u2_xpath import (
    XPathElementNotFoundError,
    format_xpath_eid,
    normalize_u2_xpath,
    parse_xpath_eid,
)
from runtime.transports.u2_jsonrpc import U2JsonRpcClient, _U2JsonRpcElement


def _make_client() -> U2JsonRpcClient:
    c = U2JsonRpcClient(host="127.0.0.1", port=9008, timeout=5.0)
    c._session = Mock()
    return c


_HIERARCHY = """<?xml version="1.0" encoding="UTF-8"?>
<hierarchy>
  <node index="0" text="Home" bounds="[0,0][100,50]" resource-id="btn_home"/>
  <node index="1" text="Next" bounds="[0,60][100,110]"/>
</hierarchy>"""


class TestNormalizeU2Xpath(unittest.TestCase):

    def test_at_resource_id(self):
        self.assertEqual(
            normalize_u2_xpath("@com.example:id/foo"),
            "//*[@resource-id='com.example:id/foo']",
        )

    def test_bare_text(self):
        xp = normalize_u2_xpath("Login")
        self.assertIn("@text='Login'", xp)
        self.assertIn("@content-desc='Login'", xp)

    def test_contains_percent(self):
        xp = normalize_u2_xpath("%Save%")
        self.assertIn("contains(@text", xp)

    def test_absolute_unchanged(self):
        raw = "//*[@text='OK']"
        self.assertEqual(normalize_u2_xpath(raw), raw)


class TestXpathEid(unittest.TestCase):

    def test_plain(self):
        self.assertEqual(parse_xpath_eid("xpath:://*[@text='a']"), ("//*[@text='a']", 0))

    def test_indexed(self):
        eid = format_xpath_eid("//*[@text='a']", 2)
        expr, idx = parse_xpath_eid(eid)
        self.assertEqual(idx, 2)
        self.assertEqual(expr, "//*[@text='a']")


class TestJsonRpcXpathSelector(unittest.TestCase):

    def setUp(self):
        self.client = _make_client()
        self.client.page_source = Mock(return_value=_HIERARCHY)

    def test_exists_and_count(self):
        sl = self.client.xpath("Home")
        self.assertTrue(sl.exists)
        self.assertGreaterEqual(sl.count, 1)

    def test_click_exists(self):
        sl = self.client.xpath("Home")
        self.assertTrue(sl.click_exists(timeout=0))

    def test_click_exists_missing(self):
        sl = self.client.xpath("Missing")
        self.assertFalse(sl.click_exists(timeout=0))

    def test_get_raises_when_missing(self):
        sl = self.client.xpath("Missing")
        with self.assertRaises(XPathElementNotFoundError):
            sl.get(timeout=0)

    def test_get_text(self):
        sl = self.client.xpath("@btn_home")
        self.assertEqual(sl.get_text(), "Home")

    def test_getitem_second_match(self):
        sl = self.client.xpath("//*[@bounds]")
        second = sl[1]
        self.assertEqual(second.get(timeout=0).text, "Next")

    def test_click_with_timeout_calls_rpc(self):
        self.client._rpc = Mock()
        self.client.xpath("Home").click(timeout=0)
        self.client._rpc.assert_called()

    def test_set_text_sends_keys(self):
        self.client._rpc = Mock(return_value={"text": ""})
        self.client.clear_text = Mock()
        self.client.send_keys = Mock()
        self.client.xpath("Home").set_text("hello")
        self.client.send_keys.assert_called_once_with("hello")

    def test_at_sugar_normalized(self):
        sl = self.client.xpath("@btn_home")
        self.assertIn("resource-id", sl._value)


if __name__ == "__main__":
    unittest.main()
