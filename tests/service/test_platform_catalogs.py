"""Layer 1 — /platform/* catalog endpoints.

Exercises the hindsight-, connector-, and agent-memory catalogs at the
HTTP layer. Hindsight is not reachable in the test environment, so the
endpoint should return ``hindsight_available: false`` and an empty bank
list (not 500).
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

pytestmark = pytest.mark.service


def test_memory_catalog_only_lists_configured_banks(monkeypatch, tmp_path) -> None:
    from gateway import api as gateway_api
    from shared.lib.config import settings

    config = tmp_path / "platform-config.yaml"
    config.write_text(
        "memory:\n"
        "  banks:\n"
        "    business:\n"
        "      example-workflow: service-decisions\n"
        "    learning:\n"
        "      example-workflow: service-learning\n"
    )
    monkeypatch.setattr(settings, "platform_config_file", str(config))

    banks = gateway_api._hindsight_banks_catalog({"incident-rca", "service-decisions", "old-bank"})

    assert {bank.bank_id for bank in banks} == {"service-decisions", "service-learning"}
    assert all(bank.workflows == ["example-workflow"] for bank in banks)
    assert next(bank for bank in banks if bank.bank_id == "service-decisions").listed_in_hindsight is True
    assert next(bank for bank in banks if bank.bank_id == "service-learning").listed_in_hindsight is False

    config.write_text("memory:\n  banks: {}\n")
    assert gateway_api._hindsight_banks_catalog({"incident-rca", "old-bank"}) == []


async def _make_client(fixture_workflows_dir: Path) -> httpx.AsyncClient:
    from shared.lib.config import settings

    settings.workflow_repo_paths = str(fixture_workflows_dir)
    # Point hindsight at an unreachable host so _hindsight_available() is False
    settings.hindsight_url = "http://127.0.0.1:1"
    # Object store client construction requires a non-empty secret key
    if not getattr(settings, "object_store_secret_key", ""):
        settings.object_store_secret_key = "test-secret"

    from gateway.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://gateway.test")


@pytest.mark.asyncio
async def test_platform_memories_endpoint_returns_shape(async_engine, fixture_workflows_dir: Path, monkeypatch) -> None:
    # The object store is not reachable from the test host — stub the catalog
    # list call so the endpoint returns an empty agent_memories list rather
    # than 500.
    from gateway import api as gateway_api

    monkeypatch.setattr(gateway_api, "list_objects", lambda *a, **k: [])  # noqa: ARG005

    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.get("/api/platform/memories")
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        # Shape assertions
        assert "hindsight_available" in payload
        assert "hindsight_banks" in payload
        assert "agent_memories" in payload
        # Hindsight unreachable in tests
        assert payload["hindsight_available"] is False
        assert isinstance(payload["hindsight_banks"], list)


@pytest.mark.asyncio
async def test_platform_connectors_endpoint_lists_configured_instances(
    async_engine, fixture_workflows_dir: Path, monkeypatch, tmp_path
) -> None:
    from shared.lib.config import settings

    config = tmp_path / "platform-config.yaml"
    config.write_text(
        "connectors:\n"
        "  enabled:\n"
        "    - event-intake\n"
        "  instances:\n"
        "    event-intake:\n"
        "      type: gcp-pubsub\n"
        "      display_name: Event Intake\n"
        "      source:\n"
        "        type: pubsub\n"
        "        subscription: my-sub\n"
        "      target:\n"
        "        workflow: example-workflow\n"
        "        message_channel: alerts\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "platform_config_file", str(config))

    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.get("/api/platform/connectors")
        assert resp.status_code == 200, resp.text
        connectors = resp.json()
        ids = {c["id"] for c in connectors}
        assert "event-intake" in ids
        event_intake = next(connector for connector in connectors if connector["id"] == "event-intake")
        assert event_intake["paused"] is True

        paused = await client.post("/api/platform/connectors/event-intake/pause")
        assert paused.status_code == 200, paused.text
        assert paused.json()["paused"] is True

        listed = await client.get("/api/platform/connectors")
        event_intake = next(connector for connector in listed.json() if connector["id"] == "event-intake")
        assert event_intake["paused"] is True

        resumed = await client.post("/api/platform/connectors/event-intake/resume")
        assert resumed.status_code == 200, resumed.text
        assert resumed.json()["paused"] is False


@pytest.mark.asyncio
async def test_platform_mcp_endpoint_returns_catalog(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.get("/api/platform/mcp")
        assert resp.status_code == 200, resp.text
        servers = resp.json()
        assert isinstance(servers, list)
        # The test fixture plugin declares a `testserver` MCP, but whether
        # it shows up here depends on mcps catalog — the point is
        # that the endpoint returns 200 and a list.


@pytest.mark.asyncio
@pytest.mark.parametrize("root_kind", ["repo", "workflows", "package", "mounted-repo"])
async def test_mcp_catalog_includes_core_and_enabled_workflow_servers(
    async_engine, monkeypatch, tmp_path, root_kind
) -> None:
    from shared.lib.config import settings

    if root_kind == "mounted-repo":
        tmp_path = tmp_path / "workflows"
        tmp_path.mkdir()
    config = tmp_path / "platform-config.yaml"
    config.write_text("mcps:\n  enabled: [custom-service, gcp-logging]\n")
    monkeypatch.setattr(settings, "platform_config_file", str(config))
    for server_id in ("custom-service", "disabled-service"):
        directory = tmp_path / "mcps" / server_id
        directory.mkdir(parents=True)
        (directory / f"mcp_{server_id.replace('-', '_')}.py").write_text(
            '"""Custom workflow service."""\n'
            'mcp = FastMCP("Custom Service")\n'
            '@mcp.tool(annotations={"readOnlyHint": True})\n'
            "async def inspect_service():\n"
            '    """Inspect service state."""\n'
            "    return {}\n"
        )
    workflow = tmp_path / "workflows" / "example-workflow"
    workflow.mkdir(parents=True)
    (workflow / "agent.yaml").write_text("name: example-workflow\n")
    (workflow / ".mcp.json").write_text('{"mcpServers": {"custom-service": {}, "knowledge": {}}}')

    catalog_root = {
        "repo": tmp_path,
        "workflows": workflow.parent,
        "package": workflow,
        "mounted-repo": tmp_path,
    }[root_kind]
    async with await _make_client(catalog_root) as client:
        response = await client.get("/api/platform/mcp")
    assert response.status_code == 200
    servers = {server["id"]: server for server in response.json()}
    assert {"message", "memory", "platform", "knowledge", "gcp-logging", "custom-service"} <= servers.keys()
    assert "disabled-service" not in servers
    assert "salesforce" not in servers
    assert servers["knowledge"]["group"] == "platform"
    assert any(tool["name"] == "list_sources" for tool in servers["knowledge"]["tools"])
    custom = servers["custom-service"]
    assert custom["group"] == "workflow"
    assert custom["used_by"] == ["example-workflow"]
    assert custom["tools"] == [
        {"name": "inspect_service", "description": "Inspect service state.", "read_only": True, "open_world": False}
    ]
