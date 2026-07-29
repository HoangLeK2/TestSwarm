from __future__ import annotations

from types import SimpleNamespace

import bootstrap
import relay.scrcpy_relay as scrcpy_mod


def test_bundle_cleanup_does_not_remove_active_scrcpy_artifact(
    monkeypatch,
    tmp_path,
) -> None:
    bundle = tmp_path / "device_bundle.tar.gz"
    bundle.write_bytes(b"bundle")
    shell_commands: list[str] = []

    monkeypatch.setattr(bootstrap, "_DEVICE_BUNDLE_TGZ", bundle)
    monkeypatch.setattr(
        bootstrap,
        "_adb",
        lambda *_args, **_kwargs: SimpleNamespace(
            returncode=0,
            stdout="",
            stderr="",
        ),
    )
    monkeypatch.setattr(
        bootstrap,
        "_adb_shell",
        lambda command, **_kwargs: shell_commands.append(command),
    )
    monkeypatch.setattr(bootstrap, "_is_atx_listening", lambda _serial: True)

    assert bootstrap.step_deploy_bundle_if_needed("A", force=True) is True
    assert len(shell_commands) == 1
    cleanup = shell_commands[0].split("&&", 1)[0]
    assert scrcpy_mod._SCRCPY_PATH_ON_DEVICE not in cleanup
