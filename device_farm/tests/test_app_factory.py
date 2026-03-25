from __future__ import annotations

from pathlib import Path

from core.config import load_config
from fastapi.testclient import TestClient
from runtime.core import DeviceManager, TaskQueue
from web.server import create_app


def test_ping():
    root = Path(__file__).resolve().parents[1]
    cfg = load_config(str(root / "config.yaml"))
    manager = DeviceManager(cfg)
    queue = TaskQueue()
    app = create_app(
        manager,
        queue,
        cfg,
        str(root / "web" / "templates"),
        str(root / "web" / "static"),
        None,
    )
    client = TestClient(app)
    r = client.get("/ping")
    assert r.status_code == 200
    assert r.json().get("service") == "device-farm"
