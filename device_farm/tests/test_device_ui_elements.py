from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.routes.device_control.device_ui import build_device_ui_router
from runtime.core.device_client import DeviceClient


_FIXTURE_DIR = Path(__file__).parent / "fixtures" / "element_finding"


def _fixture(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


def _app_for_hierarchy(xml: str) -> FastAPI:
    device = Mock()
    device.hierarchy_xml.return_value = xml
    manager = Mock()
    manager.get_device.return_value = device
    app = FastAPI()
    app.include_router(build_device_ui_router(manager), prefix="/api")
    return app


async def _get_ui_elements(xml: str) -> dict:
    app = _app_for_hierarchy(xml)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/devices/test-serial/ui_elements")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.asyncio
async def test_ui_elements_request_uses_visible_hierarchy_lane() -> None:
    device = Mock()
    device.hierarchy_xml.return_value = "<hierarchy />"
    manager = Mock()
    manager.get_device.return_value = device
    app = FastAPI()
    app.include_router(build_device_ui_router(manager), prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/devices/test-serial/ui_elements?refresh=1")

    assert resp.status_code == 200
    device.hierarchy_xml.assert_called_once_with(
        force_refresh=True,
        priority="visible",
        deadline_ms=1500,
    )


@pytest.mark.asyncio
async def test_hierarchy_request_uses_visible_hierarchy_lane() -> None:
    device = Mock()
    device.hierarchy_xml.return_value = "<hierarchy />"
    manager = Mock()
    manager.get_device.return_value = device
    app = FastAPI()
    app.include_router(build_device_ui_router(manager), prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get(
            "/api/devices/test-serial/hierarchy?refresh=1&priority=visible"
        )

    assert resp.status_code == 200
    device.hierarchy_xml.assert_called_once_with(
        force_refresh=True,
        priority="visible",
        deadline_ms=1500,
    )


@pytest.mark.asyncio
async def test_hierarchy_request_defaults_to_background_hierarchy_lane() -> None:
    device = Mock()
    device.hierarchy_xml.return_value = "<hierarchy />"
    manager = Mock()
    manager.get_device.return_value = device
    app = FastAPI()
    app.include_router(build_device_ui_router(manager), prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.get("/api/devices/test-serial/hierarchy?refresh=1")

    assert resp.status_code == 200
    device.hierarchy_xml.assert_called_once_with(
        force_refresh=True,
        priority=None,
        deadline_ms=None,
    )


@pytest.mark.asyncio
async def test_hit_test_request_uses_visible_hierarchy_lane() -> None:
    device = Mock()
    device.screen_width = 100
    device.screen_height = 200
    device.hit_test_selector.return_value = {"by": "text", "value": "OK"}
    manager = Mock()
    manager.get_device.return_value = device
    app = FastAPI()
    app.include_router(build_device_ui_router(manager), prefix="/api")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        resp = await client.post(
            "/api/devices/test-serial/hit_test",
            json={"x": 10, "y": 20},
        )

    assert resp.status_code == 200
    assert resp.json() == {"by": "text", "value": "OK"}
    device.hit_test_selector.assert_called_once_with(
        10,
        20,
        priority="visible",
        deadline_ms=1500,
    )


@pytest.mark.asyncio
async def test_ui_elements_avoids_duplicate_resource_id_when_text_is_unique() -> None:
    xml = """
    <hierarchy>
      <node package="com.example" class="android.widget.FrameLayout" bounds="[0,0][1080,1920]">
        <node package="com.example" class="android.widget.TextView"
              resource-id="com.example:id/item" text="First row"
              clickable="true" bounds="[0,100][900,180]" />
        <node package="com.example" class="android.widget.TextView"
              resource-id="com.example:id/item" text="Target row"
              clickable="true" bounds="[0,220][900,300]" />
      </node>
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    target = next(el for el in data["elements"] if el["text"] == "Target row")
    assert target["selector_by"] == "text"
    assert target["selector_value"] == "Target row"
    assert target["resource_id_duplicate_count"] == 2
    assert target["selector_reason"] == "unique text"


@pytest.mark.asyncio
async def test_ui_elements_prefers_unique_description_over_duplicate_resource_id() -> None:
    xml = """
    <hierarchy>
      <node package="com.facebook.katana" class="android.view.ViewGroup" bounds="[0,0][1080,1920]">
        <node package="com.facebook.katana" class="android.view.ViewGroup"
              resource-id="com.facebook.katana:id/(name removed)"
              content-desc="First profile"
              clickable="true" bounds="[24,200][1056,360]" />
        <node package="com.facebook.katana" class="android.view.ViewGroup"
              resource-id="com.facebook.katana:id/(name removed)"
              content-desc="Target profile"
              clickable="true" bounds="[24,380][1056,540]" />
      </node>
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    target = next(el for el in data["elements"] if el["content_desc"] == "Target profile")
    assert target["selector_by"] == "description"
    assert target["selector_value"] == "Target profile"
    assert target["resource_id_duplicate_count"] == 2
    assert target["selector_reason"] == "unique content-desc"


@pytest.mark.asyncio
async def test_ui_elements_avoids_generic_resource_id_even_when_unique() -> None:
    xml = """
    <hierarchy>
      <node package="com.facebook.katana" class="android.view.ViewGroup" bounds="[0,0][1080,1920]">
        <node package="com.facebook.katana" class="android.widget.Button"
              resource-id="com.facebook.katana:id/(name removed)"
              text="Theo dõi" clickable="true" bounds="[100,200][500,280]" />
      </node>
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    target = next(el for el in data["elements"] if el["text"] == "Theo dõi")
    assert target["selector_by"] == "text"
    assert target["selector_value"] == "Theo dõi"
    assert target["resource_id_duplicate_count"] == 1
    assert target["selector_reason"] == "unique text"


@pytest.mark.asyncio
async def test_ui_elements_shared_facebook_row_fixture_marks_duplicate_action_text_volatile() -> None:
    data = await _get_ui_elements(_fixture("facebook_row_action.xml"))

    target = next(el for el in data["elements"] if el["bounds"] == [820, 118, 1040, 190])
    assert target["selector_by"] == "xpath"
    assert target["selector_value"] == '//*[@bounds="[820,118][1040,190]"]'
    assert target["selector_volatile"] is True
    assert target["selector_reason"] == "bounds fallback"
    assert target["text_duplicate_count"] == 2

    group_row = next(
        el for el in data["elements"] if el["content_desc"] == "Group Alpha, 42K members"
    )
    assert group_row["selector_by"] == "description"
    assert group_row["selector_value"] == "Group Alpha, 42K members"


@pytest.mark.asyncio
async def test_ui_elements_skips_system_ui_nodes_when_app_nodes_exist() -> None:
    xml = """
    <hierarchy>
      <node package="com.android.systemui" class="android.widget.TextView"
            text="09:30" bounds="[0,0][1080,80]" />
      <node package="com.example" class="android.widget.Button"
            text="Open" clickable="true" bounds="[100,300][500,380]" />
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    assert all(el["package"] != "com.android.systemui" for el in data["elements"])
    assert data["elements"][0]["selector_by"] == "text"
    assert data["elements"][0]["selector_value"] == "Open"


@pytest.mark.asyncio
async def test_ui_elements_screen_dims_ignore_system_ui_when_app_nodes_exist() -> None:
    xml = """
    <hierarchy>
      <node package="com.android.systemui" class="android.widget.FrameLayout"
            bounds="[0,0][1080,3000]" />
      <node package="com.example" class="android.widget.FrameLayout"
            bounds="[0,0][1080,1920]">
        <node package="com.example" class="android.widget.Button"
              text="Open" clickable="true" bounds="[100,300][500,380]" />
      </node>
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    target = data["elements"][0]
    assert target["screen_width"] == 1080
    assert target["screen_height"] == 1920
    assert target["fallback_rx"] == 300 / 1080
    assert target["fallback_ry"] == 340 / 1920


@pytest.mark.asyncio
async def test_ui_elements_marks_bounds_xpath_fallback_as_volatile() -> None:
    xml = """
    <hierarchy>
      <node package="com.example" class="android.view.ViewGroup" bounds="[0,0][1080,1920]">
        <node package="com.example" class="android.widget.Button"
              text="Like" content-desc="Like" clickable="true"
              bounds="[100,200][300,280]" />
        <node package="com.example" class="android.widget.Button"
              text="Like" content-desc="Like" clickable="true"
              bounds="[100,320][300,400]" />
      </node>
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    first_like = next(el for el in data["elements"] if el["bounds"] == [100, 200, 300, 280])
    assert first_like["selector_by"] == "xpath"
    assert first_like["selector_value"] == '//*[@bounds="[100,200][300,280]"]'
    assert first_like["selector_volatile"] is True
    assert first_like["selector_reason"] == "bounds fallback"
    assert first_like["fallback_rx"] == 200 / 1080
    assert first_like["fallback_ry"] == 240 / 1920
    assert first_like["screen_width"] == 1080
    assert first_like["screen_height"] == 1920


@pytest.mark.asyncio
async def test_ui_elements_keeps_duplicate_candidates_visible_for_diagnostics() -> None:
    xml = """
    <hierarchy>
      <node package="com.example" class="android.widget.Button"
            text="Like" clickable="true" />
      <node package="com.example" class="android.widget.Button"
            text="Like" clickable="true" />
    </hierarchy>
    """

    data = await _get_ui_elements(xml)

    likes = [el for el in data["elements"] if el["text"] == "Like"]
    assert len(likes) == 2
    assert data["duplicates_hidden"] == 0
    assert all(el["text_duplicate_count"] == 2 for el in likes)


def test_device_client_batch_selector_dict_accepts_ui_element_selector_names() -> None:
    device = DeviceClient.__new__(DeviceClient)

    assert device._selector_dict("resource-id", "com.example:id/item") == {
        "resourceId": "com.example:id/item"
    }
    assert device._selector_dict("class name", "android.widget.Button") == {
        "className": "android.widget.Button"
    }
    assert device._selector_dict("description", "Open") == {
        "description": "Open"
    }
