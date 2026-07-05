"""Tests for chained scenario selector resolution in u2_executor."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from relay.u2_executor import _resolve_spec, _op_click_spec, _op_exists_spec


def test_resolve_spec_flat():
    dev = MagicMock()
    anchor = MagicMock()
    dev.return_value = anchor
    obj = _resolve_spec(dev, {"by": "text", "value": "OK"})
    dev.assert_called_once_with(text="OK")
    assert obj is anchor


def test_resolve_spec_description_startswith_by_value():
    dev = MagicMock()
    anchor = MagicMock()
    dev.return_value = anchor
    obj = _resolve_spec(dev, {"by": "descriptionStartsWith", "value": "Nút Thích"})
    dev.assert_called_once_with(descriptionStartsWith="Nút Thích")
    assert obj is anchor


def test_resolve_spec_description_startswith_legacy_case():
    dev = MagicMock()
    anchor = MagicMock()
    dev.return_value = anchor
    obj = _resolve_spec(dev, {"by": "descriptionStartswith", "value": "Nút Thích"})
    dev.assert_called_once_with(descriptionStartsWith="Nút Thích")
    assert obj is anchor


def test_resolve_spec_relative_chain():
    dev = MagicMock()
    anchor = MagicMock()
    switch = MagicMock()
    anchor.right.return_value = switch
    dev.return_value = anchor
    spec = {
        "by": "text",
        "value": "Wi-Fi",
        "chain": {
            "op": "relative",
            "direction": "right",
            "target": {"className": "android.widget.Switch"},
        },
    }
    obj = _resolve_spec(dev, spec)
    anchor.right.assert_called_once_with(className="android.widget.Switch")
    assert obj is switch


def test_op_click_spec():
    dev = MagicMock()
    sel = MagicMock()
    sel.click_exists.return_value = True
    dev.return_value = sel
    assert _op_click_spec(dev, {"spec": {"text": "OK", "by": "text", "value": "OK"}, "timeout": 1.0}) is True


def test_op_exists_spec():
    dev = MagicMock()
    sel = MagicMock()
    sel.exists.return_value = True
    dev.return_value = sel
    assert _op_exists_spec(dev, {"spec": {"by": "text", "value": "Here"}, "timeout": 0.5}) is True
