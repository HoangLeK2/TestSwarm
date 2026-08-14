import importlib


def test_runtime_clamps_oversized_executor_pool_env(monkeypatch):
    monkeypatch.setenv("RELAY_ADB_POOL_SIZE", "128")
    monkeypatch.setenv("RELAY_U2_POOL_SIZE", "128")
    monkeypatch.setenv("RELAY_SCRCPY_POOL_SIZE", "32")

    import relay.runtime as runtime

    runtime = importlib.reload(runtime)
    try:
        assert runtime.ADB_POOL_SIZE == 64
        assert runtime.U2_POOL_SIZE == 64
        assert runtime.SCRCPY_POOL_SIZE == 16
    finally:
        runtime.shutdown_executors(wait=False)
        monkeypatch.delenv("RELAY_ADB_POOL_SIZE", raising=False)
        monkeypatch.delenv("RELAY_U2_POOL_SIZE", raising=False)
        monkeypatch.delenv("RELAY_SCRCPY_POOL_SIZE", raising=False)
        importlib.reload(runtime)


def test_runtime_honors_low_executor_pool_env(monkeypatch):
    monkeypatch.setenv("RELAY_ADB_POOL_SIZE", "1")
    monkeypatch.setenv("RELAY_U2_POOL_SIZE", "2")
    monkeypatch.setenv("RELAY_SCRCPY_POOL_SIZE", "1")

    import relay.runtime as runtime

    runtime = importlib.reload(runtime)
    try:
        assert runtime.ADB_POOL_SIZE == 1
        assert runtime.U2_POOL_SIZE == 2
        assert runtime.SCRCPY_POOL_SIZE == 1
    finally:
        runtime.shutdown_executors(wait=False)
        monkeypatch.delenv("RELAY_ADB_POOL_SIZE", raising=False)
        monkeypatch.delenv("RELAY_U2_POOL_SIZE", raising=False)
        monkeypatch.delenv("RELAY_SCRCPY_POOL_SIZE", raising=False)
        importlib.reload(runtime)
