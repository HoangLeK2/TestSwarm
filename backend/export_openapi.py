from __future__ import annotations

import json
from pathlib import Path

from core.config import load_config
from runtime.core import DeviceManager, TaskQueue
from web.server import create_app


def build_app():
    root = Path(__file__).resolve().parent
    config = load_config("config.yaml")
    manager = DeviceManager(config)
    queue = TaskQueue()
    templates_dir = str(root / "web" / "templates")
    static_dir = str(root / "web" / "static")
    front_end_dist = None
    return create_app(manager, queue, config, templates_dir, static_dir, front_end_dist)


def main() -> None:
    app = build_app()
    schema = app.openapi()
    root = Path(__file__).resolve().parent
    out_dir = root / "swagger"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote OpenAPI schema to {out_path}")


if __name__ == "__main__":
    main()

