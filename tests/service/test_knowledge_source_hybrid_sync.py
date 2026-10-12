"""Real PostgreSQL worker, HTTP-client, and version-pinned retrieval contracts."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.lib import knowledge_source_indexer as indexer
from shared.lib.background_jobs import queue_background_job
from shared.lib.knowledge_source_embeddings import EmbeddingClient, EmbeddingOptions
from shared.lib.knowledge_source_hybrid_retrieval import HybridKnowledgeRetriever, HybridKnowledgeUnavailableError
from shared.lib.knowledge_source_publication import KnowledgeSourcePublication
from shared.lib.models import (
    BackgroundJobRun,
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)
from shared.lib.platform_secrets import ConfluenceConnection, load_confluence_connections

pytestmark = [pytest.mark.service, pytest.mark.asyncio]


class Provider:
    def __init__(self):
        self.pages = {
            "1": {"title": "Operations", "revision": 1, "body": "<p>Root operations guide.</p>"},
            "2": {"title": "Recovery", "revision": 1, "body": "<p>Original recovery procedure.</p>"},
        }
        self.requests = []
        self.embedded = []
        self.root_status = 200
        self.embedding_status = 200
        self.embedding_model = "test-embedding"
        self.embedding_dimensions = 3
        self.vector = [1.0, 0.5, 0.25]
        self.before_request = None

    async def handle(self, request):
        self.requests.append(request)
        if self.before_request:
            await self.before_request(request)
        if request.url.host == "embeddings.example":
            payload = json.loads(request.content)
            assert payload["model"] == self.embedding_model
            assert payload["dimensions"] == self.embedding_dimensions
            self.embedded.extend(payload["input"])
            if self.embedding_status != 200 and payload["input"] != ["knowledge embedding dimension probe"]:
                return httpx.Response(self.embedding_status)
            return httpx.Response(
                200,
                json={
                    "model": self.embedding_model,
                    "data": [{"index": index, "embedding": self.vector} for index in range(len(payload["input"]))],
                },
            )
        assert request.url.host == "wiki.example"
        assert request.headers["authorization"].startswith("Basic ")
        assert request.extensions["timeout"]["read"] == 7
        if self.root_status != 200:
            return httpx.Response(self.root_status, headers={"Retry-After": "0"})
        if request.url.path.endswith("/descendants"):
            return httpx.Response(
                200, json={"results": [{"id": page_id, "type": "page"} for page_id in self.pages if page_id != "1"]}
            )
        page_id = request.url.path.rsplit("/", 1)[-1]
        page = self.pages.get(page_id)
        if page is None:
            return httpx.Response(404)
        payload = {
            "id": page_id,
            "title": page["title"],
            "version": {"number": page["revision"]},
            "status": "current",
            "_links": {"webui": f"/pages/{page_id}"},
        }
        if page_id != "1":
            payload["parentId"] = "1"
        if request.url.params.get("body-format"):
            payload["body"] = {"storage": {"value": page["body"]}}
        return httpx.Response(200, json=payload)

    def change_page(self):
        self.pages["2"] = {"title": "Recovery", "revision": 2, "body": "<p>Updated recovery runbook.</p>"}

    def clear_requests(self):
        self.requests.clear()
        self.embedded.clear()

    @property
    def body_ids(self):
        return [
            request.url.path.rsplit("/", 1)[-1] for request in self.requests if request.url.params.get("body-format")
        ]

    @property
    def document_embeddings(self):
        return [value for value in self.embedded if value != "knowledge embedding dimension probe"]


@pytest.fixture
def provider(monkeypatch, tmp_path):
    provider = Provider()
    connection = ConfluenceConnection("wiki", "https://wiki.example/wiki", "worker@example.com", "dummy-token")
    monkeypatch.setattr(indexer, "load_confluence_connections", lambda *args, **kwargs: {"wiki": connection})
    monkeypatch.setattr(
        indexer.httpx, "AsyncClient", lambda: AsyncClient(transport=httpx.MockTransport(provider.handle))
    )
    for name, value in {
        "knowledge_embeddings_openai_base_url": "https://embeddings.example/v1",
        "knowledge_embeddings_openai_model": "test-embedding",
        "knowledge_embeddings_dimensions": 3,
        "knowledge_embeddings_batch_size": 1,
        "knowledge_source_max_pages": 10,
        "knowledge_source_max_chunks": 20,
        "knowledge_source_fetch_concurrency": 2,
        "knowledge_source_request_timeout_sec": 7,
        "knowledge_source_request_retries": 0,
    }.items():
        monkeypatch.setattr(indexer.settings, name, value)
    clock = itertools.count(step=11)
    monkeypatch.setattr(indexer, "time", SimpleNamespace(monotonic=clock.__next__))
    provider.config = indexer.KnowledgeSourceIndexerConfig(cache_root=tmp_path, object_store_bucket="")
    return provider


async def create_source(engine, *, alias="confluence/operations", credential_ref="wiki"):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        source = KnowledgeSource(
            canonical_alias=alias,
            source_kind="confluence",
            index_kind="hybrid_vector",
            source_config={"root_page_ids": ["1"], "include_descendants": True, "lexical_config": "simple"},
            credential_ref=credential_ref,
        )
        session.add(source)
        await session.commit()
        return source.id


async def sync(engine, provider, source_id, *, queued_run_id=None):
    return await indexer.run_knowledge_source_sync(
        engine, source_id=source_id, trigger="manual", config=provider.config, queued_run_id=queued_run_id
    )


async def records(engine, source_id):
    async with AsyncSession(engine) as session:
        source = await session.get(KnowledgeSource, source_id)
        versions = list(
            (await session.scalars(select(KnowledgeSourceVersion).order_by(KnowledgeSourceVersion.created_at))).all()
        )
        runs = list((await session.scalars(select(BackgroundJobRun).order_by(BackgroundJobRun.started_at))).all())
        members = list((await session.scalars(select(KnowledgeSourceVersionDocument))).all())
        return source, versions, runs, members


async def page_chunks(engine, version_id, page_id="2"):
    async with AsyncSession(engine) as session:
        return list(
            (
                await session.scalars(
                    select(KnowledgeChunk)
                    .join(
                        KnowledgeSourceVersionDocument,
                        KnowledgeSourceVersionDocument.document_revision_id == KnowledgeChunk.document_revision_id,
                    )
                    .where(
                        KnowledgeSourceVersionDocument.version_id == version_id,
                        KnowledgeSourceVersionDocument.external_id == page_id,
                    )
                    .order_by(KnowledgeChunk.ordinal)
                )
            ).all()
        )


async def retrieve(engine, provider):
    async def authorize(alias):
        assert alias == "confluence/operations"

    async with AsyncSession(engine) as session, AsyncClient(transport=httpx.MockTransport(provider.handle)) as client:
        embeddings = EmbeddingClient(EmbeddingOptions.from_settings(indexer.settings), client)
        retriever = HybridKnowledgeRetriever(embeddings, client, authorize)
        return await retriever.search(session, "confluence/operations", "recovery")


async def assert_failed_preserves_pointer(engine, source_id, previous):
    source, versions, runs, members = await records(engine, source_id)
    assert source.current_successful_version_id == previous.version_id
    assert runs[-1].status == "failed"
    assert runs[-1].finished_at is not None and runs[-1].duration_sec >= 0
    failed = [version for version in versions if version.status == "failed"]
    assert all(member.version_id not in {version.id for version in failed} for member in members)
    return source, versions, runs


async def test_scrub_rule_changes_refetch_and_reuse_chunks_including_reverted_rules(async_engine, provider):
    source_id = await create_source(async_engine)
    initial = await sync(async_engine, provider, source_id)
    assert initial.status == "succeeded"
    for patterns, expected in [(["Original"], 1), (["never-matches"], 0), (["Original"], 0)]:
        async with AsyncSession(async_engine) as session:
            source = await session.get(KnowledgeSource, source_id)
            source.source_config = {**source.source_config, "scrub_patterns": patterns}
            await session.commit()
        provider.clear_requests()
        outcome = await sync(async_engine, provider, source_id)
        assert outcome.status in {"succeeded", "skipped"}
        assert sorted(provider.body_ids) == ["1", "2"]
        assert len(provider.document_embeddings) == expected
        chunks = await page_chunks(async_engine, outcome.version_id)
        assert all(("Original" not in chunk.content) is (patterns == ["Original"]) for chunk in chunks)
        if patterns == ["Original"]:
            assert all("Original" not in value for value in provider.document_embeddings)
            async with AsyncSession(async_engine) as session:
                revisions = (
                    await session.scalars(
                        select(KnowledgeDocumentRevision)
                        .join(
                            KnowledgeSourceVersionDocument,
                            KnowledgeSourceVersionDocument.document_revision_id == KnowledgeDocumentRevision.id,
                        )
                        .where(KnowledgeSourceVersionDocument.version_id == outcome.version_id)
                    )
                ).all()
                assert all("Original" not in repr(revision.document_metadata) for revision in revisions)
        provider.clear_requests()
        unchanged = await sync(async_engine, provider, source_id)
        assert unchanged.status == "skipped"
        assert provider.body_ids == []


async def test_exact_pages_sync_does_not_fetch_or_index_descendants(async_engine, provider):
    source_id = await create_source(async_engine)
    async with AsyncSession(async_engine) as session:
        source = await session.get(KnowledgeSource, source_id)
        source.source_config = {**source.source_config, "include_descendants": False}
        await session.commit()
    outcome = await sync(async_engine, provider, source_id)
    assert outcome.status == "succeeded"
    assert provider.body_ids == ["1"]
    assert not any(request.url.path.endswith("/descendants") for request in provider.requests)
    _, _, _, members = await records(async_engine, source_id)
    assert {member.external_id for member in members} == {"1"}


async def test_scrub_timeout_preserves_old_serving_pointer(async_engine, provider, monkeypatch):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    async with AsyncSession(async_engine) as session:
        source = await session.get(KnowledgeSource, source_id)
        source.source_config = {**source.source_config, "scrub_patterns": ["(a+)+$"]}
        await session.commit()
    provider.pages["1"]["body"] = "<p>" + "a" * 10000 + "!</p>"
    monkeypatch.setattr("shared.lib.knowledge_source_scrubbing.SCRUB_TIMEOUT_SEC", 0.001)
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="execution budget"):
        await sync(async_engine, provider, source_id)
    source, _, _ = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is None


async def test_sync_sequence_and_version_pinned_retrieval(async_engine, provider):
    source_id = await create_source(async_engine)
    async with AsyncSession(async_engine) as session:
        queued = await queue_background_job(
            session, job_type=indexer.KNOWLEDGE_SOURCE_SYNC_JOB_TYPE, knowledge_source_id=source_id, trigger="manual"
        )
        queued_id = queued.id
    first = await sync(async_engine, provider, source_id, queued_run_id=queued_id)
    assert first.status == "succeeded" and first.run_id == queued_id
    assert first.source_revision == first.commit_sha
    assert sorted(provider.body_ids) == ["1", "2"]
    assert len(provider.document_embeddings) == 2
    source, versions, runs, members = await records(async_engine, source_id)
    assert source.current_successful_version_id == first.version_id
    assert versions[0].index_kind == "hybrid_vector" and versions[0].indexer_version
    assert versions[0].stats["document_count"] == 2
    assert versions[0].stats["embedding_dimensions"] == 3
    assert runs[-1].status == "succeeded" and len(members) == 2
    response = await retrieve(async_engine, provider)
    assert response["version_id"] == str(first.version_id)
    assert response["retrieval_mode"] == "hybrid"
    assert {item["page_id"] for item in response["results"]} == {"1", "2"}
    assert any(item["scores"]["lexical_rank"] for item in response["results"])

    provider.clear_requests()
    unchanged = await sync(async_engine, provider, source_id)
    assert unchanged.status == "skipped" and unchanged.version_id == first.version_id
    assert provider.body_ids == [] and provider.document_embeddings == []
    assert provider.embedded == ["knowledge embedding dimension probe"]
    _, versions, runs, members = await records(async_engine, source_id)
    assert len(versions) == 1 and len(members) == 2
    assert runs[-1].knowledge_source_version_id == first.version_id

    provider.change_page()
    provider.clear_requests()
    changed = await sync(async_engine, provider, source_id)
    assert changed.status == "succeeded" and changed.version_id != first.version_id
    assert provider.body_ids == ["2"] and len(provider.document_embeddings) == 1
    response = await retrieve(async_engine, provider)
    assert response["version_id"] == str(changed.version_id)
    assert any("Updated recovery" in item["content"] for item in response["results"])
    assert all("Original recovery" not in item["content"] for item in response["results"])

    del provider.pages["2"]
    provider.clear_requests()
    deleted = await sync(async_engine, provider, source_id)
    assert deleted.status == "succeeded"
    assert provider.body_ids == [] and provider.document_embeddings == []
    response = await retrieve(async_engine, provider)
    assert response["version_id"] == str(deleted.version_id)
    assert {item["page_id"] for item in response["results"]} == {"1"}
    _, versions, _, members = await records(async_engine, source_id)
    assert len(versions) == 3 and len(members) == 5
    assert versions[-1].stats["removed_pages"] == 1


async def test_changed_page_reuses_stable_chunks_in_new_immutable_revision(async_engine, provider):
    provider.pages["2"]["body"] = "<p>" + "Stable recovery instruction. " * 200 + "Original ending.</p>"
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original_chunks = await page_chunks(async_engine, first.version_id)
    assert len(original_chunks) >= 3
    assert len(provider.pages["2"]["body"]) > 2400
    assert len(provider.document_embeddings) == len(original_chunks) + 1
    original_state = [
        (chunk.id, chunk.document_revision_id, chunk.content, chunk.lexical_text, list(chunk.embedding))
        for chunk in original_chunks
    ]

    provider.pages["2"]["revision"] += 1
    provider.pages["2"]["body"] = provider.pages["2"]["body"].replace("Original ending.", "Modified ending.")
    provider.clear_requests()
    changed = await sync(async_engine, provider, source_id)
    assert changed.status == "succeeded" and changed.version_id != first.version_id
    changed_chunks = await page_chunks(async_engine, changed.version_id)
    assert len(changed_chunks) == len(original_chunks)
    assert provider.body_ids == ["2"]
    assert provider.document_embeddings == [changed_chunks[-1].lexical_text]
    assert original_chunks[-1].lexical_text != changed_chunks[-1].lexical_text
    assert not {chunk.id for chunk in original_chunks} & {chunk.id for chunk in changed_chunks}
    assert original_chunks[0].document_revision_id != changed_chunks[0].document_revision_id
    for original, cloned in zip(original_chunks[:-1], changed_chunks[:-1], strict=True):
        assert original.content_hash == cloned.content_hash
        assert original.content == cloned.content and original.lexical_text == cloned.lexical_text
        assert original.heading_path == cloned.heading_path and original.estimated_tokens == cloned.estimated_tokens
        assert list(cloned.embedding) == list(original.embedding)
    stored_originals = await page_chunks(async_engine, first.version_id)
    assert [
        (chunk.id, chunk.document_revision_id, chunk.content, chunk.lexical_text, list(chunk.embedding))
        for chunk in stored_originals
    ] == original_state
    source, versions, runs, members = await records(async_engine, source_id)
    assert source.current_successful_version_id == changed.version_id
    assert runs[-1].status == "succeeded"
    assert {member.external_id for member in members if member.version_id == changed.version_id} == {"1", "2"}
    assert {
        member.document_revision_id
        for member in members
        if member.version_id == changed.version_id and member.external_id == "2"
    } == {changed_chunks[0].document_revision_id}
    stats = next(version.stats for version in versions if version.id == changed.version_id)
    assert stats["chunks_embedded"] == len(provider.document_embeddings) == 1
    assert stats["chunks_reused"] == len(original_chunks)
    assert stats["chunk_count"] == stats["chunks_embedded"] + stats["chunks_reused"] == len(changed_chunks) + 1
    assert stats["embedding_requests"] == 2
    assert stats["embedding_input_characters"] == sum(map(len, provider.embedded))


@pytest.mark.parametrize("change", ["title", "heading"])
async def test_changed_title_or_heading_never_reuses_old_embedding_inputs(async_engine, provider, change):
    provider.pages["2"]["body"] = "<h1>Original heading</h1><p>" + "Stable recovery instruction. " * 200 + "</p>"
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original_chunks = await page_chunks(async_engine, first.version_id)
    if change == "title":
        provider.pages["2"]["title"] = "Renamed recovery"
    else:
        provider.pages["2"]["body"] = provider.pages["2"]["body"].replace("Original heading", "Modified heading")
    provider.pages["2"]["revision"] += 1
    provider.clear_requests()
    changed = await sync(async_engine, provider, source_id)
    chunks = await page_chunks(async_engine, changed.version_id)
    assert provider.document_embeddings == [chunk.lexical_text for chunk in chunks]
    assert {chunk.content for chunk in original_chunks} & {chunk.content for chunk in chunks}
    assert not {chunk.lexical_text for chunk in original_chunks} & {chunk.lexical_text for chunk in chunks}
    _, versions, _, _ = await records(async_engine, source_id)
    stats = next(version.stats for version in versions if version.id == changed.version_id)
    assert stats["chunks_embedded"] == len(chunks)
    assert stats["chunks_reused"] == 1
    assert stats["chunk_count"] == len(chunks) + 1


@pytest.mark.parametrize("boundary", ["source", "page"])
async def test_matching_chunk_inputs_never_cross_source_or_page_boundary(async_engine, provider, monkeypatch, boundary):
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original_chunks = await page_chunks(async_engine, first.version_id)
    if boundary == "source":
        connections = indexer.load_confluence_connections()
        connections["isolated"] = ConfluenceConnection(
            "isolated", "https://wiki.example/wiki", "other@example.com", "other-token"
        )
        monkeypatch.setattr(indexer, "load_confluence_connections", lambda *args, **kwargs: connections)
        target_source_id = await create_source(async_engine, alias="confluence/isolated", credential_ref="isolated")
        target_page_id = "2"
    else:
        provider.pages["3"] = dict(provider.pages["2"])
        target_source_id = source_id
        target_page_id = "3"
    provider.clear_requests()
    changed = await sync(async_engine, provider, target_source_id)
    chunks = await page_chunks(async_engine, changed.version_id, target_page_id)
    assert [chunk.lexical_text for chunk in chunks] == [chunk.lexical_text for chunk in original_chunks]
    assert all(chunk.lexical_text in provider.document_embeddings for chunk in chunks)
    _, versions, _, _ = await records(async_engine, target_source_id)
    stats = next(version.stats for version in versions if version.id == changed.version_id)
    assert stats["chunks_embedded"] == len(provider.document_embeddings) == (2 if boundary == "source" else 1)
    assert stats["chunks_reused"] == (0 if boundary == "source" else 2)
    assert stats["chunk_count"] == stats["chunks_embedded"] + stats["chunks_reused"]


@pytest.mark.parametrize("contract", ["model", "dimensions"])
async def test_changed_page_reembeds_all_chunks_when_embedding_config_changes(
    async_engine, provider, monkeypatch, contract
):
    provider.pages["2"]["body"] = "<p>" + "Stable recovery instruction. " * 200 + "Original ending.</p>"
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original_chunks = await page_chunks(async_engine, first.version_id)
    provider.pages["2"]["revision"] += 1
    provider.pages["2"]["body"] = provider.pages["2"]["body"].replace("Original ending.", "Modified ending.")
    if contract == "model":
        provider.embedding_model = "new-embedding"
        monkeypatch.setattr(indexer.settings, "knowledge_embeddings_openai_model", provider.embedding_model)
    else:
        provider.embedding_dimensions = 4
        provider.vector = [1.0, 0.5, 0.25, 0.125]
        monkeypatch.setattr(indexer.settings, "knowledge_embeddings_dimensions", provider.embedding_dimensions)
    provider.clear_requests()
    changed = await sync(async_engine, provider, source_id)
    chunks = await page_chunks(async_engine, changed.version_id)
    assert chunks[0].lexical_text == original_chunks[0].lexical_text
    assert chunks[0].index_config_hash != original_chunks[0].index_config_hash
    assert all(chunk.lexical_text in provider.document_embeddings for chunk in chunks)
    assert all(chunk.embedding_model == provider.embedding_model for chunk in chunks)
    assert all(chunk.embedding_dimensions == provider.embedding_dimensions for chunk in chunks)
    _, versions, _, _ = await records(async_engine, source_id)
    stats = next(version.stats for version in versions if version.id == changed.version_id)
    assert stats["chunks_embedded"] == stats["chunk_count"] == len(provider.document_embeddings) == len(chunks) + 1
    assert stats["chunks_reused"] == 0


@pytest.mark.parametrize("tied_timestamps", [False, True], ids=["newest", "timestamp-tie"])
async def test_cached_vector_selection_is_deterministic_by_revision(async_engine, provider, tied_timestamps):
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original = (await page_chunks(async_engine, first.version_id))[0]
    provider.pages["1"]["title"] = "Renamed operations"
    provider.pages["1"]["revision"] += 1
    second = await sync(async_engine, provider, source_id)
    newer = (await page_chunks(async_engine, second.version_id))[0]
    assert newer.document_revision_id != original.document_revision_id
    original_vector, newer_vector = [3.0, 2.0, 1.0], [6.0, 4.0, 2.0]
    async with AsyncSession(async_engine) as session:
        for chunk, year, vector in [
            (original, 2020, original_vector),
            (newer, 2020 if tied_timestamps else 2021, newer_vector),
        ]:
            await session.execute(
                update(KnowledgeDocumentRevision)
                .where(KnowledgeDocumentRevision.id == chunk.document_revision_id)
                .values(created_at=datetime(year, 1, 1, tzinfo=UTC))
            )
            await session.execute(update(KnowledgeChunk).where(KnowledgeChunk.id == chunk.id).values(embedding=vector))
        await session.commit()
    provider.pages["1"]["title"] = "Latest operations"
    provider.pages["1"]["revision"] += 1
    provider.clear_requests()
    third = await sync(async_engine, provider, source_id)
    cloned = (await page_chunks(async_engine, third.version_id))[0]
    expected = (
        newer_vector
        if not tied_timestamps or newer.document_revision_id > original.document_revision_id
        else original_vector
    )
    assert list(cloned.embedding) == expected
    assert cloned.lexical_text == newer.lexical_text == original.lexical_text
    assert cloned.lexical_text not in provider.document_embeddings
    _, versions, _, _ = await records(async_engine, source_id)
    stats = next(version.stats for version in versions if version.id == third.version_id)
    assert stats["chunks_embedded"] == len(provider.document_embeddings) == 1
    assert stats["chunks_reused"] == 1


async def test_embedding_failure_preserves_pointer_and_retry_reuses_staging(async_engine, provider):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    provider.pages["1"]["revision"] = 2
    provider.pages["1"]["body"] = "<p>New root operations text.</p>"
    provider.change_page()

    async def fail_second_document(request):
        if request.url.host == "embeddings.example" and "Updated recovery" in request.content.decode():
            provider.embedding_status = 503
        async with AsyncSession(async_engine) as session:
            pointer = await session.scalar(select(KnowledgeSource.current_successful_version_id))
            assert pointer == previous.version_id

    provider.before_request = fail_second_document
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="HTTP 503"):
        await sync(async_engine, provider, source_id)
    source, _, _ = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is None
    async with AsyncSession(async_engine) as session:
        assert await session.scalar(select(func.count()).select_from(KnowledgeDocumentRevision)) > 2
        assert await session.scalar(select(func.count()).select_from(KnowledgeChunk)) > 2
    provider.before_request = None
    provider.embedding_status = 200
    provider.clear_requests()
    retried = await sync(async_engine, provider, source_id)
    assert retried.status == "succeeded" and len(provider.document_embeddings) == 1


@pytest.mark.parametrize("status", [401, 403, 404])
async def test_root_revocation_suspends_and_validated_skip_restores(async_engine, provider, status):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    provider.root_status = status
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="revoked"):
        await sync(async_engine, provider, source_id)
    source, _, _ = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is not None
    assert "revoked" in source.serving_suspension_reason
    with pytest.raises(HybridKnowledgeUnavailableError):
        await retrieve(async_engine, provider)
    provider.root_status = 200
    provider.clear_requests()
    restored = await sync(async_engine, provider, source_id)
    assert restored.status == "skipped" and restored.version_id == previous.version_id
    assert provider.body_ids == [] and provider.document_embeddings == []
    source, _, _, _ = await records(async_engine, source_id)
    assert source.serving_suspended_at is None and source.serving_suspension_reason is None
    assert (await retrieve(async_engine, provider))["version_id"] == str(previous.version_id)


@pytest.mark.parametrize("status", [429, 503])
async def test_provider_availability_failure_keeps_serving(async_engine, provider, status):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    provider.root_status = status
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="unavailable"):
        await sync(async_engine, provider, source_id)
    source, _, _ = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is None
    assert (await retrieve(async_engine, provider))["version_id"] == str(previous.version_id)


@pytest.mark.parametrize(
    "failure", ["missing_connection", "missing_secret", "dimensions", "zero", "nonfinite", "mismatch"]
)
async def test_configuration_and_vector_failures_preserve_previous(
    async_engine, provider, monkeypatch, tmp_path, failure
):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    if failure in {"missing_connection", "missing_secret"}:
        platform_file = tmp_path / "platform.yaml"
        platform_file.write_text(
            "confluence:\n  connections:\n    wiki:\n      base_url: https://wiki.example/wiki\n"
            "      username: worker@example.com\n      token_secret: absent\n"
            if failure == "missing_secret"
            else "confluence: {}\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(indexer.settings, "platform_config_file", str(platform_file))
        monkeypatch.setattr(indexer.settings, "age_identity", "dummy-identity")
        monkeypatch.setattr(indexer, "load_confluence_connections", load_confluence_connections)
    elif failure == "dimensions":
        monkeypatch.setattr(indexer.settings, "knowledge_embeddings_dimensions", 0)
    else:
        provider.vector = {"zero": [0, 0, 0], "nonfinite": [1e40, 0, 0], "mismatch": [1, 0]}[failure]
        if failure == "nonfinite":
            provider.vector = [float("inf"), 0, 0]

            async def nonfinite_response(request):
                return httpx.Response(200, content=b'{"data":[{"index":0,"embedding":[Infinity,0,0]}]}')

            monkeypatch.setattr(
                indexer.httpx, "AsyncClient", lambda: AsyncClient(transport=httpx.MockTransport(nonfinite_response))
            )
    provider.clear_requests()
    with pytest.raises(indexer.KnowledgeSourceSyncError):
        await sync(async_engine, provider, source_id)
    source, _, runs = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is None
    if failure in {"missing_connection", "missing_secret", "dimensions"}:
        assert provider.requests == [] and runs[-1].summary["failure_phase"] == "configure"


@pytest.mark.parametrize("edit", ["disable", "config", "credential", "kind", "timestamp"])
@pytest.mark.parametrize("changed", [True, False], ids=["changed", "unchanged"])
async def test_source_edit_during_build_never_resurrects_source(async_engine, provider, edit, changed):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    if changed:
        provider.change_page()
    edited = False
    values = {
        "disable": {"enabled": False},
        "config": {"source_config": {"root_page_ids": ["99"]}, "current_successful_version_id": None},
        "credential": {"credential_ref": "replacement", "current_successful_version_id": None},
        "kind": {"source_kind": "github", "index_kind": "code_graph", "current_successful_version_id": None},
        "timestamp": {"updated_at": datetime.now(UTC)},
    }[edit]

    async def edit_source(request):
        nonlocal edited
        if not edited and request.url.host == "wiki.example":
            edited = True
            async with AsyncSession(async_engine) as session:
                await session.execute(update(KnowledgeSource).where(KnowledgeSource.id == source_id).values(**values))
                await session.commit()

    provider.before_request = edit_source
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="disabled or edited"):
        await sync(async_engine, provider, source_id)
    source, versions, runs, members = await records(async_engine, source_id)
    assert edited and runs[-1].status == "failed"
    assert source.current_successful_version_id == values.get("current_successful_version_id", previous.version_id)
    assert all(getattr(source, key) == value for key, value in values.items())
    assert len([version for version in versions if version.status == "succeeded"]) == 1
    assert {member.version_id for member in members} == {previous.version_id}


async def test_failed_restoration_does_not_clear_suspension(async_engine, provider, monkeypatch):
    source_id = await create_source(async_engine)
    previous = await sync(async_engine, provider, source_id)
    provider.root_status = 401
    with pytest.raises(indexer.KnowledgeSourceSyncError):
        await sync(async_engine, provider, source_id)
    provider.root_status = 200
    monkeypatch.setattr(indexer, "load_confluence_connections", lambda *args, **kwargs: {})
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="missing"):
        await sync(async_engine, provider, source_id)
    source, _, _ = await assert_failed_preserves_pointer(async_engine, source_id, previous)
    assert source.serving_suspended_at is not None
    assert "revoked" in source.serving_suspension_reason


async def test_stale_security_failure_does_not_suspend_edited_credentials(async_engine, provider):
    source_id = await create_source(async_engine)
    await sync(async_engine, provider, source_id)
    provider.root_status = 401

    async def replace_credentials(request):
        if request.url.host == "wiki.example":
            async with AsyncSession(async_engine) as session:
                await session.execute(
                    update(KnowledgeSource)
                    .where(KnowledgeSource.id == source_id)
                    .values(credential_ref="replacement", current_successful_version_id=None)
                )
                await session.commit()

    provider.before_request = replace_credentials
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="revoked"):
        await sync(async_engine, provider, source_id)
    source, _, runs, _ = await records(async_engine, source_id)
    assert source.credential_ref == "replacement" and source.current_successful_version_id is None
    assert source.serving_suspended_at is None and runs[-1].status == "failed"


async def test_hybrid_sync_does_not_require_graph_cache_directory(async_engine, provider, tmp_path):
    unavailable_cache = tmp_path / "not-a-directory"
    unavailable_cache.write_text("occupied", encoding="utf-8")
    provider.config = indexer.KnowledgeSourceIndexerConfig(unavailable_cache, "")
    source_id = await create_source(async_engine)
    assert (await sync(async_engine, provider, source_id)).status == "succeeded"


async def test_graph_job_requires_bucket_after_claim(async_engine, provider):
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        source = KnowledgeSource(
            canonical_alias="org/repo", repository_url="https://github.example/org/repo", default_ref="main"
        )
        session.add(source)
        await session.commit()
        source_id = source.id
    with pytest.raises(indexer.KnowledgeSourceSyncError, match="OBJECT_STORE_BUCKET"):
        await sync(async_engine, provider, source_id)
    source, versions, runs, _ = await records(async_engine, source_id)
    assert source.current_successful_version_id is None and versions == []
    assert len(runs) == 1 and runs[0].status == "failed"
    assert provider.requests == []


async def test_failed_historical_identity_can_be_rebuilt(async_engine, provider):
    source_id = await create_source(async_engine)
    original = dict(provider.pages["2"])
    first = await sync(async_engine, provider, source_id)
    provider.change_page()
    second = await sync(async_engine, provider, source_id)
    async with AsyncSession(async_engine) as session:
        version = await session.get(KnowledgeSourceVersion, first.version_id)
        version.status = "failed"
        version.error = "Previously interrupted promotion"
        await session.commit()
    provider.pages["2"] = original
    restored = await sync(async_engine, provider, source_id)
    assert restored.status == "succeeded" and restored.version_id == first.version_id
    assert restored.version_id != second.version_id
    source, versions, runs, members = await records(async_engine, source_id)
    assert source.current_successful_version_id == first.version_id
    assert len(versions) == 2 and len(members) == 4
    assert all(version.status == "succeeded" and version.error is None for version in versions)
    assert runs[-1].knowledge_source_version_id == first.version_id


async def test_historical_revision_is_deduplicated(async_engine, provider):
    source_id = await create_source(async_engine)
    first = await sync(async_engine, provider, source_id)
    original = dict(provider.pages["2"])
    provider.change_page()
    second = await sync(async_engine, provider, source_id)
    assert second.version_id != first.version_id
    provider.pages["2"] = original
    restored = await sync(async_engine, provider, source_id)
    assert restored.status == "skipped" and restored.version_id == first.version_id
    source, versions, runs, members = await records(async_engine, source_id)
    assert source.current_successful_version_id == first.version_id
    assert len(versions) == 2 and len(members) == 4
    assert runs[-1].knowledge_source_version_id == first.version_id
    assert any("Original recovery" in item["content"] for item in (await retrieve(async_engine, provider))["results"])


async def test_session_owned_advisory_lock_blocks_hybrid_job_claim(async_engine, provider):
    source_id = await create_source(async_engine)
    lock_key = int.from_bytes(source_id.bytes[:8], byteorder="big", signed=True)
    async with async_engine.connect() as connection:
        await connection.execute(text("SELECT pg_advisory_lock(:key)"), {"key": lock_key})
        await connection.commit()
        try:
            with pytest.raises(indexer.KnowledgeSourceBusyError):
                await sync(async_engine, provider, source_id)
        finally:
            await connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
            await connection.commit()
    assert provider.requests == []
    _, _, runs, _ = await records(async_engine, source_id)
    assert runs == []


async def test_graph_success_populates_generic_version_fields(async_engine, provider, monkeypatch, tmp_path):
    async with AsyncSession(async_engine, expire_on_commit=False) as session:
        source = KnowledgeSource(
            canonical_alias="org/repo", repository_url="https://github.example/org/repo", default_ref="main"
        )
        session.add(source)
        await session.commit()
        source_id = source.id
    monkeypatch.setattr(indexer, "prepare_repository_snapshot", lambda *args: (tmp_path, "a" * 40))
    monkeypatch.setattr(
        indexer, "run_graphify_code_extraction", lambda *args, **kwargs: SimpleNamespace(stdout="", stderr="")
    )
    monkeypatch.setattr(
        indexer,
        "build_knowledge_source_bundle",
        lambda **kwargs: SimpleNamespace(file_count=2, node_count=3, edge_count=4),
    )
    monkeypatch.setattr(
        indexer, "publish_knowledge_source_bundle", lambda *args, **kwargs: KnowledgeSourcePublication("bucket", {}, {})
    )
    config = indexer.KnowledgeSourceIndexerConfig(tmp_path, "bucket")
    result = await indexer.run_knowledge_source_sync(async_engine, source_id=source_id, trigger="manual", config=config)
    _, versions, _, _ = await records(async_engine, source_id)
    version = versions[0]
    assert version.source_revision == version.commit_sha == result.source_revision
    assert version.indexer_version == version.graphify_version
    assert version.index_config_hash == version.extraction_config_hash
    assert version.index_kind == "code_graph"
    assert version.stats == {"file_count": 2, "node_count": 3, "edge_count": 4}
