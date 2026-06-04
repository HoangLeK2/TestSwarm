from __future__ import annotations

import io
import json
import sys
from uuid import uuid4
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api.auth.context import decode_access_token
from api.routes import mcp as mcp_routes
from mcp import server
from mcp import token_store


@pytest.fixture(autouse=True)
def _reset_mcp_runtime(monkeypatch, tmp_path):
    server._rate_windows.clear()
    monkeypatch.setenv("DEVICE_FARM_MCP_AUDIT_LOG_PATH", str(tmp_path / "mcp-audit.jsonl"))
    monkeypatch.delenv("DEVICE_FARM_MCP_TOKEN_STORE", raising=False)
    monkeypatch.delenv("DEVICE_FARM_MCP_RATE_LIMIT", raising=False)
    yield
    server._rate_windows.clear()


def _tool_call(name: str, args: dict | None = None) -> dict:
    ctx = server.McpContext(initialized=True)
    return server.handle_tools_call(
        ctx,
        {
            "id": "call-1",
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": name, "arguments": args or {}},
        },
    )


def _content_json(response: dict) -> dict:
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def test_tools_list_exposes_epic10_preview_contract(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "user-token")

    response = server.handle_tools_list(
        server.McpContext(initialized=True),
        {"id": "list-1", "jsonrpc": "2.0", "method": "tools/list"},
    )

    result = response["result"]
    assert result["preview"] is True
    assert result["contract_version"].startswith("df-mcp-preview-")
    assert result["warning"].lower().find("preview") >= 0

    tools = {tool["name"]: tool for tool in result["tools"]}
    for name in {
        "df_device_list",
        "df_device_claim",
        "df_start_session",
        "df_end_session",
        "df_get_session_info",
        "df_campaign_create",
        "df_campaign_run",
        "df_run_scenario",
        "df_content_query",
        "df_save_extraction",
        "df_account_list",
        "df_mcp_registry",
    }:
        assert name in tools
        assert tools[name]["inputSchema"]["type"] == "object"
        assert tools[name]["outputSchema"]["type"] == "object"
        assert tools[name]["metadata"]["preview"] is True
        assert tools[name]["metadata"]["route"].startswith("/")
        assert tools[name]["metadata"]["token_scope"] in {"device", "user", "any"}


