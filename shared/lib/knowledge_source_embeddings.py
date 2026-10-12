"""Validated OpenAI-compatible embeddings shared by ingestion and retrieval."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

if TYPE_CHECKING:
    from shared.lib.config import Settings


class EmbeddingError(RuntimeError):
    """Sanitized provider or embedding contract failure."""


@dataclass(frozen=True)
class EmbeddingOptions:
    base_url: str
    model: str
    dimensions: int
    api_key: str = field(default="", repr=False)
    batch_size: int = 16
    timeout_sec: float = 60
    max_input_chars: int = 100_000

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Invalid embedding endpoint")
        if parsed.query or parsed.fragment or not self.model.strip():
            raise ValueError("Embedding endpoint and model are required")
        if (
            type(self.dimensions) is not int
            or not 1 <= self.dimensions <= 65535
            or type(self.batch_size) is not int
            or not 1 <= self.batch_size <= 1024
            or not math.isfinite(self.timeout_sec)
            or self.timeout_sec <= 0
            or self.max_input_chars <= 0
        ):
            raise ValueError("Invalid embedding dimensions or bounds")

    @classmethod
    def from_settings(cls, settings: Settings) -> EmbeddingOptions:
        return cls(
            base_url=settings.knowledge_embeddings_openai_base_url,
            model=settings.knowledge_embeddings_openai_model,
            dimensions=settings.knowledge_embeddings_dimensions,
            api_key=settings.knowledge_embeddings_openai_api_key or os.environ.get("LLM_API_KEY", ""),
            batch_size=settings.knowledge_embeddings_batch_size,
            timeout_sec=settings.knowledge_embeddings_timeout_sec,
        )


def validate_vector(value: Any, dimensions: int) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise EmbeddingError("Embedding dimension mismatch")
    if any(isinstance(number, bool) or not isinstance(number, (int, float)) for number in value):
        raise EmbeddingError("Embedding contains nonnumeric values")
    try:
        vector = [float(number) for number in value]
    except (ValueError, OverflowError):
        raise EmbeddingError("Embedding contains invalid values") from None
    if not all(math.isfinite(number) for number in vector) or not any(number != 0 for number in vector):
        raise EmbeddingError("Embedding must be finite and nonzero")
    return vector


class EmbeddingClient:
    """Sequential bounded batches; caller owns the injected HTTP client."""

    def __init__(self, options: EmbeddingOptions, client: httpx.AsyncClient) -> None:
        self.options = options
        self.client = client
        self.request_count = 0
        self.input_characters = 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if any(
            not isinstance(text, str) or not text.strip() or len(text) > self.options.max_input_chars for text in texts
        ):
            raise EmbeddingError("Embedding input is empty or exceeds limit")
        vectors: list[list[float]] = []
        for offset in range(0, len(texts), self.options.batch_size):
            batch = texts[offset : offset + self.options.batch_size]
            vectors.extend(await self._batch(batch))
        return vectors

    async def probe(self) -> None:
        await self.embed(["knowledge embedding dimension probe"])

    async def _batch(self, texts: list[str]) -> list[list[float]]:
        key = self.options.api_key or os.environ.get("LLM_API_KEY", "")
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        try:
            self.request_count += 1
            self.input_characters += sum(map(len, texts))
            response = await self.client.post(
                self.options.base_url.rstrip("/") + "/embeddings",
                headers=headers,
                json={"model": self.options.model, "input": texts, "dimensions": self.options.dimensions},
                timeout=self.options.timeout_sec,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise EmbeddingError("Embedding transport failed") from None
        if response.status_code != 200:
            raise EmbeddingError(f"Embedding endpoint failed (HTTP {response.status_code})")
        if len(response.content) > max(4096, len(texts) * self.options.dimensions * 64):
            raise EmbeddingError("Embedding response exceeds limit")
        try:
            payload = response.json()
        except ValueError:
            raise EmbeddingError("Malformed embedding response") from None
        if not isinstance(payload, dict) or payload.get("model", self.options.model) != self.options.model:
            raise EmbeddingError("Embedding response model mismatch")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(texts):
            raise EmbeddingError("Embedding response count mismatch")
        ordered: dict[int, list[float]] = {}
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingError("Malformed embedding item")
            index = item.get("index")
            if type(index) is not int or not 0 <= index < len(texts) or index in ordered:
                raise EmbeddingError("Embedding response index mismatch")
            ordered[index] = validate_vector(item.get("embedding"), self.options.dimensions)
        return [ordered[index] for index in range(len(texts))]
