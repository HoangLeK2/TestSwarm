"""Unit tests for tasks/scenario/utils.py helper functions."""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../../../'))

import time
import threading
from unittest.mock import MagicMock, patch, call
import pytest

from tasks.scenario.utils import (
    _normalize_xml,
    _xml_has_element,
    _wait_for_element,
    _retry_find_element,
    _get_implicit_wait_config,
    _evaluate_condition,
    _eval_ru_condition,
    _wait_element_gone,
    _IW_DEFAULT_TIMEOUT,
    _IW_DEFAULT_POLL,
    ScenarioCancelled,
)


# ── _normalize_xml ────────────────────────────────────────────────────────────

class TestNormalizeXml:
    def test_strips_volatile_attrs(self):
        xml = '<node bounds="[0,0][100,100]" index="3" text="hello"/>'
        result = _normalize_xml(xml)
        assert 'bounds' not in result
        assert 'index' not in result
        assert 'text="hello"' in result

    def test_stable_hash_across_calls(self):
        xml = '<node text="foo" focused="true"/>'
        r1 = _normalize_xml(xml)
        xml2 = '<node text="foo" focused="false"/>'
        r2 = _normalize_xml(xml2)
        assert r1 == r2  # focused stripped


# ── _xml_has_element ──────────────────────────────────────────────────────────

class TestXmlHasElement:
    XML = '<hierarchy><node text="Hello" resource-id="com.app:id/btn" content-desc="Close"/></hierarchy>'

    def test_by_text_found(self):
        assert _xml_has_element(self.XML, "text", "Hello") is True

    def test_by_text_not_found(self):
        assert _xml_has_element(self.XML, "text", "Missing") is False

    def test_by_resource_id(self):
        assert _xml_has_element(self.XML, "resource-id", "com.app:id/btn") is True

    def test_by_content_desc(self):
        assert _xml_has_element(self.XML, "content-desc", "Close") is True

    def test_empty_xml(self):
        assert _xml_has_element("", "text", "Hello") is False

    def test_empty_value(self):
        assert _xml_has_element(self.XML, "text", "") is False

    def test_malformed_xml(self):
        assert _xml_has_element("<bad xml", "text", "x") is False


# ── _get_implicit_wait_config ─────────────────────────────────────────────────

class TestGetImplicitWaitConfig:
    def test_defaults_when_no_config(self):
        t, p = _get_implicit_wait_config({}, {})
        assert t == _IW_DEFAULT_TIMEOUT
        assert p == _IW_DEFAULT_POLL

    def test_step_overrides_scenario(self):
        t, p = _get_implicit_wait_config({"implicit_wait": 5.0}, {"implicit_wait": 20.0})
        assert t == 5.0

    def test_number_uses_default_poll(self):
        t, p = _get_implicit_wait_config({"implicit_wait": 15}, {})
        assert t == 15.0
        assert p == _IW_DEFAULT_POLL

    def test_dict_config(self):
        t, p = _get_implicit_wait_config({"implicit_wait": {"timeout": 8, "poll": 0.2}}, {})
        assert t == 8.0
        assert p == 0.2

    def test_clamps_to_max(self):
        t, p = _get_implicit_wait_config({"implicit_wait": 9999}, {})
        assert t == 60.0

    def test_clamps_to_min(self):
        t, p = _get_implicit_wait_config({"implicit_wait": 0.0}, {})
        assert t == 0.1


# ── _wait_for_element ─────────────────────────────────────────────────────────

class TestWaitForElement:
    def test_returns_none_when_u2_is_none(self):
        result = _wait_for_element(None, "text", "foo", timeout=0.1)
        assert result is None

    def test_non_xpath_returns_element(self):
        u2 = MagicMock()
        u2.find_element.return_value = "element_id"
        u2.find_element_with_bounds.side_effect = Exception("no bounds")
        result = _wait_for_element(u2, "text", "Login", timeout=1.0)
        assert result == "element_id"

    def test_non_xpath_returns_bounds_when_available(self):
        u2 = MagicMock()
        u2.find_element.return_value = "eid"
        u2.find_element_with_bounds.return_value = {"eid": "eid", "bounds": {}}
        result = _wait_for_element(u2, "text", "Login", timeout=1.0)
        assert isinstance(result, dict)

    def test_non_xpath_returns_none_on_not_found(self):
        u2 = MagicMock()
        u2.find_element.return_value = None
        result = _wait_for_element(u2, "text", "Missing", timeout=0.2)
        assert result is None

    def test_xpath_times_out(self):
        u2 = MagicMock()
        u2.find_element.return_value = None
        start = time.monotonic()
        result = _wait_for_element(u2, "xpath", "//node", timeout=0.3, poll=0.1)
        elapsed = time.monotonic() - start
        assert result is None
        assert elapsed < 1.0

    def test_xpath_aborts_on_consecutive_errors(self):
        u2 = MagicMock()
        u2.find_element.side_effect = Exception("connection error")
        result = _wait_for_element(u2, "xpath", "//node", timeout=5.0, poll=0.01)
        assert result is None
        # Should abort after 3 errors, not wait full 5s
        assert u2.find_element.call_count == 3


