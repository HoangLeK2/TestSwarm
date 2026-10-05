from __future__ import annotations

from services.notification_service import (
    NotificationService,
    _enrich_device_event,
    device_event_label,
)


def test_device_event_label_prefers_brand_model():
    assert device_event_label(
        serial="10AE7S00HD002JK",
        brand="vivo",
        model="V2352A",
    ) == "vivo V2352A"


def test_device_event_label_falls_back_to_name():
    assert device_event_label(
        serial="10AE7S00HD002JK",
        name="Lab Phone 1",
    ) == "Lab Phone 1"


def test_device_event_label_falls_back_to_serial():
    assert device_event_label(serial="10AE7S00HD002JK") == "10AE7S00HD002JK"


def test_enrich_device_event_fills_missing_metadata_from_db():
    entry = {
        "id": "evt-1",
        "serial": "10AE7S00HD002JK",
        "event": "reconnected",
        "device_brand": "",
        "device_model": "",
    }
    from tenancy.background import DeviceRef

    ref = DeviceRef(
        device_id="dev-1",
        serial="10AE7S00HD002JK",
        user_id="user-1",
        org_id="org-1",
        name="",
        brand="vivo",
        model="V2352A",
    )
    enriched = _enrich_device_event(entry, ref)
    assert enriched["device_brand"] == "vivo"
    assert enriched["device_model"] == "V2352A"


def test_map_device_event_uses_consistent_label_for_reconnect():
    svc = NotificationService()
    mapped = svc._map_device_event(
        {
            "id": "evt-2",
            "serial": "10AE7S00HD002JK",
            "event": "reconnected",
            "device_brand": "vivo",
            "device_model": "V2352A",
        }
    )
    assert mapped is not None
    event, title, body, data = mapped
    assert event == "device.reconnect"
    assert title == "Device vivo V2352A reconnected"
    assert body == "vivo V2352A is online"
    assert data["device_brand"] == "vivo"
    assert data["device_model"] == "V2352A"


def test_on_agent_status_does_not_clear_brand_model_with_empty_payload():
    from runtime.core.device_client import DeviceClient, DeviceState

    client = DeviceClient("serial-1", 0, object())  # type: ignore[arg-type]
    client.brand = "vivo"
    client.model = "V2352A"
    client._state = DeviceState.READY
    client.on_agent_status({"brand": "", "model": ""})
    assert client.brand == "vivo"
    assert client.model == "V2352A"
