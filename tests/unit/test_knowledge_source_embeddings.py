import json

import httpx
import pytest

from shared.lib.config import Settings
from shared.lib.knowledge_source_embeddings import EmbeddingClient, EmbeddingError, EmbeddingOptions

pytestmark = pytest.mark.unit


async def test_embeddings_batch_and_restore_index_order(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fallback-secret")
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.headers["Authorization"] == "Bearer fallback-secret"
        assert request.url.path == "/v1/embeddings"
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [float(len(text)), 1.0]}
                    for index, text in reversed(list(enumerate(payload["input"])))
                ]
            },
        )

    options = EmbeddingOptions("https://model.example/v1", "embed", 2, batch_size=2)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        embeddings = EmbeddingClient(options, client)
        assert await embeddings.embed(["a", "bb", "ccc"]) == [[1, 1], [2, 1], [3, 1]]
        assert embeddings.request_count == 2
    assert [len(request["input"]) for request in requests] == [2, 1]


@pytest.mark.parametrize(
    "data",
    [
        [],
        [{"index": 0, "embedding": [1]}],
        [{"index": 0, "embedding": [0, 0]}],
        [{"index": 0, "embedding": [float("nan"), 1]}],
        [{"index": 0, "embedding": [float("inf"), 1]}],
        [{"index": 0, "embedding": [True, 1]}],
        [{"index": 1, "embedding": [1, 1]}],
        [{"index": False, "embedding": [1, 1]}],
    ],
)
async def test_invalid_vectors_and_indexes_rejected(data):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=json.dumps({"data": data}).encode()),
        )
    ) as client:
        with pytest.raises(EmbeddingError):
            await EmbeddingClient(EmbeddingOptions("https://model.example/v1", "embed", 2), client).embed(["query"])


async def test_duplicate_indexes_are_not_accepted():
    payload = {"data": [{"index": 0, "embedding": [1, 2]}, {"index": 0, "embedding": [2, 3]}]}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(EmbeddingError, match="index"):
            await EmbeddingClient(EmbeddingOptions("https://model.example/v1", "embed", 2), client).embed(["a", "b"])


async def test_errors_never_expose_provider_body_or_key():
    options = EmbeddingOptions("https://model.example/v1", "embed", 2, api_key="private-key")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(401, text="private-key private document"),
        )
    ) as client:
        with pytest.raises(EmbeddingError) as error:
            await EmbeddingClient(options, client).embed(["private document"])
    assert "private" not in str(error.value)
    assert "private-key" not in repr(options)


def test_settings_and_dimension_validation(monkeypatch):
    monkeypatch.setenv("LLM_API_KEY", "fallback-secret")
    settings = Settings(
        knowledge_embeddings_openai_base_url="https://model.example/v1",
        knowledge_embeddings_openai_model="embed",
        knowledge_embeddings_dimensions=2,
        knowledge_embeddings_openai_api_key="",
    )
    options = EmbeddingOptions.from_settings(settings)
    assert options.api_key == "fallback-secret"
    with pytest.raises(ValueError):
        EmbeddingOptions("https://model.example/v1", "embed", 0)


def test_loader_matches_foundation_setting_names():
    settings = Settings(
        knowledge_embeddings_openai_base_url="https://model.example/v1",
        knowledge_embeddings_openai_model="foundation-model",
        knowledge_embeddings_dimensions=2,
        knowledge_embeddings_openai_api_key="configured-secret",
        knowledge_embeddings_batch_size=8,
        knowledge_embeddings_timeout_sec=30,
    )
    options = EmbeddingOptions.from_settings(settings)
    assert options.model == "foundation-model"
    assert options.api_key == "configured-secret"
    assert options.batch_size == 8
    assert options.timeout_sec == 30


@pytest.mark.parametrize("alias", ["knowledge_embeddings_model", "knowledge_embeddings_api_key"])
def test_undeclared_aliases_are_rejected(alias):
    with pytest.raises(ValueError, match="Extra inputs are not permitted"):
        Settings(**{alias: "unsupported-alias"})
