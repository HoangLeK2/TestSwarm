from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.routes import platform_apps


@pytest.mark.asyncio
async def test_install_release_apk_uses_download_url_and_prepares_reverse():
    row = SimpleNamespace(object_key="platform-apps/facebook.apk")
    calls: list[str] = []
    reverse_calls: list[tuple[int, int, float]] = []

    class Device:
        def ensure_reverse_tcp(self, *, remote_port: int, local_port: int, timeout: float) -> None:
            reverse_calls.append((remote_port, local_port, timeout))

        def install(self, source: str, timeout: float, verify_package: str | None = None) -> None:
            calls.append(source)
            assert timeout == 600
            assert verify_package == platform_apps.FACEBOOK_PACKAGE

    await platform_apps._install_release_apk(
        Device(),
        row,
        "http://127.0.0.1:8081/api/platform-apps/facebook/install-download?token=t",
        timeout_seconds=600,
    )

    assert reverse_calls == [(8081, 8081, 10.0)]
    assert calls == ["http://127.0.0.1:8081/api/platform-apps/facebook/install-download?token=t"]


@pytest.mark.asyncio
async def test_install_release_apk_skips_reverse_for_external_download_url():
    row = SimpleNamespace(object_key="platform-apps/facebook.apk")
    calls: list[str] = []

    class Device:
        def ensure_reverse_tcp(self, **kwargs) -> None:
            raise AssertionError("reverse should not be used for external URLs")

        def install(self, source: str, timeout: float, verify_package: str | None = None) -> None:
            calls.append(source)
            assert verify_package == platform_apps.FACEBOOK_PACKAGE

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
