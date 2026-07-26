from tasks.scenario.steps import extraction as extraction_mod


class _FakeDevice:
    def __init__(self):
        self.calls = []

    def request_extra_data_xml(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "ok": True,
            "ingest": {
                "parsed_count": 1,
                "inserted_count": 1,
                "duplicate_count": 0,
                "diagnostic": {"reason_code": "ok"},
                "items": [{"display_name": "OpenClaw VN"}],
            },
        }


def test_fb_groups_persists_without_content_collection_and_keeps_query(
    monkeypatch,
) -> None:
    monkeypatch.setenv("EDGE_EXTRA_DATA_ENABLED", "1")
    monkeypatch.setattr(
        extraction_mod,
        "_relay_extra_data_available",
        lambda _device: True,
    )
    device = _FakeDevice()
    ctx = {}
    scenario = {
        "_execution_id": "execution-a",
        "_campaign_id": "campaign-a",
        "_campaign_vars": {"__USER_ID__": "user-a"},
        "name": "group discovery",
    }
    result = {}

    handled = extraction_mod.request_edge_extra_data(
        device=device,
        serial="device-a",
        ctx=ctx,
        scenario=scenario,
        step={
            "edge_extra_data": True,
            "search_query": "${SEARCH_QUERY}",
        },
        strategy="fb_groups",
        result=result,
    )

    assert handled is True
    assert device.calls[0]["strategy"] == "fb_groups"
    assert device.calls[0]["context"]["persist"] is True
    assert device.calls[0]["context"]["return_items"] is True
    assert device.calls[0]["context"]["search_query"] == "${SEARCH_QUERY}"
    assert ctx["groups"] == [{"display_name": "OpenClaw VN"}]
