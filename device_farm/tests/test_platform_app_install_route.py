from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes import platform_apps


@pytest.mark.asyncio
async def test_install_release_apk_uses_download_url_only():
    row = SimpleNamespace(object_key="platform-apps/facebook.apk")
    calls: list[str] = []

    class Device:
        def install(self, source: str, timeout: float) -> None:
            calls.append(source)
            assert timeout == 600

    await platform_apps._install_release_apk(
        Device(),
        row,
        "https://cdn.example/facebook.apk",
        timeout_seconds=600,
    )

    assert calls == ["https://cdn.example/facebook.apk"]


@pytest.mark.asyncio
async def test_install_release_apk_requires_download_url():
    row = SimpleNamespace(object_key="platform-apps/facebook.apk")

    with pytest.raises(RuntimeError, match="install download URL unavailable"):
        await platform_apps._install_release_apk(
            object(),
            row,
            None,
            timeout_seconds=600,
        )
