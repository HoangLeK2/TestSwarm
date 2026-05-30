from __future__ import annotations

from services.activity_presenter import _looks_like_uuid, _stored_device_label


def test_stored_device_label_reads_details():
    assert _stored_device_label({"device_label": "vivo V2352A"}) == "vivo V2352A"
    assert _stored_device_label({}) is None


def test_looks_like_uuid_detects_device_ids():
    assert _looks_like_uuid("89294f75-c2f9-4a7a-91f5-cb1c186b1a94") is True
    assert _looks_like_uuid("10AE7S00HD002JK") is False
