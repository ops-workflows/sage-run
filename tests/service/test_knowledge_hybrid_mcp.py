"""Real PostgreSQL coverage of the workflow-authorized Knowledge MCP boundary."""

from __future__ import annotations

import importlib
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
import yaml
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.lib.config import settings
from shared.lib.knowledge_source_authorization import KnowledgeSourceAccessError
from shared.lib.knowledge_source_hybrid_retrieval import HybridKnowledgeUnavailableError
from shared.lib.knowledge_source_serving import (
    KnowledgeSourceCatalog,
    KnowledgeSourceServingError,
    KnowledgeSourceServingRegistry,
    ServingSnapshot,
)
from shared.lib.models import (
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)
from shared.lib.task_call_budget import TaskCallBudget

pytestmark = [pytest.mark.service, pytest.mark.asyncio]


@pytest.fixture
async def knowledge_mcp(async_engine, tmp_path, monkeypatch):
    for name, value in {
        "knowledge_source_object_store_bucket": "test-knowledge",
        "knowledge_embeddings_openai_base_url": "https://embeddings.example/v1",
        "knowledge_embeddings_openai_model": "test-embedding",
        "knowledge_embeddings_dimensions": 3,
        "knowledge_rerank_enabled": False,
        "knowledge_require_explicit_source_grants": False,
        "workflow_repo_url": "",
        "workflow_repo_paths": str(tmp_path / "workflows"),
        "workflow_root": str(tmp_path / "workflows"),
    }.items():
        monkeypatch.setattr(settings, name, value)
    main = importlib.import_module("mcps.core.mcp_knowledge")
    factory = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="test-knowledge")
    monkeypatch.setattr(main, "registry", registry)
    monkeypatch.setattr(main, "catalog", KnowledgeSourceCatalog(registry))
    monkeypatch.setattr(main, "async_session_factory", factory)
    workflow = "online-alerts-investigator"
    package = tmp_path / "workflows" / workflow
    package.mkdir(parents=True)
    config = {"name": workflow, "description": "Test", "knowledge": {"sources": ["wiki", "code"]}}
    agent_yaml = package / "agent.yaml"
    agent_yaml.write_text(yaml.safe_dump(config), encoding="utf-8")
    (package / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    sources = {}
    versions = {}
    async with factory() as session:
        for alias in ("wiki", "private-wiki", "code"):
            graph = alias == "code"
            source = KnowledgeSource(
                canonical_alias=alias,
                display_name=alias.title(),
                source_kind="github" if graph else "confluence",
                index_kind="code_graph" if graph else "hybrid_vector",
                source_config={"description": "Operator summary", "token": "not-for-serving"},
            )
            session.add(source)
            await session.flush()
            version = KnowledgeSourceVersion(
                source_id=source.id,
                source_revision="current-" + alias,
                index_kind=source.index_kind,
                indexer_version="test",
                index_config_hash="b" * 64,
                commit_sha="a" * 40 if graph else None,
                graphify_version="test" if graph else None,
                extraction_config_hash="b" * 64 if graph else None,
                status="succeeded",
                finished_at=datetime.now(UTC),
                stats={"embedding_model": "test-embedding", "embedding_dimensions": 3, "lexical_config": "simple"},
            )
            session.add(version)
            await session.flush()
            source.current_successful_version_id = version.id
            sources[alias], versions[alias] = source, version
            if graph:
                registry._by_alias[alias] = ServingSnapshot(
                    source.id,
                    version.id,
                    alias,
                    version.commit_sha,
                    {"nodes": [], "links": [], "hyperedges": []},
                    tmp_path,
                )
                continue
            for page_id, content in [("1", "Current database recovery procedure"), ("2", "Platform operations guide")]:
                document = KnowledgeDocumentRevision(
                    source_id=source.id,
                    external_id=page_id,
                    provider_revision="1",
                    title="Runbook " + page_id,
                    canonical_url=f"https://wiki.example/pages/{page_id}",
                    hierarchy_path=["Operations"],
                    normalized_content=content,
                    content_hash=("c" if page_id == "1" else "d") * 64,
                )
                session.add(document)
                await session.flush()
                session.add(
                    KnowledgeChunk(
                        document_revision_id=document.id,
                        index_config_hash=version.index_config_hash,
                        ordinal=0,
                        heading_path=["Recovery"],
                        content=content,
                        content_hash=document.content_hash,
                        estimated_tokens=8,
                        lexical_text=content,
                        search_vector=func.to_tsvector("simple", content),
                        embedding=[1.0, 0.0, 0.0],
                        embedding_model="test-embedding",
                        embedding_dimensions=3,
                    )
                )
                session.add(
                    KnowledgeSourceVersionDocument(
                        version_id=version.id,
                        document_revision_id=document.id,
                        external_id=page_id,
                        root_page_id="1",
                    )
                )
        old = KnowledgeSourceVersion(
            source_id=sources["wiki"].id,
            source_revision="old-wiki",
            index_kind="hybrid_vector",
            indexer_version="test",
            index_config_hash="b" * 64,
            status="succeeded",
            stats=versions["wiki"].stats,
        )
        session.add(old)
        document = KnowledgeDocumentRevision(
            source_id=sources["wiki"].id,
            external_id="old",
            provider_revision="1",
            title="Obsolete",
            canonical_url="https://wiki.example/pages/old",
            normalized_content="Obsolete recovery procedure",
            content_hash="e" * 64,
        )
        session.add(document)
        await session.flush()
        session.add(
            KnowledgeChunk(
                document_revision_id=document.id,
                index_config_hash="b" * 64,
                ordinal=0,
                heading_path=[],
                content=document.normalized_content,
                content_hash=document.content_hash,
                estimated_tokens=8,
                lexical_text=document.normalized_content,
                search_vector=func.to_tsvector("simple", document.normalized_content),
                embedding=[1.0, 0.0, 0.0],
                embedding_model="test-embedding",
                embedding_dimensions=3,
            )
        )
        session.add(
            KnowledgeSourceVersionDocument(
                version_id=old.id,
                document_revision_id=document.id,
                external_id="old",
                root_page_id="1",
            )
        )
        await session.commit()

    requests = []
    provider = SimpleNamespace(embedding_status=200, rerank_status=200)

    async def handle(request):
        requests.append(request)
        payload = json.loads(request.content)
        if request.url.path.endswith("/rerank"):
            return httpx.Response(
                provider.rerank_status,
                json={
                    "results": [
                        {"index": index, "relevance_score": 1.0 / (index + 1)}
                        for index in range(len(payload["documents"]))
                    ]
                },
            )
        assert payload["model"] == "test-embedding" and payload["dimensions"] == 3
        return httpx.Response(
            provider.embedding_status,
            json={
                "model": "test-embedding",
                "data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}],
            },
        )

    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        main,
        "httpx",
        SimpleNamespace(
            AsyncClient=lambda: real_client(transport=httpx.MockTransport(handle)),
        ),
    )
    consumed = []
    monkeypatch.setattr(main.task_call_budget, "consume", consumed.append)
    return SimpleNamespace(
        main=main,
        sources=sources,
        versions=versions,
        factory=factory,
        registry=registry,
        config=config,
        agent_yaml=agent_yaml,
        package=package,
        requests=requests,
        provider=provider,
        headers={"x-task-workflow": workflow, "x-task-id": str(uuid.uuid4())},
        consumed=consumed,
    )


