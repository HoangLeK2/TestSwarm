from __future__ import annotations

from pathlib import Path

from relay.grpc_client import create_grpc_channel


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
