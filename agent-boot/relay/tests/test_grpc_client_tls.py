from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from relay.grpc_client import GrpcRelayClient, create_grpc_channel


def test_create_grpc_channel_uses_insecure_channel_by_default(monkeypatch):
    calls: list[tuple[str, str]] = []

    class _Aio:
        @staticmethod
        def insecure_channel(addr, options=None):
            calls.append(("insecure", addr))
            return object()

        @staticmethod
        def secure_channel(addr, credentials, options=None):
            calls.append(("secure", addr))
            return object()

    monkeypatch.setattr("relay.grpc_client.grpc_aio", _Aio)

    create_grpc_channel("farm.local:50051", tls_enabled=False)

    assert calls == [("insecure", "farm.local:50051")]


def test_create_grpc_channel_uses_secure_channel_with_root_cert(monkeypatch, tmp_path: Path):
    calls: list[tuple[str, str, object]] = []
    cert_file = tmp_path / "ca.pem"
    cert_file.write_text("-----BEGIN CERTIFICATE-----\nmock\n-----END CERTIFICATE-----\n")

    class _Aio:
        @staticmethod
        def insecure_channel(addr, options=None):
            calls.append(("insecure", addr, None))
            return object()

        @staticmethod
        def secure_channel(addr, credentials, options=None):
            calls.append(("secure", addr, credentials))
            return object()

    class _Grpc:
        @staticmethod
        def ssl_channel_credentials(root_certificates=None):
            return ("creds", root_certificates)

    monkeypatch.setattr("relay.grpc_client.grpc_aio", _Aio)
    monkeypatch.setattr("relay.grpc_client.grpc", _Grpc)

    create_grpc_channel("farm.local:50051", tls_enabled=True, root_cert_file=str(cert_file))

    assert calls == [("secure", "farm.local:50051", ("creds", cert_file.read_bytes()))]


@pytest.mark.asyncio
async def test_stream_sends_attempt_registration_before_shared_queue(
    monkeypatch,
) -> None:
    from relay.grpc_gen import relay_pb2_grpc

    received_types: list[str] = []

    class _Stub:
        def __init__(self, channel) -> None:
            return None

        def Stream(self, request_iterator, metadata):
            async def _responses():
                for _ in range(2):
                    message = await anext(request_iterator)
                    received_types.append(json.loads(message.meta.decode())["type"])
                if False:
                    yield None

            return _responses()

    monkeypatch.setattr(relay_pb2_grpc, "RelayServiceStub", _Stub)

    send_queue: asyncio.Queue = asyncio.Queue()
    await send_queue.put(json.dumps({"type": "heartbeat"}))
    client = GrpcRelayClient(
        server_addr="farm.local:50051",
        api_key="x",
        agent_id="relay-1",
        send_queue=send_queue,
        loop=asyncio.get_running_loop(),
        channel=object(),
    )

    await client._stream_once(
        initial_meta=json.dumps({"type": "register"}),
    )

    assert received_types == ["register", "heartbeat"]
