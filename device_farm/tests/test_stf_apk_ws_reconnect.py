from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STF_SRC = REPO_ROOT / "STFService.apk" / "app" / "src" / "main" / "java" / "jp" / "co" / "cyberagent" / "stf"


def _read_stf_source(name: str) -> str:
    return (STF_SRC / name).read_text(encoding="utf-8")


def test_identity_activity_injected_qr_preempts_saved_url_reconnect() -> None:
    src = _read_stf_source("IdentityActivity.java")
    on_create_start = src.index("protected void onCreate")
    injected_qr = src.index("String injectedQr", on_create_start)
    saved_url = src.index("String savedUrl", on_create_start)

    assert injected_qr < saved_url
    assert "return;" in src[injected_qr:saved_url]


def test_ws_agent_same_url_start_is_idempotent() -> None:
    service_src = _read_stf_source("WsAgentService.java")
    manager_src = _read_stf_source("WebSocketManager.java")

    assert "isConnectedTo(wsUrl)" in service_src
    assert "boolean isConnectedTo(String url)" in manager_src
    assert "currentUrl" in manager_src
