"""Tests for scenario app package parsing."""
from tasks.scenario.app_package import parse_step_package


def test_parse_package_only():
    pkg, comp = parse_step_package({"type": "launch_app", "package": "com.example.app"})
    assert pkg == "com.example.app"
    assert comp == ""


def test_parse_component_slash():
    pkg, comp = parse_step_package({
        "type": "launch_app",
        "package": "com.example.app",
        "activity": "com.example.app/.MainActivity",
    })
    assert pkg == "com.example.app"
    assert comp == "com.example.app/.MainActivity"


def test_parse_full_component_in_package_field():
    pkg, comp = parse_step_package({
        "type": "launch_app",
        "package": "com.example.app/.SplashActivity",
    })
    assert pkg == "com.example.app"
    assert comp == "com.example.app/.SplashActivity"
