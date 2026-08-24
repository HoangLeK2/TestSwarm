from __future__ import annotations

from services.app_automation_locator import resolve_semantic_locator
from services.app_automation_profile import validate_app_automation_profile


_XML = """
<hierarchy>
  <node index="0" text="Username" class="android.widget.TextView" bounds="[40,100][240,150]" />
  <node index="1" text="" resource-id="" class="android.widget.EditText" bounds="[260,90][900,170]" />
  <node index="2" text="Password" class="android.widget.TextView" bounds="[40,220][240,270]" />
  <node index="3" text="" resource-id="com.example:id/password" class="android.widget.EditText" bounds="[260,210][900,290]" />
  <node index="4" text="Login" class="android.widget.Button" clickable="true" bounds="[300,360][700,440]" />
</hierarchy>
"""


def _profile(extra_locators: dict | None = None):
    locators = {
        "password_field": {
            "candidates": [
                {"resource_id_contains": "password"},
                {"text_near": ["Password"], "target_class": "android.widget.EditText"},
            ]
        },
        "username_field": {
            "candidates": [
                {"text_near": ["Username"], "target_class": "android.widget.EditText", "allow_coordinate_fallback": True},
            ]
        },
        "login_button": {
            "candidates": [
                {"by": "text", "value": "Login"},
            ]
        },
    }
    if extra_locators:
        locators.update(extra_locators)
    return validate_app_automation_profile({"package": "com.example.app", "semantic_locators": locators})


def test_exact_text_locator_wins_with_trace():
    result = resolve_semantic_locator(_profile(), "login_button", _XML, screen=(1080, 1920))

    assert result.matched is True
    assert result.score == 1.0
    assert result.fallback_level == "exact"
    assert result.selector == {"by": "text", "value": "Login"}
    assert result.bounds == {"left": 300, "top": 360, "right": 700, "bottom": 440}


def test_resource_id_contains_locator_returns_stable_selector():
    result = resolve_semantic_locator(_profile(), "password_field", _XML, screen=(1080, 1920))

    assert result.matched is True
    assert result.fallback_level == "resource_id_contains"
    assert result.selector == {"by": "resource-id", "value": "com.example:id/password"}


def test_text_near_resolves_field_without_resource_id():
    result = resolve_semantic_locator(_profile(), "username_field", _XML, screen=(1080, 1920))

    assert result.matched is True
    assert result.fallback_level == "text_near"
    assert result.selector is None
    assert result.bounds == {"left": 260, "top": 90, "right": 900, "bottom": 170}


def test_text_near_requires_explicit_coordinate_fallback_for_bounds_only_node():
    xml = """
    <hierarchy>
      <node text="Username" class="android.widget.TextView" bounds="[40,100][240,150]" />
      <node text="" resource-id="" class="android.widget.EditText" bounds="[260,90][900,170]" />
    </hierarchy>
    """
    profile = _profile({
        "username_no_coordinate": {
            "candidates": [
                {"text_near": ["Username"], "target_class": "android.widget.EditText"},
            ]
        }
    })

    result = resolve_semantic_locator(profile, "username_no_coordinate", xml, screen=(1080, 1920))

    assert result.matched is False
    assert result.reason == "no candidates matched"


def test_text_near_matches_label_with_suffix():
    xml = """
    <hierarchy>
      <node text="Password *" class="android.widget.TextView" bounds="[40,220][240,270]" />
      <node text="" resource-id="com.example:id/password" class="android.widget.EditText" bounds="[260,210][900,290]" />
    </hierarchy>
    """

    result = resolve_semantic_locator(_profile(), "password_field", xml, screen=(1080, 1920))

    assert result.matched is True
    assert result.selector == {"by": "resource-id", "value": "com.example:id/password"}


def test_unknown_locator_returns_unmatched_result():
    result = resolve_semantic_locator(_profile(), "missing", _XML)

    assert result.matched is False
    assert result.reason == "unknown locator"


