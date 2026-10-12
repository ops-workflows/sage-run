from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from shared.lib.knowledge_source_confluence import (
    ConfluenceClient,
    ConfluenceError,
    ConfluenceSecurityError,
    PageMetadata,
    chunk_document,
    document_hash,
    normalize_storage,
)

pytestmark = pytest.mark.unit


def connection():
    return SimpleNamespace(base_url="https://wiki.example/wiki", username="service", token="secret", auth_type="basic")


@pytest.mark.parametrize("base_url", ["http://localhost:1234/wiki", "http://127.0.0.2/wiki", "http://[::1]/wiki"])
async def test_loopback_http_discovery_matches_connection_loader(base_url):
    config = connection()
    config.base_url = base_url

    def handler(request):
        if request.url.path.endswith("/descendants"):
            return httpx.Response(200, json={"results": []})
        return httpx.Response(200, json={"id": "1", "title": "Root", "version": {"number": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = ConfluenceClient(config, client)
        snapshot = await provider.discover(["1"])
        assert snapshot.pages[0].canonical_url == base_url + "/pages/1"
        with pytest.raises(ConfluenceSecurityError):
            provider._url("http://localhost:4321/wiki/api/v2/pages/1/descendants", "/wiki/api/v2/pages/1/descendants")


async def test_remote_http_connection_is_rejected_before_fetch():
    config = connection()
    config.base_url = "http://wiki.example/wiki"
    async with httpx.AsyncClient() as client:
        with pytest.raises(ValueError, match="HTTPS"):
            ConfluenceClient(config, client)


@pytest.mark.parametrize("auth_type,username", [("bearer", "service"), ("basic", "")])
async def test_client_requires_supported_basic_authentication_before_request(auth_type, username):
    config = connection()
    config.auth_type, config.username = auth_type, username
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ValueError, match="basic authentication and a username"):
            ConfluenceClient(config, client)
    assert requests == []


async def test_client_sends_basic_authentication():
    def handler(request):
        assert request.headers["Authorization"] == "Basic c2VydmljZTpzZWNyZXQ="
        return httpx.Response(200, json={"id": "1", "title": "Root", "version": {"number": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await ConfluenceClient(connection(), client).discover(["1"], include_descendants=False)


@pytest.mark.parametrize(
    "next_link",
    [
        "https://evil.example/wiki/api/v2/pages/1/descendants?cursor=x",
        "//evil.example/wiki/api/v2/pages/1/descendants",
        "/wiki/api/v2/users?cursor=x",
        "/wiki/api/v2/pages/1/%64escendants?cursor=x",
        "https://wiki.example:invalid/wiki/api/v2/pages/1/descendants?cursor=x",
        "https://[invalid/wiki/api/v2/pages/1/descendants?cursor=x",
    ],
)
async def test_pagination_rejects_untrusted_destinations_before_request(next_link):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.path.endswith("/descendants"):
            return httpx.Response(200, json={"results": [], "_links": {"next": next_link}})
        return httpx.Response(200, json={"id": "1", "title": "Root", "version": {"number": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(ConfluenceSecurityError):
            await ConfluenceClient(connection(), client).discover(["1"])
    assert len(requests) == 2
    assert all(request.url.host == "wiki.example" for request in requests)


async def test_discovery_keeps_pages_below_structural_parents_and_fetches_metadata_only():
    requests = []

    def handler(request):
        requests.append(str(request.url))
        if request.url.path.endswith("/descendants"):
            if "cursor" not in request.url.params:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {"id": "2", "type": "folder", "title": "Folder", "parentId": "1"},
                        ],
                        "_links": {"next": "/wiki/api/v2/pages/1/descendants?cursor=next"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": "3", "type": "page", "parentId": "2"},
                        {"id": "3", "type": "page", "parentId": "2"},
                    ]
                },
            )
        page_id = request.url.path.rsplit("/", 1)[1]
        return httpx.Response(
            200,
            json={
                "id": page_id,
                "title": "Root" if page_id == "1" else "Child",
                "version": {"number": 2},
                "parentId": None if page_id == "1" else "2",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        snapshot = await ConfluenceClient(connection(), client).discover(["1"])
    assert [page.page_id for page in snapshot.pages] == ["1", "3"]
    assert snapshot.pages[1].hierarchy_path == ("Root", "Folder")
    assert snapshot.skipped_items == 1
    assert len(requests) == 4
    assert all("body-format" not in request for request in requests)


async def test_forbidden_root_is_security_sensitive():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client:
        with pytest.raises(ConfluenceSecurityError, match="root access revoked"):
            await ConfluenceClient(connection(), client).discover(["1"])


def test_normalization_and_chunking_are_deterministic_and_bounded():
    xhtml = (
        """<h1 data-editor='x'>Recovery</h1><p>Read <a href='https://docs.example/a'>guide</a>.</p>
    <!-- secret --><script>hidden()</script><style>hidden</style>
    <table><tr><th>Host</th><th>Action</th></tr><tr><td>db</td><td>restart</td></tr></table>
    <ac:structured-macro ac:name='code'><ac:plain-text-body><![CDATA[print('ok')\nnext()]]></ac:plain-text-body>
    </ac:structured-macro><ac:structured-macro ac:name='unsupported'><p>private payload</p></ac:structured-macro>
    <ul><li>first</li><li>second</li></ul><p>"""
        + "long prose " * 80
        + "</p>"
    )
    normalized = normalize_storage(xhtml)
    assert normalized == normalize_storage(xhtml)
    assert "guide (https://docs.example/a)" in normalized.content
    assert "Host: db | Action: restart" in normalized.content
    assert "print('ok')\nnext()" in normalized.content
    assert "private payload" not in normalized.content
    assert "hidden" not in normalized.content
    chunks = chunk_document(normalized, "Runbook", max_chars=150, max_tokens=50, overlap_chars=20)
    assert all(len(chunk.lexical_text) <= 150 and chunk.estimated_tokens <= 50 for chunk in chunks)
    assert [chunk.ordinal for chunk in chunks] == list(range(len(chunks)))
    assert all(chunk.heading_path == ("Recovery",) for chunk in chunks)
    assert chunks == chunk_document(normalized, "Runbook", max_chars=150, max_tokens=50, overlap_chars=20)


def test_normalized_hash_distinguishes_headings_code_and_metadata():
    page = PageMetadata("1", "1", "Title", "https://wiki.example/wiki/pages/1", (), "1")
    plain = normalize_storage("<p>Text</p>")
    heading = normalize_storage("<h1>Text</h1>")
    code = normalize_storage("<pre>Text</pre>")
    assert len({document_hash(page, document) for document in (plain, heading, code)}) == 3
    renamed = PageMetadata("1", "1", "New title", page.canonical_url, ("Parent",), "1")
    assert document_hash(renamed, plain) != document_hash(page, plain)
    assert document_hash(page, normalize_storage("<h1>Text</h1>")) != document_hash(
        page,
        normalize_storage("<p># Text</p>"),
    )


def test_confluence_links_keep_label_and_target_and_malformed_html_is_stable():
    body = """<p>See <ac:link><ri:page ri:content-title='Recovery'/>
    <ac:plain-text-link-body>the runbook</ac:plain-text-link-body></ac:link><p>Next"""
    normalized = normalize_storage(body)
    assert "the runbook (Recovery)" in normalized.content
    assert normalized == normalize_storage(body)


async def test_cloud_webui_links_keep_wiki_prefix():
    payload = {"id": "1", "title": "Root", "version": {"number": 1}, "_links": {"webui": "/spaces/OPS/pages/1/Root"}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        snapshot = await ConfluenceClient(connection(), client).discover(["1"], include_descendants=False)
    assert snapshot.pages[0].canonical_url == "https://wiki.example/wiki/spaces/OPS/pages/1/Root"


async def test_rate_limit_honors_retry_after_and_heartbeats(monkeypatch):
    wait = AsyncMock()
    monkeypatch.setattr("shared.lib.knowledge_source_confluence.asyncio.sleep", wait)
    replies = [
        httpx.Response(429, headers={"Retry-After": "2"}),
        httpx.Response(200, json={"id": "1", "title": "Root", "version": {"number": 1}}),
    ]
    heartbeat = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: replies.pop(0))) as client:
        provider = ConfluenceClient(connection(), client, heartbeat=heartbeat)
        snapshot = await provider.discover(["1"], include_descendants=False)
    assert snapshot.pages[0].page_id == "1"
    wait.assert_awaited_once_with(2.0)
    assert heartbeat.await_count == 2


async def test_transient_failure_is_not_security_sensitive(monkeypatch):
    monkeypatch.setattr("shared.lib.knowledge_source_confluence.asyncio.sleep", AsyncMock())
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as client:
        provider = ConfluenceClient(connection(), client, retries=1)
        with pytest.raises(ConfluenceError) as error:
            await provider.discover(["1"])
    assert not isinstance(error.value, ConfluenceSecurityError)
    assert provider.request_count == 2


async def test_changed_version_during_body_fetch_aborts_snapshot():
    page = PageMetadata("1", "1", "Root", "https://wiki.example/wiki/pages/1", (), "1")
    payload = {"id": "1", "version": {"number": 2}, "body": {"storage": {"value": "<p>body</p>"}}}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ConfluenceError, match="changed during"):
            await ConfluenceClient(connection(), client).fetch_body(page)


def test_oversized_prose_chunks_retain_bounded_overlap():
    document = normalize_storage("<p>" + " ".join(f"word{index}" for index in range(100)) + "</p>")
    chunks = chunk_document(document, "Title", max_chars=180, max_tokens=80, overlap_chars=24)
    assert len(chunks) > 2
    assert all(len(chunk.lexical_text) <= 180 for chunk in chunks)
    assert all(
        second.content.startswith(first.content[-24:]) for first, second in zip(chunks[:-1], chunks[1:], strict=True)
    )


@pytest.mark.parametrize("body", ["<pre>{text}</pre>", "<table><tr><td>{text}</td></tr></table>"])
def test_oversized_code_and_table_blocks_respect_token_and_character_limits(body):
    document = normalize_storage(body.format(text="singlelongword" * 100))
    chunks = chunk_document(document, "Title", max_chars=150, max_tokens=30, overlap_chars=20)
    assert len(chunks) > 2
    assert all(len(chunk.lexical_text) <= 90 and chunk.estimated_tokens <= 30 for chunk in chunks)
