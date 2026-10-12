import uuid
from collections import deque
from dataclasses import asdict, replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy.dialects import postgresql

from shared.lib.knowledge_source_confluence import (
    NORMALIZER_VERSION,
    ConfluenceError,
    ConfluenceLimitError,
    PageMetadata,
    SourceSnapshot,
    chunk_document,
    document_hash,
    normalize_storage,
    stable_hash,
)
from shared.lib.knowledge_source_embeddings import EmbeddingError, EmbeddingOptions
from shared.lib.knowledge_source_hybrid_index import (
    HybridIndexOptions,
    build_hybrid_index,
    index_config_hash,
)
from shared.lib.models import KnowledgeChunk, KnowledgeDocumentRevision, KnowledgeSourceVersionDocument

pytestmark = pytest.mark.unit


class Session:
    def __init__(self, scalar_results=(), row_results=(), previous=None, reusable_chunks=()):
        self.scalar_results = deque(scalar_results)
        self.row_results = deque(row_results)
        self.previous = previous
        self.reusable_chunks = reusable_chunks
        self.reuse_queries = []
        self.added = []
        self.flush = AsyncMock()
        self.commit = AsyncMock()

    async def scalar(self, statement):
        return self.scalar_results.popleft()

    async def scalars(self, statement):
        if statement.column_descriptions[0]["entity"].__name__ == "KnowledgeChunk" and "JOIN" in str(
            statement.compile(dialect=postgresql.dialect())
        ):
            self.reuse_queries.append(statement)
            values = self.reusable_chunks
        else:
            values = self.row_results.popleft()
        return SimpleNamespace(all=lambda: values)

    async def get(self, model, identifier):
        return self.previous

    def add(self, value):
        self.added.append(value)


def inputs():
    source_id = uuid.uuid4()
    source = SimpleNamespace(
        id=source_id,
        source_kind="confluence",
        index_kind="hybrid_vector",
        source_config={"root_page_ids": ["1"]},
        current_successful_version_id=None,
    )
    version = SimpleNamespace(id=uuid.uuid4(), source_id=source_id, status="pending")
    page = PageMetadata("1", "2", "Root", "https://wiki.example/wiki/pages/1", (), "1")
    provider = SimpleNamespace(
        request_count=0,
        discover=AsyncMock(return_value=SourceSnapshot((page,), ())),
        fetch_body=AsyncMock(return_value="<h1>Heading</h1><p>body</p>"),
    )
    embeddings = SimpleNamespace(
        options=EmbeddingOptions("https://model.example/v1", "embed", 2),
        probe=AsyncMock(),
        embed=AsyncMock(side_effect=lambda texts: [[1.0, 2.0] for text in texts]),
        request_count=0,
        input_characters=0,
    )
    return source, version, page, provider, embeddings


async def test_build_inserts_complete_membership_without_committing_or_promoting():
    source, version, page, provider, embeddings = inputs()
    session = Session(["simple", None], [[], []])
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert build.stats["document_count"] == 1
    assert build.stats["chunks_embedded"] > 0
    assert len([item for item in session.added if isinstance(item, KnowledgeSourceVersionDocument)]) == 1
    assert source.current_successful_version_id is None
    assert version.status == "pending"
    session.commit.assert_not_awaited()
    embeddings.probe.assert_awaited_once()


