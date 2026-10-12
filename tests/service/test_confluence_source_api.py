"""HTTP and PostgreSQL contracts for polymorphic Knowledge Sources."""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI

from gateway.api import router
from shared.lib.models import KnowledgeSourceVersion
from shared.lib.platform_secrets import ConfluenceConnection, GitHubAppConnection

pytestmark = [pytest.mark.asyncio, pytest.mark.service]


@pytest.fixture
async def source_client(async_engine, monkeypatch):
    monkeypatch.setattr(
        "gateway.api.load_confluence_connections",
        lambda _path: {
            "corporate-wiki": ConfluenceConnection(
                "corporate-wiki", "https://company.atlassian.net/wiki", "private-email", "private-token"
            ),
            "other-wiki": ConfluenceConnection(
                "other-wiki", "https://other.atlassian.net/wiki", "other-email", "other-token"
            ),
        },
    )
    monkeypatch.setattr(
        "gateway.api.load_github_app_connections",
        lambda _path: {
            "github-public": GitHubAppConnection(
                "github-public", "https://github.example.com", "https://api.github.example.com", "1", "2", ""
            )
        },
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client


def confluence_payload():
    return {
        "canonical_alias": "platform-runbooks",
        "display_name": "Platform runbooks",
        "source_kind": "confluence",
        "index_kind": "hybrid_vector",
        "credential_ref": "corporate-wiki",
        "source_config": {"root_pages": ["123", "https://company.atlassian.net/wiki/spaces/OPS/pages/456/Runbooks"]},
        "sync_policy": {"interval_sec": 3600},
        "enabled": True,
    }


@pytest.mark.parametrize(
    "root",
    [
        "123",
        "https://company.atlassian.net/wiki/spaces/OPS/pages/123",
        "https://company.atlassian.net/wiki/spaces/OPS/pages/123/Runbooks",
        "https://company.atlassian.net/wiki/pages/viewpage.action?pageId=123",
    ],
)
async def test_confluence_normalized_source_and_redacted_connections(source_client, root):
    payload = confluence_payload()
    payload["source_config"]["root_pages"] = [root, "123"]
    response = await source_client.post("/api/platform/knowledge-sources", json=payload)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["source_config"] == {
        "root_page_ids": ["123"],
        "include_descendants": True,
        "body_format": "storage",
        "lexical_config": "simple",
        "scrub_patterns": [],
    }
    assert source["repository_url"] is None
    assert source["default_ref"] is None
    assert source["serving_suspended_at"] is None
    assert (await source_client.get(f"/api/platform/knowledge-sources/{source['id']}")).json() == source
    assert source in (await source_client.get("/api/platform/knowledge-sources")).json()
    connections = await source_client.get("/api/platform/knowledge-sources/confluence-connections")
    assert connections.status_code == 200
    assert connections.json() == [
        {"name": "corporate-wiki", "base_url": "https://company.atlassian.net/wiki"},
        {"name": "other-wiki", "base_url": "https://other.atlassian.net/wiki"},
    ]


@pytest.mark.parametrize(
    "root",
    [
        "https://evil.example/wiki/spaces/OPS/pages/123",
        "http://company.atlassian.net/wiki/spaces/OPS/pages/123",
        "https://company.atlassian.net:444/wiki/spaces/OPS/pages/123",
        "https://company.atlassian.net/spaces/OPS/pages/123",
        "https://company.atlassian.net/wiki-other/spaces/OPS/pages/123",
        "https://token@company.atlassian.net/wiki/spaces/OPS/pages/123",
        "https://company.atlassian.net/wiki/api/v2/pages/123",
        "https://company.atlassian.net/wiki/pages/viewpage.action?pageId=123&pageId=456",
        "https://company.atlassian.net/wiki/pages/viewpage.action?pageId=abc",
        "https://company.atlassian.net/wiki/spaces/OPS/pages/abc",
        "https://company.atlassian.net/wiki/spaces/OPS/pages/123/../../456",
        "not-a-page-id",
        "",
    ],
)
async def test_invalid_confluence_roots_return_422(source_client, root):
    payload = confluence_payload()
    payload["source_config"]["root_pages"] = [root]
    assert (await source_client.post("/api/platform/knowledge-sources", json=payload)).status_code == 422


@pytest.mark.parametrize(
    "replacement",
    [
        {"source_kind": "unknown"},
        {"index_kind": "code_graph"},
        {"credential_ref": "github-public"},
        {"credential_ref": "unknown"},
        {"canonical_alias": "invalid/alias"},
        {"canonical_alias": None},
        {"display_name": "   "},
        {"token": "forbidden"},
        {"repository": "org/repo"},
        {"enabled": "true"},
        {"sync_policy": {"interval_sec": True}},
        {"sync_policy": {"interval_sec": -1}},
        {"sync_policy": {"schedule": "daily"}},
        {"source_config": {"root_page_ids": [123]}},
        {"source_config": {"root_page_ids": ["abc"]}},
        {"source_config": {"root_page_ids": []}},
        {"source_config": {"root_pages": "123"}},
        {"source_config": {"root_page_ids": ["123"], "root_pages": ["456"]}},
        {"source_config": {"root_page_ids": ["123"], "include_descendants": 1}},
        {"source_config": {"root_page_ids": ["123"], "body_format": "view"}},
        {"source_config": {"root_page_ids": ["123"], "lexical_config": "unknown"}},
        {"source_config": {"root_page_ids": ["123"], "scrub_patterns": ["valid", "["]}},
        {"source_config": {"root_page_ids": ["123"], "scrub_patterns": "not-a-list"}},
        {"source_config": {"root_page_ids": ["123"], "scrub_patterns": [1]}},
        {"source_config": {"root_page_ids": ["123"], "base_url": "https://evil.example"}},
        {"source_config": {}},
    ],
)
async def test_strict_source_requests_return_422(source_client, replacement):
    payload = {**confluence_payload(), **replacement}
    assert (await source_client.post("/api/platform/knowledge-sources", json=payload)).status_code == 422


async def test_exact_pages_option_round_trips(source_client):
    payload = confluence_payload()
    payload["source_config"]["include_descendants"] = False
    payload["source_config"]["scrub_patterns"] = ["", r"(?i)secret=\S+"]
    response = await source_client.post("/api/platform/knowledge-sources", json=payload)
    assert response.status_code == 201, response.text
    source = response.json()
    assert source["source_config"]["include_descendants"] is False
    assert source["source_config"]["scrub_patterns"] == [r"(?i)secret=\S+"]
    response = await source_client.put(f"/api/platform/knowledge-sources/{source['id']}", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["source_config"]["include_descendants"] is False


async def test_invalid_scrub_rule_reports_its_line_without_echoing_pattern(source_client):
    payload = confluence_payload()
    payload["source_config"]["scrub_patterns"] = ["valid", "["]
    response = await source_client.post("/api/platform/knowledge-sources", json=payload)
    assert response.status_code == 422
    assert "scrub rule line 2" in response.text


async def test_update_security_boundary_and_disabled_sync(source_client):
    payload = confluence_payload()
    source = (await source_client.post("/api/platform/knowledge-sources", json=payload)).json()
    source_url = f"/api/platform/knowledge-sources/{source['id']}"
    assert (await source_client.put(source_url, json={**payload, "canonical_alias": "renamed"})).status_code == 422
    assert (
        await source_client.put(
            source_url,
            json={
                "source_kind": "github",
                "index_kind": "code_graph",
                "repository": "org/repo",
                "credential_ref": "github-public",
            },
        )
    ).status_code == 422
    assert (await source_client.post(f"{source_url}/sync")).status_code == 202
    changed = {**payload, "source_config": {"root_page_ids": ["789"]}}
    assert (await source_client.put(source_url, json=changed)).status_code == 409
    assert (
        await source_client.put(
            source_url,
            json={**payload, "credential_ref": "other-wiki", "source_config": {"root_page_ids": ["123", "456"]}},
        )
    ).status_code == 409
    disabled = await source_client.put(source_url, json={**payload, "enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["source_config"] == source["source_config"]
    assert (await source_client.post(f"{source_url}/sync")).status_code == 409


async def test_root_change_suspends_serving_and_alias_remains_stable(source_client):
    payload = confluence_payload()
    source = (await source_client.post("/api/platform/knowledge-sources", json=payload)).json()
    payload.pop("canonical_alias")
    payload["source_config"] = {"root_page_ids": ["789"]}
    updated = await source_client.put(f"/api/platform/knowledge-sources/{source['id']}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["canonical_alias"] == source["canonical_alias"]
    assert updated.json()["serving_suspended_at"] is not None
    assert "successful sync" in updated.json()["serving_suspension_reason"]


async def test_legacy_and_explicit_github_aliases_and_dual_writes(source_client):
    payload = {"repository": "org/application", "credential_ref": "github-public"}
    source = (await source_client.post("/api/platform/knowledge-sources", json=payload)).json()
    assert source["canonical_alias"] == "application"
    changed = await source_client.put(
        f"/api/platform/knowledge-sources/{source['id']}", json={**payload, "repository": "org/new-repo"}
    )
    assert changed.status_code == 200
    assert changed.json()["canonical_alias"] == "application"
    assert changed.json()["source_config"]["repository_url"] == changed.json()["repository_url"]
    explicit = await source_client.post(
        "/api/platform/knowledge-sources", json={**payload, "canonical_alias": "custom-alias"}
    )
    assert explicit.status_code == 201
    assert explicit.json()["canonical_alias"] == "custom-alias"
    assert (
        await source_client.post("/api/platform/knowledge-sources", json={**payload, "index_kind": "hybrid_vector"})
    ).status_code == 422
    assert (
        await source_client.post(
            "/api/platform/knowledge-sources", json={**payload, "source_config": {"root_page_ids": ["123"]}}
        )
    ).status_code == 422


async def test_generic_vector_version_has_nullable_graph_fields(source_client, db_session):
    source = (await source_client.post("/api/platform/knowledge-sources", json=confluence_payload())).json()
    db_session.add(
        KnowledgeSourceVersion(
            source_id=uuid.UUID(source["id"]),
            source_revision="snapshot-digest",
            index_kind="hybrid_vector",
            indexer_version="hybrid-1",
            index_config_hash="embedding-config",
            status="succeeded",
            stats={"indexed_pages": 4, "chunks_embedded": 12},
        )
    )
    await db_session.commit()
    response = await source_client.get(f"/api/platform/knowledge-sources/{source['id']}/versions")
    assert response.status_code == 200
    version = response.json()[0]
    assert version["source_revision"] == "snapshot-digest"
    assert version["index_config_hash"] == "embedding-config"
    assert version["stats"] == {"indexed_pages": 4, "chunks_embedded": 12}
    assert version["commit_sha"] is None
    assert version["graphify_version"] is None
