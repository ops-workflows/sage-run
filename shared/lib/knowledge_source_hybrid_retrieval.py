"""Authorized, version-pinned exact-vector and PostgreSQL full-text retrieval."""

from __future__ import annotations

import json
import math
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy import cast, func, literal, select
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession

from shared.lib.knowledge_source_embeddings import EmbeddingClient, EmbeddingError
from shared.lib.models import (
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)


class HybridKnowledgeUnavailableError(RuntimeError):
    """Source is disabled, suspended, unpromoted or lacks hybrid capability."""


@dataclass(frozen=True)
class RetrievalOptions:
    max_query_chars: int = 2000
    max_response_chars: int = 24000
    max_content_chars: int = 4000

    def __post_init__(self) -> None:
        if self.max_query_chars <= 0 or self.max_response_chars < 512 or self.max_content_chars <= 0:
            raise ValueError("Invalid retrieval bounds")


@dataclass(frozen=True)
class RerankOptions:
    enabled: bool = False
    base_url: str = "http://model-gateway:1235"
    model: str = ""
    timeout_sec: float = 3
    candidates: int = 20
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_sec) or self.timeout_sec <= 0 or not 1 <= self.candidates <= 40:
            raise ValueError("Invalid reranking bounds")
        if self.enabled:
            parsed = urlsplit(self.base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
                or not self.model
            ):
                raise ValueError("Invalid reranking endpoint/model")

    @classmethod
    def from_settings(cls, settings: Any, *, api_key: str = "") -> RerankOptions:
        return cls(
            enabled=getattr(settings, "knowledge_rerank_enabled", False),
            base_url=getattr(settings, "knowledge_rerank_base_url", "http://model-gateway:1235"),
            model=getattr(settings, "knowledge_rerank_model", ""),
            timeout_sec=getattr(settings, "knowledge_rerank_timeout_sec", 3),
            candidates=min(40, getattr(settings, "knowledge_rerank_candidates", 20)),
            api_key=api_key,
        )


def reciprocal_rank_fusion(dense: list[dict[str, Any]], lexical: list[dict[str, Any]]) -> list[dict[str, Any]]:
    fused: dict[str, dict[str, Any]] = {}
    for lane, candidates in (("dense", dense), ("lexical", lexical)):
        seen: set[str] = set()
        for rank, candidate in enumerate(candidates[:20], 1):
            identity = str(candidate["chunk_id"])
            if identity in seen:
                continue
            seen.add(identity)
            item = fused.setdefault(
                identity,
                {
                    **candidate,
                    "scores": {"rrf": 0.0, "dense_rank": None, "lexical_rank": None, "rerank": None},
                },
            )
            item["scores"]["rrf"] += 1.0 / (60 + rank)
            item["scores"][f"{lane}_rank"] = rank
    return sorted(fused.values(), key=lambda item: (-item["scores"]["rrf"], str(item["chunk_id"])))


def _overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    if first["page_id"] != second["page_id"]:
        return False
    first_words, second_words = first["content"].split(), second["content"].split()
    if first_words == second_words:
        return True
    if abs(first["ordinal"] - second["ordinal"]) != 1 or first["heading_path"] != second["heading_path"]:
        return False
    left, right = (first_words, second_words) if first["ordinal"] < second["ordinal"] else (second_words, first_words)
    shorter = min(len(left), len(right))
    if not shorter:
        return False
    return any(left[-size:] == right[:size] for size in range(shorter, math.ceil(shorter * 0.65) - 1, -1))


def deduplicate_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    for candidate in candidates:
        if not any(_overlap(candidate, prior) for prior in kept):
            kept.append(candidate)
    return kept


async def rerank_candidates(
    client: httpx.AsyncClient,
    options: RerankOptions,
    query: str,
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    if not options.enabled or not candidates:
        return candidates, None
    selected = candidates[: options.candidates]
    try:
        response = await client.post(
            options.base_url.rstrip("/") + "/rerank",
            headers={"Authorization": f"Bearer {options.api_key}"} if options.api_key else {},
            json={
                "model": options.model,
                "query": query,
                "documents": [item["lexical_text"] for item in selected],
                "top_n": len(selected),
                "return_documents": False,
            },
            timeout=options.timeout_sec,
            follow_redirects=False,
        )
        if response.status_code != 200 or len(response.content) > 100_000:
            raise ValueError("Unavailable reranker")
        payload = response.json()
        results = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(results, list) or len(results) != len(selected):
            raise ValueError("Incomplete rerank response")
        scores: dict[int, float] = {}
        for result in results:
            index, score = result["index"], result["relevance_score"]
            if (
                type(index) is not int
                or not 0 <= index < len(selected)
                or index in scores
                or isinstance(score, bool)
                or not isinstance(score, (int, float))
                or not math.isfinite(score)
            ):
                raise ValueError("Malformed rerank response")
            scores[index] = float(score)
        ordered = []
        for index in sorted(scores, key=lambda value: (-scores[value], value)):
            item = {**selected[index], "scores": {**selected[index]["scores"], "rerank": scores[index]}}
            ordered.append(item)
        return ordered + candidates[len(selected) :], None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OverflowError):
        return candidates, "Reranker unavailable or malformed; retained reciprocal-rank order"


