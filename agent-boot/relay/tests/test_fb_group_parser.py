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