def test_stdio_startup_requires_at_least_one_token(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DEVICE_FARM_MCP_ALLOW_UNAUTH", raising=False)
    monkeypatch.setattr(sys, "stderr", io.StringIO())

    with pytest.raises(SystemExit) as exc:
        server.validate_startup_config()

    assert exc.value.code == 2
    assert "MCP_AUTH_TOKEN" in sys.stderr.getvalue()


def test_tool_error_contract_has_df_code_without_traceback(monkeypatch, tmp_path):
    audit_path = tmp_path / "mcp-audit.jsonl"
    monkeypatch.setenv("MCP_AUTH_TOKEN", "user-token")
    monkeypatch.setenv("DEVICE_FARM_MCP_AUDIT_LOG_PATH", str(audit_path))

    response = _tool_call("df_tap", {"x": 1, "y": 2})

    assert "error" not in response
    assert response["result"]["isError"] is True
    payload = _content_json(response)
    assert payload["error"]["code"] == "df.invalid_argument"
    assert payload["error"]["retryable"] is False
    assert "traceback" not in json.dumps(payload).lower()

    entries = [json.loads(line) for line in audit_path.read_text().splitlines()]
    assert entries[-1]["tool_name"] == "df_tap"
    assert entries[-1]["result_code"] == "df.invalid_argument"
    assert entries[-1]["token_id_hash"] != "user-token"


def test_rate_limit_returns_retryable_df_rate_limited(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "user-token")
    monkeypatch.setenv("DEVICE_FARM_MCP_RATE_LIMIT", "1/minute")

    first = _tool_call("df_mcp_registry")
    second = _tool_call("df_mcp_registry")

    assert first["result"].get("isError") is not True
    payload = _content_json(second)
    assert second["result"]["isError"] is True
    assert payload["error"]["code"] == "df.rate_limited"
    assert payload["error"]["retryable"] is True
    assert payload["error"]["details"]["retry_after_ms"] > 0


def test_token_store_hashes_plaintext_and_revokes(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_FARM_MCP_TOKEN_STORE", str(tmp_path / "tokens.json"))

    record, plaintext = token_store.create_token(
        name="agent",
        scope_type="device",
        scope_ref="SER-1",
        owner_user_id="user-1",
        org_id="org-1",
    )

    assert plaintext.startswith("dfmcp_")
    assert plaintext not in (tmp_path / "tokens.json").read_text()
    assert token_store.lookup_token(plaintext).id == record.id
    assert token_store.revoke_token(record.id) is True
    assert token_store.lookup_token(plaintext) is None

    uuid_org = uuid4()
    uuid_record, _uuid_plaintext = token_store.create_token(
        name="uuid-agent",
        scope_type="user",
        scope_ref=uuid4(),
        owner_user_id=uuid4(),
        org_id=uuid_org,
    )
    assert uuid_record.org_id == str(uuid_org)
    assert token_store.list_tokens(org_id=str(uuid_org))[0].id == uuid_record.id


def test_dashboard_minted_token_decodes_to_auth_context(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_FARM_MCP_TOKEN_STORE", str(tmp_path / "tokens.json"))
    _record, plaintext = token_store.create_token(
        name="agent",
        scope_type="user",
        scope_ref=None,
        owner_user_id="user-1",
        org_id="org-1",
    )

    ctx = decode_access_token(plaintext)

    assert ctx.user_id == "user-1"
    assert ctx.org_id == "org-1"
    assert ctx.token_type == "mcp"
    assert "mcp:user" in ctx.roles


@pytest.mark.asyncio
async def test_mcp_api_filters_tokens_audit_and_revoke_by_org(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_FARM_MCP_TOKEN_STORE", str(tmp_path / "tokens.json"))
    audit_path = tmp_path / "audit.jsonl"
    monkeypatch.setenv("DEVICE_FARM_MCP_AUDIT_LOG_PATH", str(audit_path))
    token_a, _plain_a = token_store.create_token(
        name="a",
        scope_type="user",
        owner_user_id="user-a",
        org_id="org-a",
    )
    token_b, _plain_b = token_store.create_token(
        name="b",
        scope_type="user",
        owner_user_id="user-b",
        org_id="org-b",
    )
    audit_path.write_text(
        "\n".join(
            [
                json.dumps({"org_id": "org-a", "tool_name": "df_device_list", "started_at": 1}),
                json.dumps({"org_id": "org-b", "tool_name": "df_account_list", "started_at": 2}),
                json.dumps({"tool_name": "legacy_no_org", "started_at": 3}),
            ]
        ),
        encoding="utf-8",
    )
    user_a = SimpleNamespace(id="user-a", org_id="org-a", role="operator")

    token_response = await mcp_routes.list_mcp_tokens(user=user_a)
    audit_response = await mcp_routes.list_mcp_audit_log(
        user=user_a,
        limit=50,
        offset=0,
    )

    assert [record["id"] for record in token_response["tokens"]] == [token_a.id]
    assert [entry["tool_name"] for entry in audit_response["entries"]] == ["df_device_list"]
    assert token_store.revoke_token(token_b.id, org_id="org-a") is False
    assert await mcp_routes.revoke_mcp_token(token_a.id, user=user_a) == {
        "ok": True,
        "token_id": token_a.id,
    }
    user_without_org = SimpleNamespace(id="user-no-org", org_id=None, role="operator")
    no_org_tokens = await mcp_routes.list_mcp_tokens(user=user_without_org)
    no_org_audit = await mcp_routes.list_mcp_audit_log(
        user=user_without_org,
        limit=50,
        offset=0,
    )

    assert no_org_tokens["tokens"] == []
    assert no_org_audit["entries"] == []
    with pytest.raises(HTTPException) as create_exc:
        await mcp_routes.create_mcp_token(
            mcp_routes.McpTokenCreate(
                name="bad",
                scope_type="user",
                preview_consent=True,
            ),
            user=user_without_org,
        )
    assert create_exc.value.status_code == 403
    with pytest.raises(HTTPException) as exc:
        await mcp_routes.revoke_mcp_token(token_b.id, user=user_without_org)
    assert exc.value.status_code == 404


def test_mcp_auth_token_is_forwarded_to_device_and_user_tools(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "user-token")
    monkeypatch.setenv("DEVICE_FARM_MCP_RATE_LIMIT", "100/minute")

    def fake_http_post(path: str, body: dict, timeout: int = 30):
        assert server._auth_headers()["Authorization"] == "Bearer user-token"
        return {}

    monkeypatch.setattr(server, "_http_post_json", fake_http_post)

    response = _tool_call("df_tap", {"device": "SER-1", "x": 1, "y": 2})

    assert response["result"].get("isError") is not True


def test_dfmcp_user_scope_covers_device_tools_but_device_scope_cannot_call_user_tools(monkeypatch, tmp_path):
    monkeypatch.setenv("DEVICE_FARM_MCP_TOKEN_STORE", str(tmp_path / "tokens.json"))
    monkeypatch.setenv("DEVICE_FARM_MCP_RATE_LIMIT", "100/minute")
    _user_record, user_plaintext = token_store.create_token(
        name="user-agent",
        scope_type="user",
        owner_user_id="user-1",
        org_id="org-1",
    )
    _device_record, device_plaintext = token_store.create_token(
        name="device-agent",
        scope_type="device",
        scope_ref="SER-1",
        owner_user_id="user-1",
        org_id="org-1",
    )

    def fake_http_post(path: str, body: dict, timeout: int = 30):
        assert server._auth_headers()["Authorization"] == f"Bearer {user_plaintext}"
        return {}

    monkeypatch.setattr(server, "_http_post_json", fake_http_post)
    monkeypatch.setenv("MCP_AUTH_TOKEN", user_plaintext)

    user_response = _tool_call("df_tap", {"device": "SER-1", "x": 1, "y": 2})

    assert user_response["result"].get("isError") is not True

    monkeypatch.setenv("MCP_AUTH_TOKEN", device_plaintext)
    device_response = _tool_call("df_campaign_create", {"name": "blocked"})
    payload = _content_json(device_response)

    assert device_response["result"]["isError"] is True
    assert payload["error"]["code"] == "df.permission_denied"


def test_save_extraction_requires_artifact_refs(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", "user-token")

    response = _tool_call("df_save_extraction", {"data": {"post": "hello"}})
    payload = _content_json(response)

    assert response["result"]["isError"] is True
    assert payload["error"]["code"] == "df.evidence_required"