class HybridKnowledgeRetriever:
    """An injected authorizer is mandatory; caller owns DB and HTTP transactions."""

    def __init__(
        self,
        embeddings: EmbeddingClient,
        client: httpx.AsyncClient,
        authorize: Callable[[str], Awaitable[None]],
        *,
        options: RetrievalOptions | None = None,
        rerank: RerankOptions | None = None,
    ) -> None:
        self.embeddings = embeddings
        self.client = client
        self.authorize = authorize
        self.options = options or RetrievalOptions()
        self.rerank = rerank or RerankOptions()

    async def pin(self, session: AsyncSession, source_alias: str) -> tuple[KnowledgeSource, KnowledgeSourceVersion]:
        await self.authorize(source_alias)
        source, version = KnowledgeSource, KnowledgeSourceVersion
        result = await session.execute(
            select(source, version)
            .join(
                version,
                version.id == source.current_successful_version_id,
            )
            .where(
                source.canonical_alias == source_alias,
                source.enabled.is_(True),
                source.serving_suspended_at.is_(None),
                source.source_kind == "confluence",
                source.index_kind == "hybrid_vector",
                version.source_id == source.id,
                version.status == "succeeded",
                version.index_kind == "hybrid_vector",
            )
            .execution_options(populate_existing=True)
        )
        pinned = result.one_or_none()
        if pinned is None:
            raise HybridKnowledgeUnavailableError("Knowledge source is unavailable or does not support hybrid search")
        return pinned[0], pinned[1]

    def candidate_statement(
        self, source: KnowledgeSource, version: KnowledgeSourceVersion, query: str, vector: list[float] | None = None
    ) -> Any:
        chunk, document, member = (
            KnowledgeChunk,
            KnowledgeDocumentRevision,
            KnowledgeSourceVersionDocument,
        )
        columns = (
            chunk.id.label("chunk_id"),
            document.external_id.label("page_id"),
            document.title,
            document.canonical_url.label("url"),
            document.hierarchy_path,
            chunk.heading_path,
            chunk.ordinal,
            chunk.content,
            chunk.lexical_text,
        )
        base = (
            select(*columns)
            .select_from(chunk)
            .join(document, document.id == chunk.document_revision_id)
            .join(
                member,
                member.document_revision_id == document.id,
            )
            .where(
                member.version_id == version.id,
                document.source_id == source.id,
                member.external_id == document.external_id,
                chunk.index_config_hash == version.index_config_hash,
            )
        )
        if vector is not None:
            filtered = (
                base.add_columns(chunk.embedding)
                .where(
                    chunk.embedding_model == self.embeddings.options.model,
                    chunk.embedding_dimensions == self.embeddings.options.dimensions,
                    func.vector_dims(chunk.embedding) == self.embeddings.options.dimensions,
                )
                .cte("current_version_chunks")
                .prefix_with("MATERIALIZED")
            )
            distance = filtered.c.embedding.cosine_distance(vector)
            return (
                select(*(filtered.c[column.key] for column in columns))
                .order_by(distance, filtered.c.chunk_id)
                .limit(20)
            )
        lexical_config = (version.stats or {}).get("lexical_config", "simple")
        tsquery = func.websearch_to_tsquery(cast(literal(lexical_config), REGCONFIG), literal(query))
        return (
            base.where(chunk.search_vector.op("@@")(tsquery))
            .order_by(
                func.ts_rank_cd(chunk.search_vector, tsquery).desc(),
                chunk.id,
            )
            .limit(20)
        )

    async def search(self, session: AsyncSession, source_alias: str, query: str, *, limit: int = 6) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip() or len(query) > self.options.max_query_chars:
            raise ValueError("Knowledge query is empty or exceeds limit")
        if type(limit) is not int or not 1 <= limit <= 6:
            raise ValueError("Knowledge result limit must be between one and six")
        query = " ".join(query.split())
        source, version = await self.pin(session, source_alias)
        warnings = []
        dense: list[dict[str, Any]] = []
        mode = "hybrid"
        stats = version.stats or {}
        try:
            if (
                stats.get("embedding_model") != self.embeddings.options.model
                or stats.get("embedding_dimensions") != self.embeddings.options.dimensions
            ):
                raise EmbeddingError("Pinned version uses another embedding contract")
            vectors = await self.embeddings.embed([query])
        except (EmbeddingError, httpx.HTTPError):
            mode = "lexical_fallback"
            warnings.append("Query embeddings unavailable or incompatible; used PostgreSQL full-text search")
        else:
            result = await session.execute(self.candidate_statement(source, version, query, vectors[0]))
            dense = [dict(row) for row in result.mappings().all()]
        result = await session.execute(self.candidate_statement(source, version, query))
        lexical = [dict(row) for row in result.mappings().all()]
        candidates = deduplicate_candidates(reciprocal_rank_fusion(dense, lexical))[:20]
        candidates, warning = await rerank_candidates(self.client, self.rerank, query, candidates)
        if warning:
            warnings.append(warning)
        response: dict[str, Any] = {
            "source": source.canonical_alias,
            "version_id": str(version.id),
            "retrieval_mode": mode,
            "warnings": warnings,
            "results": [],
            "truncated": False,
        }
        for candidate in candidates:
            item = {
                key: candidate[key] for key in ("page_id", "title", "url", "hierarchy_path", "heading_path", "scores")
            }
            item.update(
                source=source.canonical_alias,
                source_kind=source.source_kind,
                version_id=str(version.id),
                retrieval_mode=mode,
                content=candidate["content"][: self.options.max_content_chars],
            )
            original = item["content"]
            low, high = 0, len(original)
            while low < high:
                middle = (low + high + 1) // 2
                item["content"] = original[:middle]
                if (
                    len(json.dumps({**response, "results": [*response["results"], item]}, ensure_ascii=True))
                    <= self.options.max_response_chars
                ):
                    low = middle
                else:
                    high = middle - 1
            item["content"] = original[:low]
            if not low:
                response["truncated"] = True
                continue
            response["results"].append(item)
            if len(candidate["content"]) > low:
                response["truncated"] = True
            if len(response["results"]) == limit:
                break
        response["truncated"] = response["truncated"] or len(response["results"]) < min(len(candidates), limit)
        return response