def test_ambiguous_duplicate_exact_match_fails_closed():
    xml = """
    <hierarchy>
      <node text="Continue" class="android.widget.Button" bounds="[10,10][100,80]" />
      <node text="Continue" class="android.widget.Button" bounds="[10,120][100,200]" />
    </hierarchy>
    """
    profile = _profile({
        "continue_button": {
            "candidates": [{"by": "text", "value": "Continue"}],
        }
    })

    result = resolve_semantic_locator(profile, "continue_button", xml)

    assert result.matched is False
    assert result.reason == "ambiguous candidates"
    assert result.candidate_count == 2


def test_class_name_filters_combined_direct_candidate():
    xml = """
    <hierarchy>
      <node content-desc="Log in" class="android.widget.Button" bounds="[24,517][516,583]" />
      <node text="Log in" content-desc="Log in" class="android.view.View" bounds="[239,534][302,567]" />
    </hierarchy>
    """
    profile = _profile({
        "login_button": {
            "candidates": [
                {"description_contains": "Log in", "class_name": "android.widget.Button"},
            ],
        }
    })

    result = resolve_semantic_locator(profile, "login_button", xml, screen=(540, 1200))

    assert result.matched is True
    assert result.bounds == {"left": 24, "top": 517, "right": 516, "bottom": 583}
    assert result.candidate_count == 1


def test_allow_ambiguous_permits_first_duplicate_match():
    xml = """
    <hierarchy>
      <node text="Continue" class="android.widget.Button" bounds="[10,10][100,80]" />
      <node text="Continue" class="android.widget.Button" bounds="[10,120][100,200]" />
    </hierarchy>
    """
    profile = _profile({
        "continue_button": {
            "allow_ambiguous": True,
            "candidates": [{"by": "text", "value": "Continue"}],
        }
    })

    result = resolve_semantic_locator(profile, "continue_button", xml)

    assert result.matched is True
    assert result.bounds == {"left": 10, "top": 10, "right": 100, "bottom": 80}


def test_region_filter_limits_candidates():
    xml = """
    <hierarchy>
      <node text="Close" class="android.widget.Button" bounds="[10,10][100,80]" />
      <node text="Close" class="android.widget.Button" bounds="[10,1700][100,1800]" />
    </hierarchy>
    """
    profile = _profile({
        "bottom_close": {
            "candidates": [{"by": "text", "value": "Close", "region": "bottom"}],
        }
    })

    result = resolve_semantic_locator(profile, "bottom_close", xml, screen=(1080, 1920))

    assert result.matched is True
    assert result.bounds == {"left": 10, "top": 1700, "right": 100, "bottom": 1800}


def test_region_filter_applies_to_text_near_candidates():
    xml = """
    <hierarchy>
      <node text="Search" class="android.widget.TextView" bounds="[40,100][240,150]" />
      <node text="" resource-id="com.example:id/top_search" class="android.widget.EditText" bounds="[260,90][900,170]" />
      <node text="Search" class="android.widget.TextView" bounds="[40,1500][240,1550]" />
      <node text="" resource-id="com.example:id/bottom_search" class="android.widget.EditText" bounds="[260,1490][900,1570]" />
    </hierarchy>
    """
    profile = _profile({
        "bottom_search": {
            "candidates": [{"text_near": ["Search"], "target_class": "android.widget.EditText", "region": "bottom"}],
        }
    })

    result = resolve_semantic_locator(profile, "bottom_search", xml, screen=(1080, 1920))

    assert result.matched is True
    assert result.selector == {"by": "resource-id", "value": "com.example:id/bottom_search"}


def test_text_near_repeated_rows_fail_as_ambiguous_without_region():
    xml = """
    <hierarchy>
      <node text="Code" class="android.widget.TextView" bounds="[40,100][240,150]" />
      <node text="" resource-id="com.example:id/code_top" class="android.widget.EditText" bounds="[260,90][900,170]" />
      <node text="Code" class="android.widget.TextView" bounds="[40,210][240,260]" />
      <node text="" resource-id="com.example:id/code_bottom" class="android.widget.EditText" bounds="[260,200][900,280]" />
    </hierarchy>
    """
    profile = _profile({
        "code_field": {
            "candidates": [{"text_near": ["Code"], "target_class": "android.widget.EditText"}],
        }
    })

    result = resolve_semantic_locator(profile, "code_field", xml, screen=(1080, 1920))

    assert result.matched is False
    assert result.reason == "ambiguous candidates"