async def test_mcp_hybrid_promoted_snapshot_catalog_provenance_and_budget(knowledge_mcp):
    fixture = knowledge_mcp
    listed = await fixture.main.list_sources(headers=fixture.headers)
    assert [item["alias"] for item in listed] == ["code", "wiki"]
    assert listed[0]["capabilities"] == ["graph", "literal_source"] and listed[0]["ready"]
    assert listed[1]["capabilities"] == ["hybrid_search"] and listed[1]["ready"]
    assert listed[1]["promoted_at"] and listed[1]["source_revision"] == "current-wiki"
    assert "not-for-serving" not in str(listed)
    result = await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    assert result["version_id"] == str(fixture.versions["wiki"].id)
    assert result["retrieval_mode"] == "hybrid" and result["warnings"] == []
    assert {item["page_id"] for item in result["results"]} == {"1", "2"}
    assert all(item["url"].startswith("https://wiki.example/") for item in result["results"])
    assert all(item["source_kind"] == "confluence" and item["source"] == "wiki" for item in result["results"])
    assert "Obsolete" not in str(result)
    assert fixture.consumed == [fixture.headers["x-task-id"]] * 2
    fixture.main.get_graph_overview("code", headers=fixture.headers)
    assert len(fixture.consumed) == 3


@pytest.mark.parametrize(
    "config",
    [
        {"knowledge": {"sources": []}},
        {"knowledge": {"sources": ["private-wiki"]}},
        {"knowledge": None},
        {"knowledge": {"sources": ["*"]}},
    ],
)
async def test_mcp_denies_undeclared_and_malformed_grants_before_embedding(knowledge_mcp, config):
    fixture = knowledge_mcp
    fixture.config.update(config)
    fixture.agent_yaml.write_text(yaml.safe_dump(fixture.config), encoding="utf-8")
    with pytest.raises(KnowledgeSourceAccessError):
        await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    with pytest.raises(KnowledgeSourceAccessError):
        fixture.main.get_graph_overview("code", headers=fixture.headers)
    assert fixture.requests == []
    assert "wiki" not in [item["alias"] for item in await fixture.main.list_sources(headers=fixture.headers)]
    assert len(fixture.consumed) == 3