# ── _evaluate_condition ───────────────────────────────────────────────────────

class TestEvaluateCondition:
    XML_WITH_BUTTON = '<hierarchy><node text="OK"/></hierarchy>'
    XML_EMPTY = '<hierarchy></hierarchy>'

    def _device(self, xml):
        d = MagicMock()
        d.hierarchy_xml.return_value = xml
        return d

    def test_element_exists_true(self):
        d = self._device(self.XML_WITH_BUTTON)
        result = _evaluate_condition(d, {"type": "element_exists", "by": "text", "value": "OK"}, {})
        assert result is True

    def test_element_exists_false(self):
        d = self._device(self.XML_EMPTY)
        result = _evaluate_condition(d, {"type": "element_exists", "by": "text", "value": "Missing"}, {})
        assert result is False

    def test_element_not_exists(self):
        d = self._device(self.XML_EMPTY)
        result = _evaluate_condition(d, {"type": "element_not_exists", "by": "text", "value": "Missing"}, {})
        assert result is True

    def test_posts_count_gte_true(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "posts_count_gte", "count": 3}, {"posts": [1, 2, 3]})
        assert result is True

    def test_posts_count_gte_false(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "posts_count_gte", "count": 5}, {"posts": [1, 2]})
        assert result is False

    def test_posts_count_lt(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "posts_count_lt", "count": 5}, {"posts": [1, 2]})
        assert result is True

    def test_no_new_posts_below_threshold(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "no_new_posts", "threshold": 3}, {"_no_new_posts_streak": 2})
        assert result is False

    def test_no_new_posts_at_threshold(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "no_new_posts", "threshold": 3}, {"_no_new_posts_streak": 3})
        assert result is True

    def test_unknown_type_returns_false(self):
        d = MagicMock()
        result = _evaluate_condition(d, {"type": "unknown_condition"}, {})
        assert result is False


# ── _eval_ru_condition ────────────────────────────────────────────────────────

class TestEvalRuCondition:
    XML_WITH_DONE = '<hierarchy><node text="Done"/></hierarchy>'
    XML_EMPTY = '<hierarchy></hierarchy>'

    def _device(self, xml):
        d = MagicMock()
        d.hierarchy_xml.return_value = xml
        return d

    def _var_ctx(self, **overrides):
        vc = MagicMock()
        vc.resolve.side_effect = lambda val, **kwargs: str(val)
        return vc

    def test_element_exists_stop_condition(self):
        d = self._device(self.XML_WITH_DONE)
        vc = self._var_ctx()
        result = _eval_ru_condition(d, {"element_exists": {"by": "text", "value": "Done"}}, vc)
        assert result is True

    def test_element_not_exists_stop_condition(self):
        d = self._device(self.XML_EMPTY)
        vc = self._var_ctx()
        result = _eval_ru_condition(d, {"element_not_exists": {"by": "text", "value": "Loading"}}, vc)
        assert result is True

    def test_variable_equals_match(self):
        d = MagicMock()
        vc = MagicMock()
        vc.resolve.side_effect = lambda val, **kwargs: "10" if "MAX" in val else "10"
        result = _eval_ru_condition(d, {"variable_equals": {"name": "count", "value": "${MAX}"}}, vc)
        assert result is True

    def test_unknown_condition_returns_false(self):
        d = MagicMock()
        vc = self._var_ctx()
        result = _eval_ru_condition(d, {"unknown_key": {}}, vc)
        assert result is False


# ── _wait_element_gone ────────────────────────────────────────────────────────

class TestWaitElementGone:
    def test_returns_true_when_u2_is_none(self):
        from tasks.scenario.utils import _wait_element_gone
        assert _wait_element_gone(None, "text", "x") is True

    def test_element_already_gone(self):
        from tasks.scenario.utils import _wait_element_gone
        u2 = MagicMock(spec_set=["find_element"])  # no _wait_until_gone
        u2.find_element.return_value = None
        assert _wait_element_gone(u2, "text", "x", timeout=0.5) is True

    def test_element_gone_after_delay(self):
        from tasks.scenario.utils import _wait_element_gone
        u2 = MagicMock(spec_set=["find_element"])  # no _wait_until_gone
        call_count = [0]
        def side_effect(by, val, timeout=0):
            call_count[0] += 1
            return None if call_count[0] > 2 else "exists"
        u2.find_element.side_effect = side_effect
        assert _wait_element_gone(u2, "text", "x", timeout=2.0, poll=0.05) is True


# ── ScenarioCancelled ─────────────────────────────────────────────────────────

class TestScenarioCancelled:
    def test_is_exception(self):
        assert issubclass(ScenarioCancelled, Exception)

    def test_can_raise_and_catch(self):
        with pytest.raises(ScenarioCancelled):
            raise ScenarioCancelled("cancelled")
