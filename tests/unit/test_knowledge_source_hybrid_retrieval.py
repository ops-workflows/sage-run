import json
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from shared.lib.knowledge_source_embeddings import EmbeddingError, EmbeddingOptions
from shared.lib.knowledge_source_hybrid_retrieval import (
    HybridKnowledgeRetriever,
    HybridKnowledgeUnavailableError,
    RerankOptions,
    RetrievalOptions,
    deduplicate_candidates,
    reciprocal_rank_fusion,
    rerank_candidates,
)

pytestmark = pytest.mark.unit


def candidate(identity, page="page", ordinal=0, content=None):
    return {
        "chunk_id": identity,
        "page_id": page,
        "title": "Runbook",
        "url": "https://wiki.example/page",
        "hierarchy_path": ["Ops"],
        "heading_path": ["Recovery"],
        "ordinal": ordinal,
        "content": content or f"body {identity}",
        "lexical_text": f"Runbook Recovery body {identity}",
    }


def pinned():
    source = SimpleNamespace(id=uuid.uuid4(), canonical_alias="runbooks", source_kind="confluence")
    version = SimpleNamespace(
        id=uuid.uuid4(),
        index_config_hash="config",
        stats={
            "embedding_model": "embed",
            "embedding_dimensions": 2,
            "lexical_config": "simple",
        },
    )
    return source, version


def embeddings():
    return SimpleNamespace(
        options=EmbeddingOptions("https://model.example/v1", "embed", 2), embed=AsyncMock(return_value=[[1, 2]])
    )


class Session:
    def __init__(self, pin, dense=(), lexical=()):
        self.pin = pin
        self.dense, self.lexical = dense, lexical
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return SimpleNamespace(one_or_none=lambda: self.pin)
        sql = str(statement.compile(dialect=postgresql.dialect()))
        rows = self.dense if "MATERIALIZED" in sql else self.lexical
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


def test_rrf_merges_lanes_without_rigid_split_or_duplicates():
    results = reciprocal_rank_fusion([candidate("a"), candidate("b")], [candidate("b"), candidate("c")])
    assert [item["chunk_id"] for item in results] == ["b", "a", "c"]
    assert results[0]["scores"]["rrf"] == pytest.approx(1 / 62 + 1 / 61)


def test_adjacent_strong_overlap_deduplicates_but_distinct_pages_survive():
    first = candidate("a", ordinal=0, content="a b c d e f")
    adjacent = candidate("b", ordinal=1, content="c d e f g")
    different = candidate("c", page="other", content=first["content"])
    assert deduplicate_candidates([first, adjacent, different]) == [first, different]


async def test_search_pins_once_and_returns_six_fused_results():
    source, version = pinned()
    session = Session(
        (source, version), [candidate(str(index), page=str(index)) for index in range(8)], [candidate("7", page="7")]
    )
    authorize = AsyncMock()
    async with httpx.AsyncClient() as client:
        retriever = HybridKnowledgeRetriever(embeddings(), client, authorize)
        response = await retriever.search(session, "runbooks", "recover database")
    assert len(response["results"]) == 6
    assert response["results"][0]["page_id"] == "7"
    assert all(item["version_id"] == str(version.id) for item in response["results"])
    assert "embedding" not in json.dumps(response)
    authorize.assert_awaited_once_with("runbooks")
    assert len(session.statements) == 3
    dense_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "MATERIALIZED" in dense_sql and "<=>" in dense_sql
    assert "knowledge_source_version_documents.version_id =" in dense_sql
    assert "knowledge_chunks.index_config_hash =" in dense_sql
    lexical_sql = str(session.statements[2].compile(dialect=postgresql.dialect()))
    assert "@@" in lexical_sql and "websearch_to_tsquery" in lexical_sql and "ts_rank_cd" in lexical_sql


async def test_query_embedding_failure_uses_lexical_only():
    session = Session(pinned(), lexical=[candidate("lexical")])
    embedder = embeddings()
    embedder.embed.side_effect = EmbeddingError("failed")
    async with httpx.AsyncClient() as client:
        response = await HybridKnowledgeRetriever(embedder, client, AsyncMock()).search(session, "runbooks", "query")
    assert response["retrieval_mode"] == "lexical_fallback"
    assert response["warnings"]
    assert len(session.statements) == 2


async def test_authorization_precedes_database_and_network():
    session = Session(pinned())
    embedder = embeddings()
    async with httpx.AsyncClient() as client:
        retriever = HybridKnowledgeRetriever(embedder, client, AsyncMock(side_effect=PermissionError("denied")))
        with pytest.raises(PermissionError):
            await retriever.search(session, "runbooks", "query")
    assert session.statements == []
    embedder.embed.assert_not_awaited()


