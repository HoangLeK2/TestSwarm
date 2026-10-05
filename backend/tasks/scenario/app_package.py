"""Parse package / activity from scenario step payloads."""
from __future__ import annotations

from typing import Any, Dict, Tuple


def parse_step_package(step: Dict[str, Any]) -> Tuple[str, str]:
    """Return (package, component_or_activity) from a step dict."""
    app_field = step.get("app")
    app_pkg = ""
    app_component = ""
    if isinstance(app_field, dict):
        app_pkg = str(app_field.get("package") or app_field.get("app_package") or "").strip()
        app_component = str(app_field.get("component") or app_field.get("activity") or "").strip()
    elif isinstance(app_field, str):
        app_pkg = app_field.strip()

    raw_pkg = str(
        step.get("package")
        or step.get("app_package")
        or step.get("appPackage")
        or app_pkg
        or ""
    ).strip()
    raw_component = str(
        step.get("component")
        or step.get("activity")
        or step.get("title")
        or app_component
        or ""
    ).strip()
    pkg = raw_pkg
    component = ""

    if pkg and "/" in pkg:
        component = pkg
        pkg = pkg.split("/", 1)[0].strip()
    if raw_component and "/" in raw_component:
        component = raw_component
        if not pkg:
            pkg = raw_component.split("/", 1)[0].strip()
    elif raw_component and not pkg:
        pkg = raw_component
    return pkg, component
