from relay.extra_data.parsers.facebook.group_pipeline import parse_group_search_results


def test_parse_group_search_results_deduplicates_cards_and_parses_vn_metrics():
    xml = """
    <hierarchy>
      <node class="android.widget.Button"
            clickable="true"
            bounds="[0,200][1080,430]"
            content-desc="OpenClaw VN, Nhóm Công khai · 158.771 thành viên">
        <node text="OpenClaw VN" />
        <node text="Nhóm Công khai · 158.771 thành viên" />
      </node>
      <node class="android.widget.Button"
            clickable="true"
            bounds="[0,440][1080,670]"
            content-desc="Automation Builders, Private group · 12.5K members" />
    </hierarchy>
    """

    items, diagnostic = parse_group_search_results(xml)

    assert diagnostic == {"reason_code": "ok", "groups_returned": 2}
    assert [item["display_name"] for item in items] == [
        "OpenClaw VN",
        "Automation Builders",
    ]
    assert items[0]["metrics"]["member_count"] == 158_771
    assert items[0]["attributes"]["privacy"] == "public"
    assert items[1]["metrics"]["member_count"] == 12_500
    assert items[1]["attributes"]["privacy"] == "private"
    assert all(item["platform"] == "facebook" for item in items)
    assert all(item["entity_type"] == "group" for item in items)
    assert items[0]["attributes"]["locator"] == {
        "kind": "facebook_group_search_result",
        "version": 1,
        "search_query": "OpenClaw VN",
        "selector": {
            "by": "descriptionStartsWith",
            "value": "OpenClaw VN,",
        },
        "fallback_selector": {
            "by": "descriptionContains",
            "value": "OpenClaw VN",
        },
    }


def test_parse_group_search_results_accepts_current_facebook_vietnamese_cards():
    xml = """
    <hierarchy>
      <node class="android.widget.Button"
            clickable="true"
            bounds="[0,474][1260,781]"
            content-desc="OpenClaw Community - The AI Agent,Công khai · 138K thành viên · 10+ bài viết/ngày">
        <node text="OpenClaw Community - The AI Agent · Truy cập" />
        <node text="Công khai · 138K thành viên · 10+ bài viết/ngày" />
      </node>
      <node class="android.widget.Button"
            clickable="true"
            bounds="[0,781][1260,1047]"
            content-desc="Openclaw - Hermes VN - AI Agents trên VPS,Công khai · 6,1K thành viên">
        <node text="Openclaw - Hermes VN - AI Agents trên VPS · Tham gia" />
        <node text="Công khai · 6,1K thành viên" />
      </node>
    </hierarchy>
    """

    items, diagnostic = parse_group_search_results(xml)

    assert diagnostic == {"reason_code": "ok", "groups_returned": 2}
    assert [item["display_name"] for item in items] == [
        "OpenClaw Community - The AI Agent",
        "Openclaw - Hermes VN - AI Agents trên VPS",
    ]
    assert [item["metrics"]["member_count"] for item in items] == [
        138_000,
        6_100,
    ]
    assert all(item["attributes"]["privacy"] == "public" for item in items)


def test_parse_group_search_results_rejects_generic_public_content() -> None:
    xml = """
    <hierarchy>
      <node class="android.widget.Button"
            clickable="true"
            content-desc="Bài viết công khai" />
      <node class="android.widget.Button"
            clickable="true"
            content-desc="Nhóm OpenClaw, Công khai · 120 thành viên" />
    </hierarchy>
    """

    items, diagnostic = parse_group_search_results(xml)

    assert diagnostic == {"reason_code": "ok", "groups_returned": 1}
    assert [item["display_name"] for item in items] == ["Nhóm OpenClaw"]
