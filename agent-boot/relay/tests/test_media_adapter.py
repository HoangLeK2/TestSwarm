import json

from relay import media_adapter, media_adapter_session


def test_media_adapter_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MEDIA_ADAPTER_ENABLED", raising=False)

    assert media_adapter.enabled() is False


def test_direct_scrcpy_enabled_requires_adapter_and_direct_flag(monkeypatch):
    monkeypatch.setenv("MEDIA_ADAPTER_ENABLED", "1")
    monkeypatch.setenv("MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED", "0")
    assert media_adapter.direct_scrcpy_enabled() is False

    monkeypatch.setenv("MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED", "1")
    assert media_adapter.direct_scrcpy_enabled() is True


def test_start_direct_scrcpy_stream_posts_to_http_api(monkeypatch):
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"running":true,"connected":false}'

    def fake_urlopen(req, timeout):
        calls.append((req, timeout))
        return FakeResponse()

    monkeypatch.setenv("MEDIA_ADAPTER_HTTP_URL", "http://adapter.local:8878")
    monkeypatch.setattr(media_adapter.urllib.request, "urlopen", fake_urlopen)

    result = media_adapter.start_direct_scrcpy_stream(
        serial="SERIAL-1",
        host="127.0.0.1",
        port=27183,
        control=True,
        owns_scrcpy=True,
        max_fps=15,
        max_width=600,
        bitrate=900_000,
        video_codec="h264",
        video_encoder="c2.android.avc.encoder",
        low_latency=True,
    )

    req, timeout = calls[0]
    assert timeout == 1.5
    assert req.full_url == "http://adapter.local:8878/v1/scrcpy/streams/SERIAL-1/start"
    assert json.loads(req.data.decode()) == {
        "host": "127.0.0.1",
        "port": 27183,
        "control": True,
        "owns_scrcpy": True,
        "max_fps": 15,
        "max_width": 600,
        "bitrate": 900_000,
        "video_codec": "h264",
        "video_encoder": "c2.android.avc.encoder",
        "low_latency": True,
    }
    assert result["running"] is True


def test_media_adapter_session_uses_per_serial_video_encoder(monkeypatch):
    calls = []

    def fake_start_direct_scrcpy_stream(**kwargs):
        calls.append(kwargs)
        return {"running": True}

    monkeypatch.setenv("SCRCPY_VIDEO_ENCODER", "OMX.default.avc.encoder")
    monkeypatch.setenv("SCRCPY_VIDEO_ENCODER__SERIAL_1", "c2.android.avc.encoder")
    monkeypatch.setattr(
        media_adapter_session,
        "start_direct_scrcpy_stream",
        fake_start_direct_scrcpy_stream,
    )

    session = media_adapter_session.MediaAdapterScrcpySession(
        serial="SERIAL-1",
        max_fps=15,
        max_width=480,
        enable_control=True,
        port=0,
        send_queue=None,
        loop=None,
        bitrate=900_000,
    )
    session.start()

    assert calls[0]["video_codec"] == "h264"
    assert calls[0]["video_encoder"] == "c2.android.avc.encoder"


def test_media_adapter_owns_scrcpy_defaults_to_enabled_with_direct(monkeypatch):
    monkeypatch.setenv("MEDIA_ADAPTER_ENABLED", "1")
    monkeypatch.setenv("MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED", "1")
    monkeypatch.delenv("MEDIA_ADAPTER_OWNS_SCRCPY", raising=False)

    assert media_adapter.owns_scrcpy_enabled() is True


def test_media_adapter_owns_scrcpy_can_be_disabled_for_rollback(monkeypatch):
    monkeypatch.setenv("MEDIA_ADAPTER_ENABLED", "1")
    monkeypatch.setenv("MEDIA_ADAPTER_DIRECT_SCRCPY_ENABLED", "1")
    monkeypatch.setenv("MEDIA_ADAPTER_OWNS_SCRCPY", "0")

    assert media_adapter.owns_scrcpy_enabled() is False