async def test_unavailable_pin_rejects_and_sql_checks_security_state():
    session = Session(None)
    async with httpx.AsyncClient() as client:
        with pytest.raises(HybridKnowledgeUnavailableError):
            await HybridKnowledgeRetriever(embeddings(), client, AsyncMock()).search(session, "runbooks", "query")
    sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    assert "serving_suspended_at IS NULL" in sql
    assert "enabled IS true" in sql
    assert "current_successful_version_id" in sql and "status =" in sql
    assert "succeeded" in session.statements[0].compile().params.values()


async def test_database_failure_is_not_disguised_as_fallback():
    session = SimpleNamespace(execute=AsyncMock(side_effect=RuntimeError("database failed")))
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="database failed"):
            await HybridKnowledgeRetriever(embeddings(), client, AsyncMock()).search(session, "runbooks", "query")


@pytest.mark.parametrize(
    "payload",
    [
        {"results": []},
        {"results": [{"index": 99, "relevance_score": 1}]},
        {"results": [{"index": 0, "relevance_score": 1}, {"index": 0, "relevance_score": 0.5}]},
        {"results": [{"index": 0, "relevance_score": "bad"}, {"index": 1, "relevance_score": 1}]},
        {"results": [{"index": False, "relevance_score": 1}, {"index": 1, "relevance_score": 1}]},
    ],
)
async def test_malformed_reranker_fails_open(payload):
    original = reciprocal_rank_fusion([candidate("a"), candidate("b")], [])
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        results, warning = await rerank_candidates(
            client, RerankOptions(True, "https://model.example", "rank"), "q", original
        )
    assert results is original
    assert warning


async def test_reranker_reorders_valid_indexed_results():
    original = reciprocal_rank_fusion([candidate("a"), candidate("b")], [])
    payload = {"results": [{"index": 0, "relevance_score": 0.1}, {"index": 1, "relevance_score": 0.9}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        results, warning = await rerank_candidates(
            client, RerankOptions(True, "https://model.example", "rank"), "q", original
        )
    assert [item["chunk_id"] for item in results] == ["b", "a"]
    assert results[0]["scores"]["rerank"] == 0.9
    assert warning is None


async def test_response_budget_includes_provenance_and_escaped_text():
    session = Session(pinned(), lexical=[candidate("large", content='"\\' * 3000)])
    embedder = embeddings()
    embedder.embed.side_effect = EmbeddingError("offline")
    async with httpx.AsyncClient() as client:
        response = await HybridKnowledgeRetriever(
            embedder,
            client,
            AsyncMock(),
            options=RetrievalOptions(max_response_chars=1500),
        ).search(session, "runbooks", "query")
    assert len(json.dumps(response, ensure_ascii=True)) <= 1500
    assert response["truncated"]
    assert response["results"][0]["content"]


@pytest.mark.parametrize("failure", [429, 503, "timeout", "bad-json"])
async def test_reranker_provider_failures_preserve_fusion_order(failure):
    original = reciprocal_rank_fusion([candidate("a"), candidate("b")], [])

    def handler(request):
        if failure == "timeout":
            raise httpx.ReadTimeout("private request detail", request=request)
        if failure == "bad-json":
            return httpx.Response(200, text="not json")
        return httpx.Response(failure, text="private request detail")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result, warning = await rerank_candidates(
            client,
            RerankOptions(True, "https://model.example", "rank"),
            "query",
            original,
        )
    assert result is original
    assert warning and "private" not in warning


async def test_disabled_reranking_never_calls_endpoint():
    client = SimpleNamespace(post=AsyncMock(side_effect=AssertionError("unexpected request")))
    original = reciprocal_rank_fusion([candidate("a")], [])
    results, warning = await rerank_candidates(client, RerankOptions(), "query", original)
    assert results is original and warning is None
    client.post.assert_not_awaited()


async def test_wrong_embedding_model_uses_pinned_lexical_index_without_embedding_call():
    source, version = pinned()
    version.stats["embedding_model"] = "old-model"
    session = Session((source, version), lexical=[candidate("lexical")])
    embedder = embeddings()
    async with httpx.AsyncClient() as client:
        result = await HybridKnowledgeRetriever(embedder, client, AsyncMock()).search(session, "runbooks", "query")
    assert result["retrieval_mode"] == "lexical_fallback"
    embedder.embed.assert_not_awaited()