async def test_missing_grants_compatibility_warning_strict_and_missing_mcp(knowledge_mcp, monkeypatch, caplog):
    fixture = knowledge_mcp
    fixture.config.pop("knowledge")
    fixture.agent_yaml.write_text(yaml.safe_dump(fixture.config), encoding="utf-8")
    assert len(await fixture.main.list_sources(headers=fixture.headers)) == 3
    assert "deprecated" in caplog.text
    monkeypatch.setattr(settings, "knowledge_require_explicit_source_grants", True)
    assert await fixture.main.list_sources(headers=fixture.headers) == []
    with pytest.raises(KnowledgeSourceAccessError):
        await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    monkeypatch.setattr(settings, "knowledge_require_explicit_source_grants", False)
    (fixture.package / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    assert await fixture.main.list_sources(headers=fixture.headers) == []
    with pytest.raises(KnowledgeSourceAccessError):
        fixture.main.get_graph_overview("code", headers=fixture.headers)


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"enabled": False}, "disabled"),
        ({"serving_suspended_at": datetime.now(UTC)}, "suspended"),
        ({"current_successful_version_id": None}, "unavailable"),
    ],
)
async def test_live_revocation_rejects_hybrid_and_refresh_evicts_graph(knowledge_mcp, change, expected):
    fixture = knowledge_mcp
    async with fixture.factory() as session:
        await session.execute(update(KnowledgeSource).values(**change))
        await session.commit()
    listed = await fixture.main.list_sources(headers=fixture.headers)
    assert {item["status"] for item in listed} == {expected}
    with pytest.raises(HybridKnowledgeUnavailableError):
        await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    async with fixture.factory() as session:
        await fixture.registry.refresh(session)
    assert fixture.registry._by_alias == {}
    with pytest.raises(KnowledgeSourceServingError):
        fixture.main.get_graph_overview("code", headers=fixture.headers)
    assert fixture.requests == []


@pytest.mark.parametrize("mismatch", ["model", "dimensions", "provider"])
async def test_embedding_contract_mismatch_or_failure_is_warned_lexical(knowledge_mcp, mismatch):
    fixture = knowledge_mcp
    if mismatch == "provider":
        fixture.provider.embedding_status = 503
    else:
        stats = {**fixture.versions["wiki"].stats}
        stats["embedding_model" if mismatch == "model" else "embedding_dimensions"] = (
            "other-embedding" if mismatch == "model" else 4
        )
        async with fixture.factory() as session:
            await session.execute(
                update(KnowledgeSourceVersion)
                .where(
                    KnowledgeSourceVersion.id == fixture.versions["wiki"].id,
                )
                .values(stats=stats)
            )
            await session.commit()
    result = await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    assert result["retrieval_mode"] == "lexical_fallback" and result["warnings"]
    assert [item["page_id"] for item in result["results"]] == ["1"]
    assert result["results"][0]["scores"]["dense_rank"] is None
    assert len(fixture.requests) == (1 if mismatch == "provider" else 0)


async def test_missing_embedding_configuration_and_wrong_capability(knowledge_mcp, monkeypatch):
    fixture = knowledge_mcp
    with pytest.raises(HybridKnowledgeUnavailableError, match="hybrid search"):
        await fixture.main.search_knowledge("code", "recovery", headers=fixture.headers)
    with pytest.raises(KnowledgeSourceServingError, match="graph capability"):
        fixture.main.get_graph_overview("wiki", headers=fixture.headers)
    monkeypatch.setattr(settings, "knowledge_embeddings_openai_model", "")
    monkeypatch.setattr(settings, "knowledge_embeddings_dimensions", 0)
    with pytest.raises(RuntimeError, match="configure the embedding model and dimensions"):
        await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    assert fixture.requests == []
    assert len(fixture.consumed) == 3


