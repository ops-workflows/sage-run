"""Hot policy reload and persisted activation gates without a process restart."""

import importlib
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import yaml

pytestmark = pytest.mark.unit

POLICIES = [
    ("salesforce", "allowed_objects", ["Case"], ["Account"], "ALLOWED_OBJECTS"),
    ("github", "allowed_hosts", ["github.example"], ["other.example"], "ALLOWED_HOSTS"),
    ("splunk", "session_cookie_name", "first", "second", "SESSION_COOKIE_NAME"),
    ("cloudwatch", "allowed_regions", ["eu-west-1"], ["eu-west-2"], "ALLOWED_REGIONS"),
    ("gcp-logging", "allowed_projects", ["first-project"], ["second-project"], "ALLOWED_PROJECTS"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("server,key,first,second,attribute", POLICIES)
async def test_http_requests_reload_policy_and_respect_the_deployment_lock(
    monkeypatch, tmp_path, server, key, first, second, attribute
):
    path = tmp_path / "platform-config.yaml"
    path.write_text(yaml.safe_dump({"mcps": {"config": {server: {key: first}}}}))
    monkeypatch.setenv("PLATFORM_CONFIG_FILE", str(path))
    module = importlib.import_module(f"mcps.integrations.mcp_{server.replace('-', '_')}")
    for name, value in list(vars(module).items()):
        if name.isupper():
            monkeypatch.setattr(module, name, value)
    for name in ("_CONFIG_PATH", "PLATFORM_CONFIG_FILE"):
        if hasattr(module, name):
            monkeypatch.setattr(module, name, str(path))
    transport = httpx.ASGITransport(app=module.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        old = getattr(module, attribute)
        guard = tmp_path / ".git/sage-run-deploy.lock.d"
        guard.mkdir(parents=True)
        path.write_text(yaml.safe_dump({"mcps": {"config": {server: {key: second}}}}))
        assert (await client.get("/health")).status_code == 200
        assert getattr(module, attribute) == old
        guard.rmdir()
        assert (await client.get("/health")).status_code == 200
        expected = frozenset(second) if isinstance(second, list) else second
        assert getattr(module, attribute) == expected
        path.write_text("mcps: [invalid yaml")
        failed = httpx.ASGITransport(app=module.app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=failed, base_url="http://test") as failing_client:
            assert (await failing_client.get("/health")).status_code == 500
        assert getattr(module, attribute) == expected


@pytest.mark.asyncio
async def test_revision_is_not_visible_until_the_checkout_writer_releases_its_lock(monkeypatch, tmp_path):
    from shared.lib import config_reload

    monkeypatch.setattr(config_reload.settings, "workflow_repo_local_path", str(tmp_path))
    guard = tmp_path / ".git/sage-run-deploy.lock.d"
    guard.mkdir(parents=True)
    factory = MagicMock()
    monkeypatch.setattr(config_reload, "async_session_factory", factory)
    assert await config_reload.active_config_revision() is None
    factory.assert_not_called()
    guard.rmdir()
    revision = datetime.now(UTC)
    session = AsyncMock()
    session.scalar.return_value = revision
    factory.return_value.__aenter__.return_value = session
    assert await config_reload.active_config_revision() == revision


@pytest.mark.asyncio
async def test_policy_reload_preserves_streamable_mcp_initialization_and_tool_discovery(monkeypatch, tmp_path):
    path = tmp_path / "platform-config.yaml"
    path.write_text("mcps: {config: {salesforce: {allowed_objects: [Case]}}}")
    monkeypatch.setenv("PLATFORM_CONFIG_FILE", str(path))
    module = importlib.import_module("mcps.integrations.mcp_salesforce")
    for name, value in list(vars(module).items()):
        if name.isupper():
            monkeypatch.setattr(module, name, value)
    headers = {"Accept": "application/json, text/event-stream"}
    async with (
        module.app.router.lifespan_context(module.app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=module.app), base_url="http://test") as client,
    ):
        initialized = await client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "reload-test", "version": "1"},
                },
            },
        )
        assert initialized.status_code == 200, initialized.text
        headers["mcp-session-id"] = initialized.headers["mcp-session-id"]
        notification = await client.post(
            "/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"}
        )
        assert notification.status_code == 202
        tools = await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        assert tools.status_code == 200, tools.text
        assert '"tools"' in tools.text
