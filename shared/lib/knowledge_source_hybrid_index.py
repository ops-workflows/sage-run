"""Build complete hybrid snapshots without committing or promoting caller state."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from typing import Any

import httpx
from sqlalchemy import and_, cast, func, literal, literal_column, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from shared.lib.knowledge_source_confluence import (
    CHUNKER_VERSION,
    NORMALIZER_VERSION,
    ConfluenceClient,
    ConfluenceError,
    ConfluenceLimitError,
    ContentBlock,
    NormalizedDocument,
    PageMetadata,
    chunk_document,
    document_hash,
    normalize_storage,
    normalized_text,
    stable_hash,
)
from shared.lib.knowledge_source_embeddings import EmbeddingClient, validate_vector
from shared.lib.knowledge_source_scrubbing import compile_scrub_rules, scrub_document
from shared.lib.models import (
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)
from shared.lib.platform_secrets import ConfluenceConnection

INDEXER_VERSION = "confluence-hybrid-1"


@dataclass(frozen=True)
class HybridIndexOptions:
    max_pages: int = 10000
    max_chunks: int = 100000
    max_body_chars: int = 2_000_000
    max_total_chars: int = 50_000_000
    max_chunk_chars: int = 2400
    max_chunk_tokens: int = 800
    overlap_chars: int = 200
    concurrency: int = 6
    lexical_config: str = "simple"

    def __post_init__(self) -> None:
        if (
            any(
                value <= 0
                for value in (
                    self.max_pages,
                    self.max_chunks,
                    self.max_body_chars,
                    self.max_total_chars,
                    self.max_chunk_chars,
                    self.max_chunk_tokens,
                    self.concurrency,
                )
            )
            or not 0 <= self.overlap_chars < self.max_chunk_chars
        ):
            raise ValueError("Invalid hybrid index bounds")
        if not self.lexical_config or len(self.lexical_config) > 128:
            raise ValueError("Invalid lexical configuration")


@dataclass(frozen=True)
class HybridIndexBuild:
    source_revision: str
    index_config_hash: str
    stats: dict[str, Any]
    warnings: tuple[str, ...]
    unchanged: bool
    indexer_version: str = INDEXER_VERSION


def index_config_hash(options: HybridIndexOptions, embeddings: EmbeddingClient) -> str:
    return stable_hash(
        {
            "schema": 1,
            "normalizer": NORMALIZER_VERSION,
            "chunker": CHUNKER_VERSION,
            "max_chars": options.max_chunk_chars,
            "max_tokens": options.max_chunk_tokens,
            "overlap": options.overlap_chars,
            "lexical_config": options.lexical_config,
            "embedding_model": embeddings.options.model,
            "embedding_dimensions": embeddings.options.dimensions,
        }
    )


def _document_metadata(document: KnowledgeDocumentRevision) -> dict[str, Any]:
    return document.document_metadata or {}


def _cached_document(document: KnowledgeDocumentRevision) -> NormalizedDocument | None:
    metadata = _document_metadata(document)
    if metadata.get("normalizer_version") != NORMALIZER_VERSION or not isinstance(metadata.get("blocks"), list):
        return None
    try:
        blocks = tuple(
            ContentBlock(item["kind"], item["text"], tuple(item["heading_path"])) for item in metadata["blocks"]
        )
        if any(not isinstance(block.text, str) or not isinstance(block.kind, str) for block in blocks):
            return None
        if normalized_text(blocks) != document.normalized_content:
            return None
        return NormalizedDocument(blocks, document.normalized_content)
    except (KeyError, TypeError):
        return None


def _chunk_fingerprint(chunk: Any) -> tuple[str, str, str, tuple[str, ...], int]:
    return (
        chunk.content_hash,
        chunk.content,
        chunk.lexical_text,
        tuple(chunk.heading_path),
        chunk.estimated_tokens,
    )


async def _reusable_chunk_vectors(
    session: AsyncSession,
    document: KnowledgeDocumentRevision,
    missing: list[Any],
    config_hash: str,
    embeddings: EmbeddingClient,
) -> dict[tuple[str, str, str, tuple[str, ...], int], list[float]]:
    if not missing:
        return {}
    chunk_model = KnowledgeChunk
    revision_model = KnowledgeDocumentRevision
    fingerprints = {_chunk_fingerprint(chunk) for chunk in missing}
    fingerprint_columns = (
        chunk_model.content_hash,
        chunk_model.content,
        chunk_model.lexical_text,
        chunk_model.heading_path,
        chunk_model.estimated_tokens,
    )
    candidates = (
        await session.scalars(
            select(chunk_model)
            .join(revision_model, revision_model.id == chunk_model.document_revision_id)
            .where(
                revision_model.source_id == document.source_id,
                revision_model.external_id == document.external_id,
                revision_model.id != document.id,
                chunk_model.index_config_hash == config_hash,
                chunk_model.embedding_model == embeddings.options.model,
                chunk_model.embedding_dimensions == embeddings.options.dimensions,
                chunk_model.content_hash.in_({fingerprint[0] for fingerprint in fingerprints}),
                or_(
                    *(
                        and_(
                            chunk_model.content_hash == content_hash,
                            chunk_model.content == content,
                            chunk_model.lexical_text == lexical_text,
                            chunk_model.heading_path == list(heading_path),
                            chunk_model.estimated_tokens == estimated_tokens,
                        )
                        for content_hash, content, lexical_text, heading_path, estimated_tokens in sorted(fingerprints)
                    )
                ),
            )
            .distinct(*fingerprint_columns)
            .order_by(
                *fingerprint_columns,
                revision_model.created_at.desc(),
                revision_model.id.desc(),
                chunk_model.ordinal,
                chunk_model.id,
            )
        )
    ).all()
    vectors = {}
    for chunk in candidates:
        fingerprint = _chunk_fingerprint(chunk)
        if (
            fingerprint not in fingerprints
            or chunk.index_config_hash != config_hash
            or chunk.embedding_model != embeddings.options.model
            or chunk.embedding_dimensions != embeddings.options.dimensions
        ):
            continue
        vector = chunk.embedding.tolist() if hasattr(chunk.embedding, "tolist") else chunk.embedding
        vectors[fingerprint] = validate_vector(vector, embeddings.options.dimensions)
    return vectors


async def _ensure_chunks(
    session: AsyncSession,
    document: KnowledgeDocumentRevision,
    normalized: NormalizedDocument,
    config_hash: str,
    options: HybridIndexOptions,
    embeddings: EmbeddingClient,
    remaining: int,
    heartbeat: Callable[[], Awaitable[None]] | None,
) -> tuple[int, int]:
    chunk_model = KnowledgeChunk
    expected = chunk_document(
        normalized,
        document.title,
        max_chars=options.max_chunk_chars,
        max_tokens=options.max_chunk_tokens,
        overlap_chars=options.overlap_chars,
        max_chunks=min(options.max_chunks, max(1, remaining)),
    )
    if len(expected) > remaining:
        raise ConfluenceLimitError("Source chunk limit exceeded")
    existing = list(
        (
            await session.scalars(
                select(chunk_model)
                .where(
                    chunk_model.document_revision_id == document.id,
                    chunk_model.index_config_hash == config_hash,
                )
                .order_by(chunk_model.ordinal)
            )
        ).all()
    )
    by_ordinal = {}
    for chunk in existing:
        if chunk.ordinal in by_ordinal or not 0 <= chunk.ordinal < len(expected):
            raise ValueError("Stored chunk ordinals are inconsistent")
        candidate = expected[chunk.ordinal]
        if (
            chunk.content_hash != candidate.content_hash
            or chunk.content != candidate.content
            or chunk.lexical_text != candidate.lexical_text
            or tuple(chunk.heading_path) != candidate.heading_path
            or chunk.estimated_tokens != candidate.estimated_tokens
            or chunk.embedding_model != embeddings.options.model
            or chunk.embedding_dimensions != embeddings.options.dimensions
        ):
            raise ValueError("Stored immutable chunk does not match index contract")
        vector = chunk.embedding.tolist() if hasattr(chunk.embedding, "tolist") else chunk.embedding
        validate_vector(vector, embeddings.options.dimensions)
        by_ordinal[chunk.ordinal] = chunk
    missing = [chunk for chunk in expected if chunk.ordinal not in by_ordinal]
    cached_vectors = await _reusable_chunk_vectors(session, document, missing, config_hash, embeddings)
    regconfig = cast(literal(options.lexical_config), REGCONFIG)
    embedded = 0
    for offset in range(0, len(missing), embeddings.options.batch_size):
        batch = missing[offset : offset + embeddings.options.batch_size]
        fresh = [chunk for chunk in batch if _chunk_fingerprint(chunk) not in cached_vectors]
        if heartbeat:
            await heartbeat()
        vectors = await embeddings.embed([chunk.lexical_text for chunk in fresh]) if fresh else []
        if len(vectors) != len(fresh):
            raise ValueError("Embedding client returned incomplete chunk batch")
        fresh_vectors = {chunk.ordinal: vector for chunk, vector in zip(fresh, vectors, strict=True)}
        embedded += len(fresh)
        for chunk in batch:
            fingerprint = _chunk_fingerprint(chunk)
            vector = cached_vectors[fingerprint] if fingerprint in cached_vectors else fresh_vectors[chunk.ordinal]
            weighted_title = func.setweight(
                func.to_tsvector(regconfig, literal("\n".join((document.title, *chunk.heading_path)))),
                literal_column("'A'::\"char\""),
            )
            weighted_body = func.setweight(
                func.to_tsvector(regconfig, literal(chunk.content)), literal_column("'B'::\"char\"")
            )
            session.add(
                chunk_model(
                    id=uuid.uuid4(),
                    document_revision_id=document.id,
                    index_config_hash=config_hash,
                    ordinal=chunk.ordinal,
                    heading_path=list(chunk.heading_path),
                    content=chunk.content,
                    content_hash=chunk.content_hash,
                    estimated_tokens=chunk.estimated_tokens,
                    lexical_text=chunk.lexical_text,
                    search_vector=weighted_title.op("||")(weighted_body),
                    embedding=validate_vector(vector, embeddings.options.dimensions),
                    embedding_model=embeddings.options.model,
                    embedding_dimensions=embeddings.options.dimensions,
                )
            )
        await session.flush()
    return embedded, len(existing) + len(missing) - embedded


async def build_hybrid_index(
    session: AsyncSession,
    source: KnowledgeSource,
    version: KnowledgeSourceVersion,
    connection: ConfluenceConnection,
    client: httpx.AsyncClient,
    embeddings: EmbeddingClient,
    *,
    options: HybridIndexOptions | None = None,
    confluence: ConfluenceClient | None = None,
    heartbeat: Callable[[], Awaitable[None]] | None = None,
) -> HybridIndexBuild:
    """Flush immutable rows and complete membership, but never commit or promote.

    Caller must hold the source sync lock, supply a flushed pending version, and
    atomically assign the returned revision/config/stats plus succeeded status and
    current pointer after success. Failure requires caller rollback or cleanup.
    ConfluenceSecurityError requires caller suspension in a separate transaction.
    """
    if (source.source_kind, source.index_kind) != ("confluence", "hybrid_vector"):
        raise ValueError("Unsupported source/index pair")
    if not version.id or version.source_id != source.id or version.status not in {"pending", "running"}:
        raise ValueError("A flushed pending version for this source is required")
    config = source.source_config or {}
    scrub_rules = compile_scrub_rules(config.get("scrub_patterns", []))
    scrub_signature = stable_hash([rule.pattern for rule in scrub_rules])
    if config.get("body_format", "storage") != "storage":
        raise ValueError("Only Confluence storage bodies are supported")
    options = options or HybridIndexOptions(lexical_config=config.get("lexical_config", "simple"))
    if await session.scalar(select(cast(literal(options.lexical_config), REGCONFIG))) is None:
        raise ValueError("Lexical configuration is not installed in PostgreSQL")
    provider = confluence or ConfluenceClient(
        connection,
        client,
        concurrency=options.concurrency,
        max_pages=options.max_pages,
        max_body_chars=options.max_body_chars,
        heartbeat=heartbeat,
    )
    previous = None
    if source.current_successful_version_id:
        previous = await session.get(KnowledgeSourceVersion, source.current_successful_version_id)
        if previous is None or previous.status != "succeeded" or previous.source_id != source.id:
            raise ValueError("Invalid current successful version")
    prior_documents = {}
    revision_model, membership_model = KnowledgeDocumentRevision, KnowledgeSourceVersionDocument
    if previous:
        documents = (
            await session.scalars(
                select(revision_model)
                .join(
                    membership_model,
                    membership_model.document_revision_id == revision_model.id,
                )
                .where(membership_model.version_id == previous.id, revision_model.source_id == source.id)
            )
        ).all()
        prior_documents = {document.external_id: document for document in documents}
    previous_states = (previous.stats or {}).get("provider_revisions", {}) if previous else {}
    rules_unchanged = previous is not None and (previous.stats or {}).get("scrub_signature") == scrub_signature
    request_start = embeddings.request_count
    characters_start = embeddings.input_characters
    provider_start = provider.request_count
    await embeddings.probe()
    snapshot = await provider.discover(
        config.get("root_page_ids", []), include_descendants=config.get("include_descendants", True)
    )
    if len(snapshot.pages) > options.max_pages:
        raise ConfluenceLimitError("Source page limit exceeded")
    warnings = list(snapshot.warnings)
    members: list[tuple[PageMetadata, Any]] = []
    embedded = reused_chunks = reused_pages = total_chars = 0
    provider_revisions: dict[str, str] = {}
    for page in snapshot.pages:
        if heartbeat:
            await heartbeat()
        prior = prior_documents.get(page.page_id)
        normalized = None
        provider_revision = previous_states.get(page.page_id, prior.provider_revision if prior else None)
        if prior is not None and provider_revision == page.provider_revision and rules_unchanged:
            normalized = _cached_document(prior)
        if normalized is None:
            body = await provider.fetch_body(page)
            if body is None:
                if page.page_id == page.root_page_id:
                    raise ConfluenceError("Configured root missing from build")
                if len(warnings) < 100:
                    warnings.append(f"Omitted inaccessible page {page.page_id}")
                continue
            if len(body) > options.max_body_chars:
                raise ConfluenceLimitError("Source body limit exceeded")
            normalized = scrub_document(normalize_storage(body), scrub_rules)
        total_chars += len(normalized.content)
        if total_chars > options.max_total_chars:
            raise ConfluenceLimitError("Source text limit exceeded")
        content_hash = document_hash(page, normalized)
        if prior is not None and prior.content_hash == content_hash:
            document = prior
        else:
            document = await session.scalar(
                select(revision_model).where(
                    revision_model.source_id == source.id,
                    revision_model.external_id == page.page_id,
                    revision_model.content_hash == content_hash,
                )
            )
            if document is None:
                document = revision_model(
                    id=uuid.uuid4(),
                    source_id=source.id,
                    external_id=page.page_id,
                    provider_revision=page.provider_revision,
                    title=page.title,
                    canonical_url=page.canonical_url,
                    hierarchy_path=list(page.hierarchy_path),
                    normalized_content=normalized.content,
                    content_hash=content_hash,
                    document_metadata={
                        "normalizer_version": NORMALIZER_VERSION,
                        "blocks": [asdict(block) for block in normalized.blocks],
                    },
                )
                session.add(document)
                await session.flush()
        created, reused = await _ensure_chunks(
            session,
            document,
            normalized,
            config_hash=index_config_hash(options, embeddings),
            options=options,
            embeddings=embeddings,
            remaining=options.max_chunks - embedded - reused_chunks,
            heartbeat=heartbeat,
        )
        embedded += created
        reused_chunks += reused
        reused_pages += int(created == 0 and prior is not None and prior.id == document.id)
        members.append((page, document))
        provider_revisions[page.page_id] = page.provider_revision
    roots = {str(value) for value in config.get("root_page_ids", [])}
    if not roots.issubset({page.page_id for page, _ in members}):
        raise ConfluenceError("Incomplete root membership; snapshot cannot be promoted")
    config_hash = index_config_hash(options, embeddings)
    source_revision = stable_hash(
        {
            "scrub_signature": scrub_signature,
            "pages": sorted(
                [page.page_id, page.provider_revision, document.content_hash, list(page.hierarchy_path)]
                for page, document in members
            ),
        }
    )
    existing_members = (
        await session.scalars(select(membership_model).where(membership_model.version_id == version.id))
    ).all()
    if existing_members:
        raise ValueError("Pending version already has membership; use a new version or clean it before retry")
    for page, document in members:
        session.add(
            membership_model(
                version_id=version.id,
                document_revision_id=document.id,
                external_id=page.page_id,
                root_page_id=page.root_page_id,
            )
        )
    await session.flush()
    stats = {
        "discovered_pages": len(snapshot.pages),
        "indexed_pages": len(members) - reused_pages,
        "reused_pages": reused_pages,
        "removed_pages": len(set(prior_documents) - set(provider_revisions)),
        "document_count": len(members),
        "chunk_count": embedded + reused_chunks,
        "chunks_embedded": embedded,
        "chunks_reused": reused_chunks,
        "skipped_items": snapshot.skipped_items,
        "warning_count": len(warnings),
        "normalized_characters": total_chars,
        "embedding_requests": embeddings.request_count - request_start,
        "embedding_input_characters": embeddings.input_characters - characters_start,
        "provider_requests": provider.request_count - provider_start,
        "provider_revisions": provider_revisions,
        "embedding_model": embeddings.options.model,
        "embedding_dimensions": embeddings.options.dimensions,
        "lexical_config": options.lexical_config,
        "scrub_signature": scrub_signature,
    }
    unchanged = bool(
        previous and previous.source_revision == source_revision and previous.index_config_hash == config_hash
    )
    return HybridIndexBuild(source_revision, config_hash, stats, tuple(warnings), unchanged)