@pytest.mark.parametrize("rerank_status", [200, 503])
async def test_reranker_is_optional_and_fails_open(knowledge_mcp, monkeypatch, rerank_status):
    fixture = knowledge_mcp
    monkeypatch.setattr(settings, "knowledge_rerank_enabled", True)
    monkeypatch.setattr(settings, "knowledge_rerank_base_url", "https://embeddings.example")
    monkeypatch.setattr(settings, "knowledge_rerank_model", "test-reranker")
    fixture.provider.rerank_status = rerank_status
    result = await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    assert result["results"] and result["retrieval_mode"] == "hybrid"
    assert len(fixture.requests) == 2 and fixture.requests[-1].url.path == "/rerank"
    assert bool(result["warnings"]) is (rerank_status != 200)
    assert len(fixture.consumed) == 1


async def test_missing_trusted_workflow_header_denies_all_tools(knowledge_mcp):
    fixture = knowledge_mcp
    for headers in [{}, {"x-workflow": "online-alerts-investigator"}]:
        with pytest.raises(PermissionError, match="x-task-workflow"):
            await fixture.main.list_sources(headers=headers)
        with pytest.raises(PermissionError, match="x-task-workflow"):
            await fixture.main.search_knowledge("wiki", "recovery", headers=headers)
        with pytest.raises(PermissionError, match="x-task-workflow"):
            fixture.main.get_graph_overview("code", headers=headers)
    assert fixture.requests == [] and fixture.consumed == []


async def test_async_tools_are_exposed_over_http_with_injected_identity(knowledge_mcp, background_app):
    fixture = knowledge_mcp
    server = background_app(fixture.main.app)
    transport = StreamableHttpTransport(server.base_url + "/mcp", headers=fixture.headers)
    async with Client(transport) as client:
        tools = {tool.name: tool for tool in await client.list_tools()}
        assert "search_knowledge" in tools and "list_sources" in tools
        assert "headers" not in tools["search_knowledge"].inputSchema["properties"]
        assert "untrusted evidence" in tools["search_knowledge"].description
        listed = await client.call_tool("list_sources", {})
        result = await client.call_tool("search_knowledge", {"source_alias": "wiki", "query": "recovery"})
    assert [item["alias"] for item in listed.data] == ["code", "wiki"]
    assert result.data["retrieval_mode"] == "hybrid"
    assert fixture.consumed == [fixture.headers["x-task-id"]] * 2


async def test_actual_budget_counts_each_async_call_once(knowledge_mcp, monkeypatch):
    fixture = knowledge_mcp
    monkeypatch.setattr(fixture.main, "task_call_budget", TaskCallBudget(limit=2, max_tasks=10))
    await fixture.main.list_sources(headers=fixture.headers)
    await fixture.main.search_knowledge("wiki", "recovery", headers=fixture.headers)
    with pytest.raises(PermissionError, match="budget exhausted"):
        await fixture.main.list_sources(headers=fixture.headers)
    assert len(fixture.requests) == 1


async def test_refresh_hydrates_only_live_graph_and_retains_it_on_transient_failure(knowledge_mcp, monkeypatch):
    import shared.lib.knowledge_source_serving as serving

    fixture = knowledge_mcp
    hydrated = []

    def hydrate(source, version, **kwargs):
        hydrated.append(source.canonical_alias)
        raise RuntimeError("Transient bundle failure")

    monkeypatch.setattr(serving, "hydrate_knowledge_source", hydrate)
    async with fixture.factory() as session:
        await fixture.registry.refresh(session)
    assert hydrated == ["code"]
    assert fixture.registry.has_version("code", fixture.versions["code"].id)
    assert fixture.registry.health()["degraded_sources"] == {"code": "Transient bundle failure"}


@pytest.mark.parametrize("query, limit", [("", 6), ("x" * 2001, 6), ("recovery", 0), ("recovery", 7)])
async def test_query_and_result_bounds_fail_before_embedding(knowledge_mcp, query, limit):
    fixture = knowledge_mcp
    with pytest.raises(ValueError):
        await fixture.main.search_knowledge("wiki", query, headers=fixture.headers, limit=limit)
    assert fixture.requests == []
    assert len(fixture.consumed) == 1
