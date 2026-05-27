import os

from relay.agent import RelayAgent


def test_scrcpy_auto_resume_default_is_disabled(monkeypatch):
    # Default should be viewer-gated: do not auto-start scrcpy unless explicitly asked.
    monkeypatch.delenv("SCRCPY_AUTO_RESUME", raising=False)
    agent = RelayAgent(server_url="localhost:50051", api_key="x", relay_id="relay-1", enrollment_token="")
    assert agent._scrcpy_auto_resume_enabled is False

    monkeypatch.setenv("SCRCPY_AUTO_RESUME", "true")
    agent2 = RelayAgent(server_url="localhost:50051", api_key="x", relay_id="relay-1", enrollment_token="")
    assert agent2._scrcpy_auto_resume_enabled is True

