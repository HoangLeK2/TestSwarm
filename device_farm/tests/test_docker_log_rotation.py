"""Regression tests for bounded Docker logs on the noisy farm service."""
from __future__ import annotations

from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_farm_docker_logs_are_rotated_in_all_compose_files():
    for filename in ("docker-compose.yml", "docker-compose.deploy.yml"):
        compose = yaml.safe_load((REPO_ROOT / filename).read_text())
        logging = compose["services"]["farm"]["logging"]

        assert logging == {
            "driver": "json-file",
            "options": {
                "max-size": "25m",
                "max-file": "5",
            },
        }, filename
