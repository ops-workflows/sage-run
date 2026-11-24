"""Unit tests for Salesforce MCP policy and OAuth client credentials."""

from __future__ import annotations

import importlib
from functools import partial
from pathlib import Path
from textwrap import dedent
from urllib.parse import parse_qs

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport

pytestmark = pytest.mark.unit


def _write_policy(path: Path, body: str) -> str:
    path.write_text(dedent(body).lstrip(), encoding="utf-8")
    return str(path)


def _reload_with_config(monkeypatch, config_path: str):
    monkeypatch.setenv("PLATFORM_CONFIG_FILE", config_path)
    import mcps.integrations.mcp_salesforce as sf

    return importlib.reload(sf)


def test_policy_loads_from_platform_config(monkeypatch, tmp_path):
    config = _write_policy(
        tmp_path / "platform-config.yaml",
        """
        mcps:
          config:
            salesforce:
              api_version: v55.0
              max_query_limit: 50
              max_query_fields: 5
              allowed_objects:
                - Case
                - Account
              allowed_tooling_objects:
                - ValidationRule
              filter_required_objects:
                - Account
              object_fields:
                Case: "Id, Subject, Status"
              tooling_object_fields:
                ValidationRule: "Id, ValidationName"
        """,
    )

    sf = _reload_with_config(monkeypatch, config)

    assert sf.API_VERSION == "v55.0"
    assert sf.MAX_QUERY_LIMIT == 50
    assert sf.MAX_QUERY_FIELDS == 5
    assert sorted(sf.ALLOWED_OBJECTS) == ["Account", "Case"]
    assert sorted(sf.ALLOWED_TOOLING_OBJECTS) == ["ValidationRule"]
    assert sorted(sf.FILTER_REQUIRED_OBJECTS) == ["Account"]
    assert sf.OBJECT_FIELDS["Case"] == "Id, Subject, Status"
    assert sf.TOOLING_OBJECT_FIELDS["ValidationRule"] == "Id, ValidationName"


def test_no_hardcoded_policy_without_config(monkeypatch, tmp_path):
    config = _write_policy(tmp_path / "platform-config.yaml", "config: {}\n")

    sf = _reload_with_config(monkeypatch, config)

    # The public server ships no built-in org policy: absent config means no
    # allowed objects and safe scalar defaults.
    assert not sf.ALLOWED_OBJECTS
    assert not sf.ALLOWED_TOOLING_OBJECTS
    assert not sf.OBJECT_FIELDS
    assert sf.API_VERSION == sf.DEFAULT_API_VERSION
    assert sf.MAX_QUERY_LIMIT == sf.DEFAULT_MAX_QUERY_LIMIT
    assert sf.MAX_QUERY_FIELDS == sf.DEFAULT_MAX_QUERY_FIELDS


def test_default_fields_fall_back_to_generic_set(monkeypatch, tmp_path):
    config = _write_policy(
        tmp_path / "platform-config.yaml",
        """
        mcps:
          config:
            salesforce:
              allowed_objects:
                - Case
        """,
    )

    sf = _reload_with_config(monkeypatch, config)

    assert sf._default_fields_for_object("Case") == "Id, Name, CreatedDate, LastModifiedDate"
    assert sf._default_fields_for_tooling_object("ValidationRule") == "Id"


@pytest.fixture
def salesforce(monkeypatch, tmp_path):
    config = _write_policy(
        tmp_path / "platform-config.yaml",
        "mcps: {config: {salesforce: {instance_url: https://org.example.test/, allowed_objects: [Case]}}}",
    )
    return _reload_with_config(monkeypatch, config)


@pytest.mark.asyncio
async def test_client_credentials_cache_and_session_renewal(salesforce, monkeypatch):
    issued = 0
    used_tokens: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal issued
        assert request.url.host == "org.example.test"
        if request.method == "POST":
            assert request.url.path == "/services/oauth2/token"
            assert parse_qs(request.content.decode()) == {
                "grant_type": ["client_credentials"],
                "client_id": ["app-id"],
                "client_secret": ["app-secret"],
            }
            assert "authorization" not in request.headers
            issued += 1
            return httpx.Response(200, json={"access_token": f"token-{issued}"})

        assert request.url.path == "/services/data/v60.0/query"
        token = request.headers["authorization"]
        used_tokens.append(token)
        if len(used_tokens) >= 3 and token == "Bearer token-1":
            return httpx.Response(401, json=[{"errorCode": "INVALID_SESSION_ID"}])
        return httpx.Response(200, json={"records": []})

    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=httpx.MockTransport(handle)))
    headers = {
        "X-Salesforce-Client-Id": "app-id",
        "X-Salesforce-Client-Secret": "app-secret",
        "X-Salesforce-Instance-Url": "https://ignored.example.test",
        "Authorization": "Bearer ignored",
    }
    transport = StreamableHttpTransport(
        "http://test/mcp",
        headers=headers,
        httpx_client_factory=partial(httpx.AsyncClient, transport=httpx.ASGITransport(app=salesforce.app)),
    )
    async with salesforce.app.router.lifespan_context(salesforce.app), Client(transport) as client:
        assert issued == 0
        for _ in range(4):
            result = await client.call_tool("query_records", {"object_type": "Case", "fields": ["Id"]})
            assert result.data == {"records": []}

    assert issued == 2
    assert used_tokens == ["Bearer token-1"] * 3 + ["Bearer token-2"] * 2


def test_expiry_and_credentials_are_checked_before_reusing_a_token(salesforce, monkeypatch, caplog):
    now = 100
    issued = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal issued
        if request.method == "POST":
            secret = parse_qs(request.content.decode())["client_secret"][0]
            if secret != "valid-secret":
                return httpx.Response(400, json={"error_description": f"Rejected: {secret}"})
            issued += 1
            return httpx.Response(200, json={"access_token": f"token-{issued}", "expires_in": 10})

        assert request.headers["authorization"] == f"Bearer token-{issued}"
        return httpx.Response(200, json={"records": []})

    monkeypatch.setattr(httpx, "Client", partial(httpx.Client, transport=httpx.MockTransport(handle)))
    monkeypatch.setattr(salesforce, "time", type("Clock", (), {"monotonic": lambda: now}))
    headers = {"x-salesforce-client-id": "app-id", "x-salesforce-client-secret": "valid-secret"}
    assert salesforce._sf_request("/query", headers=headers) == {"records": []}

    assert salesforce._sf_request("/query", headers={**headers, "x-salesforce-client-secret": "invalid-secret"}) == {
        "error": "Salesforce OAuth token exchange failed (HTTP 400)"
    }
    assert "invalid-secret" not in caplog.text
    assert (
        "x-salesforce-client-secret"
        in salesforce._sf_request("/query", headers={"x-salesforce-client-id": "app-id"})["error"]
    )
    assert issued == 1

    now += 10
    assert salesforce._sf_request("/query", headers=headers) == {"records": []}
    assert issued == 2