def cached_inputs():
    source, version, page, provider, embeddings = inputs()
    options = HybridIndexOptions()
    body = "<h1>Heading</h1><p>body</p><pre>code()</pre>"
    normalized = normalize_storage(body)
    provider.fetch_body.return_value = body
    document = KnowledgeDocumentRevision(
        id=uuid.uuid4(),
        source_id=source.id,
        external_id="1",
        provider_revision="1",
        title=page.title,
        canonical_url=page.canonical_url,
        hierarchy_path=[],
        normalized_content=normalized.content,
        content_hash=document_hash(page, normalized),
        document_metadata={
            "normalizer_version": NORMALIZER_VERSION,
            "blocks": [asdict(block) for block in normalized.blocks],
        },
    )
    chunks = [
        KnowledgeChunk(
            id=uuid.uuid4(),
            document_revision_id=document.id,
            ordinal=chunk.ordinal,
            index_config_hash=index_config_hash(options, embeddings),
            content=chunk.content,
            lexical_text=chunk.lexical_text,
            content_hash=chunk.content_hash,
            heading_path=list(chunk.heading_path),
            embedding=[1, 2],
            estimated_tokens=chunk.estimated_tokens,
            embedding_model="embed",
            embedding_dimensions=2,
        )
        for chunk in chunk_document(normalized, page.title)
    ]
    previous = SimpleNamespace(
        id=uuid.uuid4(),
        source_id=source.id,
        status="succeeded",
        stats={"provider_revisions": {"1": "2"}, "scrub_signature": stable_hash([])},
        source_revision="old",
        index_config_hash=index_config_hash(options, embeddings),
    )
    source.current_successful_version_id = previous.id
    return source, version, page, provider, embeddings, document, chunks, previous


