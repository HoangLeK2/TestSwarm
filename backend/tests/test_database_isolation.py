from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from core.config import _build_database_config


BACKEND_ROOT = Path(__file__).resolve().parents[1]
ISOLATED_URL = (
    "postgresql://platform_tester:secret@postgres:5432/"
    "android_platform_tester_test"
)
LEGACY_URL = "postgresql://postgres:secret@postgres:5432/device_farm"


def _import_database_url(env_overrides: dict[str, str | None]) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(BACKEND_ROOT)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from db.database import DATABASE_URL; print(DATABASE_URL)",
        ],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_platform_tester_database_url_wins_over_legacy_device_farm_url() -> None:
    result = _import_database_url(
        {
            "ANDROID_PLATFORM_TESTER_DATABASE_URL": ISOLATED_URL,
            "DATABASE_URL": LEGACY_URL,
            "DB_NAME": "device_farm",
        }
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().endswith("/android_platform_tester_test")
    assert "device_farm" not in result.stdout


def test_legacy_database_url_is_not_a_fallback() -> None:
    result = _import_database_url(
        {
            "ANDROID_PLATFORM_TESTER_DATABASE_URL": None,
            "DATABASE_URL": LEGACY_URL,
            "DB_NAME": "device_farm",
        }
    )

    assert result.returncode != 0
    assert "ANDROID_PLATFORM_TESTER_DATABASE_URL" in result.stderr


def test_platform_tester_url_rejects_device_farm_database_name() -> None:
    result = _import_database_url(
        {
            "ANDROID_PLATFORM_TESTER_DATABASE_URL": LEGACY_URL,
            "DATABASE_URL": None,
        }
    )

    assert result.returncode != 0
    assert "independent database" in result.stderr


def test_database_config_ignores_generic_database_url(monkeypatch) -> None:
    monkeypatch.setenv("ANDROID_PLATFORM_TESTER_DATABASE_URL", ISOLATED_URL)
    monkeypatch.setenv("DATABASE_URL", LEGACY_URL)

    config = _build_database_config({"enabled": True, "name": "device_farm"})

    assert config.url == ISOLATED_URL
    assert config.name == "android_platform_tester"