async def test_metadata_unchanged_reuses_document_body_and_chunks():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    session = Session(["simple"], [[document], chunks, []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert build.stats["reused_pages"] == 1
    assert build.stats["chunks_reused"] == len(chunks)
    provider.discover.assert_awaited_once()
    provider.fetch_body.assert_not_awaited()
    embeddings.embed.assert_not_awaited()
    assert len(session.added) == 1
    assert session.reuse_queries == []


async def test_rule_change_refetches_unchanged_page_and_reuses_unchanged_chunks():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    source.source_config["scrub_patterns"] = ["body"]
    session = Session(["simple", None], [[document], [], []], previous, reusable_chunks=chunks)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    provider.fetch_body.assert_awaited_once_with(page)
    assert build.index_config_hash == previous.index_config_hash
    assert build.stats["chunks_embedded"] == 1
    assert build.stats["chunks_reused"] == len(chunks) - 1
    revision = next(item for item in session.added if isinstance(item, KnowledgeDocumentRevision))
    assert "body" not in revision.normalized_content
    assert "[REDACTED]" in revision.normalized_content
    assert all("body" not in value for call in embeddings.embed.await_args_list for value in call.args[0])
    assert build.stats["scrub_signature"] == stable_hash(["body"])


async def test_no_match_rule_change_still_records_signature_without_embedding():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    source.source_config["scrub_patterns"] = ["never-matches"]
    session = Session(["simple"], [[document], chunks, []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    provider.fetch_body.assert_awaited_once_with(page)
    embeddings.embed.assert_not_awaited()
    assert build.stats["scrub_signature"] == stable_hash(["never-matches"])
    assert build.source_revision != previous.source_revision
    assert build.index_config_hash == previous.index_config_hash


async def test_embedding_failure_never_creates_membership_or_promotes():
    source, version, page, provider, embeddings = inputs()
    embeddings.embed.side_effect = RuntimeError("provider unavailable")
    session = Session(["simple", None], [[]])
    async with httpx.AsyncClient() as client:
        with pytest.raises(RuntimeError, match="unavailable"):
            await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert not any(isinstance(item, KnowledgeSourceVersionDocument) for item in session.added)
    assert version.status == "pending"
    session.commit.assert_not_awaited()


async def test_missing_root_prevents_complete_snapshot():
    source, version, page, provider, embeddings = inputs()
    provider.discover.return_value = SourceSnapshot((), ())
    session = Session(["simple"])
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConfluenceError, match="Incomplete root"):
            await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert not session.added


async def test_document_budget_prevents_partial_membership():
    source, version, page, provider, embeddings = inputs()
    session = Session(["simple"])
    async with httpx.AsyncClient() as client:
        with pytest.raises(ConfluenceLimitError):
            await build_hybrid_index(
                session,
                source,
                version,
                None,
                client,
                embeddings,
                confluence=provider,
                options=HybridIndexOptions(max_total_chars=1),
            )
    assert not session.added


def test_index_identity_changes_with_model_and_chunk_contract():
    source, version, page, provider, embeddings = inputs()
    baseline = index_config_hash(HybridIndexOptions(), embeddings)
    assert baseline != index_config_hash(HybridIndexOptions(max_chunk_chars=2000), embeddings)
    embeddings.options = EmbeddingOptions("https://model.example/v1", "new-model", 2)
    assert baseline != index_config_hash(HybridIndexOptions(), embeddings)


@pytest.mark.parametrize("changes", [{"title": "Renamed"}, {"hierarchy_path": ("New parent",)}])
async def test_fresh_metadata_changes_revision_without_refetching_body(changes):
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    page = replace(page, **changes)
    provider.discover.return_value = SourceSnapshot((page,), ())
    session = Session(["simple", None], [[document], [], []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    provider.fetch_body.assert_not_awaited()
    embeddings.embed.assert_awaited()
    assert build.stats["chunks_embedded"] > 0
    revision = next(item for item in session.added if isinstance(item, KnowledgeDocumentRevision))
    assert revision.title == page.title and tuple(revision.hierarchy_path) == page.hierarchy_path
    assert revision.content_hash != document.content_hash


async def test_model_change_reembeds_cached_body_with_new_index_hash():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    embeddings.options = EmbeddingOptions("https://model.example/v1", "next-model", 2)
    session = Session(["simple"], [[document], [], []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    provider.fetch_body.assert_not_awaited()
    assert build.index_config_hash != previous.index_config_hash
    assert build.stats["chunks_embedded"] == len(chunks)
    assert not any(isinstance(item, KnowledgeDocumentRevision) for item in session.added)


async def test_new_provider_revision_with_same_body_keeps_chunks_and_tracks_latest_version():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    provider.discover.return_value = SourceSnapshot((replace(page, provider_revision="3"),), ())
    session = Session(["simple"], [[document], chunks, []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    provider.fetch_body.assert_awaited_once()
    embeddings.embed.assert_not_awaited()
    assert build.stats["provider_revisions"] == {"1": "3"}
    assert build.stats["chunks_reused"] == len(chunks)


async def test_removed_page_is_absent_from_complete_new_membership():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    removed = KnowledgeDocumentRevision(id=uuid.uuid4(), source_id=source.id, external_id="2")
    session = Session(["simple"], [[document, removed], chunks, []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert build.stats["removed_pages"] == 1
    assert {item.external_id for item in session.added if isinstance(item, KnowledgeSourceVersionDocument)} == {"1"}


async def test_incomplete_chunk_set_is_completed_without_reembedding_stored_chunks():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    assert len(chunks) >= 2
    session = Session(["simple"], [[document], chunks[:1], []], previous)
    heartbeat = AsyncMock()
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(
            session, source, version, None, client, embeddings, confluence=provider, heartbeat=heartbeat
        )
    assert build.stats["chunks_reused"] == 1
    assert build.stats["chunks_embedded"] == len(chunks) - 1
    assert heartbeat.await_count >= 2


async def test_wrong_stored_embedding_contract_aborts_instead_of_promoting():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    chunks[0].embedding = [0, 0]
    session = Session(["simple"], [[document], chunks], previous)
    async with httpx.AsyncClient() as client:
        with pytest.raises(EmbeddingError, match="finite and nonzero"):
            await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert not session.added


async def test_changed_revision_clones_exact_cached_chunks_without_embedding():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    provider.discover.return_value = SourceSnapshot((replace(page, hierarchy_path=("New parent",)),), ())
    chunks[0].embedding = SimpleNamespace(tolist=lambda: [1, 2])
    session = Session(["simple", None], [[document], [], []], previous, reusable_chunks=chunks)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    embeddings.embed.assert_not_awaited()
    assert build.stats["chunks_embedded"] == 0
    assert build.stats["chunks_reused"] == build.stats["chunk_count"] == len(chunks)
    assert build.stats["indexed_pages"] == 1 and build.stats["reused_pages"] == 0
    clones = [item for item in session.added if isinstance(item, KnowledgeChunk)]
    revision = next(item for item in session.added if isinstance(item, KnowledgeDocumentRevision))
    assert revision.id != document.id
    for original, clone in zip(chunks, clones, strict=True):
        assert clone.id != original.id and clone.document_revision_id == revision.id
        assert clone.embedding == [1.0, 2.0]
        assert clone.lexical_text == original.lexical_text and clone.content_hash == original.content_hash
    statement = session.reuse_queries[0].compile(dialect=postgresql.dialect())
    sql = str(statement)
    assert "DISTINCT ON" in sql
    assert "knowledge_document_revisions.source_id =" in sql
    assert "knowledge_document_revisions.external_id =" in sql
    assert "knowledge_document_revisions.id !=" in sql
    assert (
        "control_plane.knowledge_document_revisions.created_at DESC, control_plane.knowledge_document_revisions.id DESC"
        in sql
    )
    assert statement.params["source_id_1"] == source.id
    assert statement.params["external_id_1"] == page.page_id
    assert set(statement.params["content_hash_1"]) == {chunk.content_hash for chunk in chunks}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("content_hash", "collision"),
        ("content", "different body"),
        ("lexical_text", "different embedding input"),
        ("heading_path", ["Different heading"]),
        ("estimated_tokens", 999),
        ("index_config_hash", "different configuration"),
        ("embedding_model", "other-model"),
        ("embedding_dimensions", 3),
    ],
)
async def test_cached_chunks_require_exact_fingerprint_and_embedding_contract(field, value):
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    provider.discover.return_value = SourceSnapshot((replace(page, hierarchy_path=("New parent",)),), ())
    setattr(chunks[0], field, value)
    session = Session(["simple", None], [[document], [], []], previous, reusable_chunks=chunks)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    assert build.stats["chunks_embedded"] == 1
    assert build.stats["chunks_reused"] == len(chunks) - 1
    assert build.stats["chunk_count"] == len(chunks)
    assert sum(len(call.args[0]) for call in embeddings.embed.await_args_list) == 1


@pytest.mark.parametrize("contract", ["model", "dimensions", "chunker"])
async def test_changed_page_never_reuses_chunks_from_another_index_contract(contract):
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    provider.discover.return_value = SourceSnapshot((replace(page, hierarchy_path=("New parent",)),), ())
    options = HybridIndexOptions()
    if contract == "chunker":
        options = replace(options, overlap_chars=100)
    else:
        embeddings.options = replace(
            embeddings.options, **{"model": "new-model"} if contract == "model" else {"dimensions": 3}
        )
        embeddings.embed.side_effect = lambda texts: [[1.0] * embeddings.options.dimensions for text in texts]
    session = Session(["simple", None], [[document], [], []], previous, reusable_chunks=chunks)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(
            session, source, version, None, client, embeddings, options=options, confluence=provider
        )
    assert build.index_config_hash != previous.index_config_hash
    assert build.stats["chunks_embedded"] == build.stats["chunk_count"] == len(chunks)
    assert build.stats["chunks_reused"] == 0


async def test_reuse_query_only_requests_missing_chunk_fingerprints():
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    session = Session(["simple"], [[document], chunks[:1], []], previous)
    async with httpx.AsyncClient() as client:
        build = await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    statement = session.reuse_queries[0].compile(dialect=postgresql.dialect())
    assert set(statement.params["content_hash_1"]) == {chunk.content_hash for chunk in chunks[1:]}
    assert chunks[0].content_hash not in statement.params["content_hash_1"]
    assert build.stats["chunks_reused"] == 1


@pytest.mark.parametrize("vector", [[0, 0], [1], [float("inf"), 2]])
async def test_invalid_cached_vector_aborts_without_creating_chunk_rows(vector):
    source, version, page, provider, embeddings, document, chunks, previous = cached_inputs()
    provider.discover.return_value = SourceSnapshot((replace(page, hierarchy_path=("New parent",)),), ())
    chunks[0].embedding = vector
    session = Session(["simple", None], [[document], []], previous, reusable_chunks=chunks)
    async with httpx.AsyncClient() as client:
        with pytest.raises(EmbeddingError):
            await build_hybrid_index(session, source, version, None, client, embeddings, confluence=provider)
    embeddings.embed.assert_not_awaited()
    assert not any(isinstance(item, KnowledgeChunk) for item in session.added)
    assert not any(isinstance(item, KnowledgeSourceVersionDocument) for item in session.added)
