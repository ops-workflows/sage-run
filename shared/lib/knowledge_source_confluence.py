"""Bounded Confluence Cloud discovery and deterministic storage-body processing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
import secrets
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from ipaddress import ip_address
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Comment, NavigableString, Tag

NORMALIZER_VERSION = "confluence-storage-1"
CHUNKER_VERSION = "heading-paragraph-1"


class ConfluenceError(RuntimeError):
    """Provider failure with no credentials or response body in its message."""


class ConfluenceSecurityError(ConfluenceError):
    """Caller must suspend serving when credentials or configured roots are revoked."""


class ConfluenceLimitError(ConfluenceError):
    """Discovery or content exceeded a configured bound; do not promote."""


@dataclass(frozen=True)
class PageMetadata:
    page_id: str
    provider_revision: str
    title: str
    canonical_url: str
    hierarchy_path: tuple[str, ...]
    root_page_id: str
    parent_id: str | None = None


@dataclass(frozen=True)
class SourceSnapshot:
    pages: tuple[PageMetadata, ...]
    warnings: tuple[str, ...]
    skipped_items: int = 0


@dataclass(frozen=True)
class ContentBlock:
    kind: str
    text: str
    heading_path: tuple[str, ...] = ()


@dataclass(frozen=True)
class NormalizedDocument:
    blocks: tuple[ContentBlock, ...]
    content: str


@dataclass(frozen=True)
class DocumentChunk:
    ordinal: int
    heading_path: tuple[str, ...]
    content: str
    content_hash: str
    estimated_tokens: int
    lexical_text: str


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode()
    ).hexdigest()


def document_hash(page: PageMetadata, document: NormalizedDocument) -> str:
    return stable_hash(
        [
            NORMALIZER_VERSION,
            page.title,
            page.canonical_url,
            page.hierarchy_path,
            document.content,
            [asdict(block) for block in document.blocks],
        ]
    )


def _inline(node: Tag | NavigableString) -> str:
    if isinstance(node, NavigableString):
        return str(node)
    if node.name == "br":
        return "\n"
    if node.name == "ac:link":
        page = node.find("ri:page")
        label = node.find(["ac:plain-text-link-body", "ac:link-body"])
        target = str(page.get("ri:content-title", "")) if page else ""
        if target:
            return f"{_compact(label.get_text())} ({target})" if label else target
    text = "".join(_inline(child) for child in node.children if isinstance(child, (Tag, NavigableString)))
    if node.name == "a" and node.get("href"):
        target = str(node["href"])
        if urlsplit(target).scheme.lower() in {"", "http", "https", "mailto"}:
            return f"{text.strip()} ({target})"
    if node.name == "ri:page" and node.get("ri:content-title"):
        return str(node["ri:content-title"])
    return text


def _compact(text: str) -> str:
    return " ".join(text.split())


def normalized_text(blocks: tuple[ContentBlock, ...]) -> str:
    return "\n\n".join(
        f"{'#' * len(block.heading_path)} {block.text}"
        if block.kind == "heading"
        else f"```\n{block.text}\n```"
        if block.kind == "code"
        else block.text
        for block in blocks
    )


def normalize_storage(xhtml: str) -> NormalizedDocument:
    """Normalize blocks without rendering HTML or retaining editor/macro payloads."""
    soup = BeautifulSoup(xhtml, "html.parser")
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for node in soup.find_all(["script", "style"]):
        node.decompose()
    for macro in soup.find_all("ac:structured-macro"):
        name = macro.get("ac:name", "")
        body = macro.find("ac:plain-text-body" if name == "code" else "ac:rich-text-body")
        if name == "code" and body is not None:
            replacement = soup.new_tag("pre")
            replacement.string = body.get_text()
            macro.replace_with(replacement)
        elif name in {"info", "note", "warning", "tip", "panel", "expand"} and body is not None:
            macro.replace_with(body)
        else:
            macro.decompose()
    blocks: list[ContentBlock] = []
    headings: list[tuple[int, str]] = []

    def emit(kind: str, text: str) -> None:
        cleaned = text.strip() if kind == "code" else _compact(text)
        if cleaned:
            blocks.append(ContentBlock(kind, cleaned, tuple(title for _, title in headings)))

    def visit(node: Tag | NavigableString) -> None:
        if isinstance(node, NavigableString):
            emit("paragraph", str(node))
            return
        if re.fullmatch(r"h[1-6]", node.name or ""):
            level = int(node.name[1])
            title = _compact(_inline(node))
            while headings and headings[-1][0] >= level:
                headings.pop()
            if title:
                headings.append((level, title))
                emit("heading", title)
        elif node.name in {"pre", "ac:plain-text-body"}:
            emit("code", node.get_text().replace("\r\n", "\n").replace("\r", "\n"))
        elif node.name == "table":
            rows = node.find_all("tr")
            headers = [_compact(_inline(cell)) for cell in rows[0].find_all("th")] if rows else []
            for row in rows:
                cells = [_compact(_inline(cell)) for cell in row.find_all(["td", "th"], recursive=False)]
                if cells:
                    text = " | ".join(
                        f"{headers[index]}: {cell}" if headers and index < len(headers) else cell
                        for index, cell in enumerate(cells)
                    )
                    emit("table", text)
        elif node.name in {"ul", "ol"}:
            for index, item in enumerate(node.find_all("li", recursive=False), 1):
                children = [child for child in item.children if getattr(child, "name", None) not in {"ul", "ol"}]
                text = "".join(_inline(child) for child in children if isinstance(child, (Tag, NavigableString)))
                emit("list", f"{index}. {text}" if node.name == "ol" else f"- {text}")
                for nested in item.find_all(["ul", "ol"], recursive=False):
                    visit(nested)
        elif node.name == "p":
            emit("paragraph", _inline(node))
        else:
            for child in node.children:
                if isinstance(child, (Tag, NavigableString)):
                    visit(child)

    visit(soup)
    return NormalizedDocument(tuple(blocks), normalized_text(tuple(blocks)))


def _split_block(text: str, limit: int) -> list[str]:
    pieces = []
    while len(text) > limit:
        boundary = max(text.rfind("\n", 0, limit + 1), text.rfind(" ", 0, limit + 1))
        boundary = boundary if boundary >= limit // 2 else limit
        pieces.append(text[:boundary].rstrip())
        text = text[boundary:].lstrip()
    if text:
        pieces.append(text)
    return pieces


def chunk_document(
    document: NormalizedDocument,
    title: str,
    *,
    max_chars: int = 2400,
    max_tokens: int = 800,
    overlap_chars: int = 200,
    max_chunks: int = 1000,
) -> tuple[DocumentChunk, ...]:
    """Bound embedding text including its title and heading prefix."""
    if min(max_chars, max_tokens, max_chunks) <= 0 or not 0 <= overlap_chars < max_chars:
        raise ValueError("Invalid chunk bounds")
    chunks: list[DocumentChunk] = []
    pending = ""
    pending_path: tuple[str, ...] = ()

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        lexical = "\n".join((title, *pending_path, pending))
        chunks.append(
            DocumentChunk(
                len(chunks), pending_path, pending, stable_hash(lexical), math.ceil(len(lexical) / 3), lexical
            )
        )
        if len(chunks) > max_chunks:
            raise ConfluenceLimitError("Document chunk limit exceeded")
        pending = ""

    for block in document.blocks or (ContentBlock("paragraph", title or "Untitled"),):
        prefix = "\n".join((title, *block.heading_path)) + "\n"
        capacity = min(max_chars, max_tokens * 3) - len(prefix)
        if capacity <= 0:
            raise ConfluenceLimitError("Title and headings exceed chunk budget")
        if pending_path != block.heading_path or block.kind in {"heading", "code", "table"}:
            flush()
        pending_path = block.heading_path
        overlap = min(overlap_chars, capacity // 4) if block.kind == "paragraph" else 0
        split_limit = max(1, capacity - overlap - (2 if overlap else 0))
        for piece in _split_block(block.text, split_limit):
            if pending and len(pending) + 2 + len(piece) > capacity:
                previous = pending
                flush()
                if block.kind == "paragraph":
                    carry = min(overlap, max(0, capacity - len(piece) - 2))
                    pending = previous[-carry:] if carry else ""
            pending = f"{pending}\n\n{piece}" if pending else piece
            if block.kind in {"code", "table"}:
                flush()
    flush()
    return tuple(chunks)


class ConfluenceClient:
    """Client ownership remains with the caller; redirects are never followed."""

    def __init__(
        self,
        connection: Any,
        client: httpx.AsyncClient,
        *,
        concurrency: int = 6,
        retries: int = 3,
        max_pages: int = 10000,
        max_body_chars: int = 2_000_000,
        max_retry_delay: float = 60,
        timeout_sec: float = 30,
        heartbeat: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        base = urlsplit(connection.base_url.rstrip("/"))
        try:
            loopback = ip_address(base.hostname or "").is_loopback
        except ValueError:
            loopback = (base.hostname or "").lower() == "localhost"
        if (
            (base.scheme != "https" and not (base.scheme == "http" and loopback))
            or not base.hostname
            or base.username
            or base.password
            or base.query
            or base.fragment
        ):
            raise ValueError("Confluence requires an HTTPS origin without credentials")
        if base.path.rstrip("/") not in {"", "/wiki"}:
            raise ValueError("Confluence Cloud base URL must use /wiki")
        if connection.auth_type != "basic" or not connection.username:
            raise ValueError("Confluence requires basic authentication and a username")
        if (
            min(concurrency, max_pages, max_body_chars, timeout_sec) <= 0
            or retries < 0
            or max_retry_delay < 0
            or not math.isfinite(timeout_sec)
            or not math.isfinite(max_retry_delay)
        ):
            raise ValueError("Invalid Confluence bounds")
        self.base_url = f"{base.scheme}://{base.netloc}/wiki"
        self.client = client
        self.auth = httpx.BasicAuth(connection.username, connection.token)
        self.headers = {"Accept": "application/json"}
        self.semaphore = asyncio.Semaphore(concurrency)
        self.concurrency = concurrency
        self.retries = retries
        self.max_pages = max_pages
        self.max_body_chars = max_body_chars
        self.max_retry_delay = max_retry_delay
        self.timeout_sec = timeout_sec
        self.request_count = 0
        self.heartbeat = heartbeat

    def _url(self, link: str, expected_path: str, *, current_url: str | None = None) -> str:
        try:
            url = urljoin(current_url or self.base_url + "/", link)
            parsed, origin = urlsplit(url), urlsplit(self.base_url)
            same_origin = (
                parsed.scheme,
                parsed.hostname,
                parsed.port or (443 if parsed.scheme == "https" else 80),
            ) == (
                origin.scheme,
                origin.hostname,
                origin.port or (443 if origin.scheme == "https" else 80),
            )
        except ValueError:
            raise ConfluenceSecurityError("Rejected malformed Confluence pagination link") from None
        if (
            not same_origin
            or parsed.username
            or parsed.password
            or parsed.fragment
            or unquote(parsed.path) != expected_path
            or parsed.path != expected_path
        ):
            raise ConfluenceSecurityError("Rejected unsafe Confluence pagination link")
        return url

    async def _get(self, url: str, *, root: bool = False) -> dict[str, Any] | None:
        for attempt in range(self.retries + 1):
            if self.heartbeat:
                await self.heartbeat()
            try:
                async with self.semaphore:
                    self.request_count += 1
                    response = await self.client.get(
                        url,
                        auth=self.auth,
                        headers=self.headers,
                        follow_redirects=False,
                        timeout=self.timeout_sec,
                    )
            except httpx.TransportError:
                if attempt == self.retries:
                    raise ConfluenceError("Confluence transport failed") from None
                await asyncio.sleep(min(self.max_retry_delay, 2**attempt + secrets.randbelow(1000) / 1000))
                continue
            code = response.status_code
            if code == 401 or (root and code in {403, 404}):
                raise ConfluenceSecurityError("Confluence credentials or configured root access revoked")
            if code in {403, 404}:
                return None
            if code == 429 or code >= 500:
                if attempt == self.retries:
                    raise ConfluenceError(f"Confluence unavailable (HTTP {code})")
                delay = 2**attempt + secrets.randbelow(1000) / 1000
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        with suppress(ValueError, TypeError, OverflowError):
                            delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                if not math.isfinite(delay) or delay > self.max_retry_delay:
                    raise ConfluenceError("Confluence retry delay exceeds bound")
                await asyncio.sleep(max(0, delay))
                continue
            if code != 200:
                raise ConfluenceError(f"Confluence request failed (HTTP {code})")
            if len(response.content) > self.max_body_chars * 4:
                raise ConfluenceLimitError("Confluence response exceeds limit")
            try:
                result = response.json()
                if not isinstance(result, dict):
                    raise ValueError
                return result
            except ValueError:
                raise ConfluenceError("Malformed Confluence response") from None
        raise ConfluenceError("Confluence retry exhausted")

    async def discover(self, root_page_ids: list[str], *, include_descendants: bool = True) -> SourceSnapshot:
        if not isinstance(root_page_ids, (list, tuple)) or type(include_descendants) is not bool:
            raise ValueError("Confluence roots and descendant policy are invalid")
        roots = sorted({str(value) for value in root_page_ids})
        if not roots or any(not re.fullmatch(r"[0-9]+", value) for value in roots):
            raise ValueError("Confluence roots must be numeric page IDs")
        if len(roots) > self.max_pages:
            raise ConfluenceLimitError("Confluence root limit exceeded")
        items: dict[str, dict[str, Any]] = {}
        owners: dict[str, str] = {}
        metadata: dict[str, dict[str, Any]] = {}
        skipped = 0
        warnings: list[str] = []
        for root_id in roots:
            root = await self._get(f"{self.base_url}/api/v2/pages/{root_id}", root=True)
            if root is None or root.get("status", "current") != "current":
                raise ConfluenceSecurityError("Configured Confluence root is not current")
            metadata[root_id] = root
            items[root_id] = {**root, "type": "page"}
            owners[root_id] = root_id
            if not include_descendants:
                continue
            endpoint = f"/wiki/api/v2/pages/{root_id}/descendants"
            url: str | None = f"{self.base_url}/api/v2/pages/{root_id}/descendants?limit=100"
            visited: set[str] = set()
            while url:
                url = self._url(url, endpoint)
                if url in visited or len(visited) >= self.max_pages:
                    raise ConfluenceLimitError("Confluence pagination cycle or limit exceeded")
                visited.add(url)
                response = await self._get(url, root=True)
                if response is None or not isinstance(response.get("results"), list):
                    raise ConfluenceError("Malformed Confluence descendants")
                for item in response["results"]:
                    if not isinstance(item, dict) or not re.fullmatch(r"[0-9]+", str(item.get("id", ""))):
                        raise ConfluenceError("Malformed Confluence descendant ID")
                    page_id = str(item["id"])
                    existing = items.get(page_id)
                    if existing is None or (
                        item.get("type") == "page"
                        and existing.get("type") != "page"
                        and item.get("status", "current") == "current"
                    ):
                        items[page_id] = item
                    owners.setdefault(page_id, root_id)
                    if len(items) > self.max_pages:
                        raise ConfluenceLimitError("Confluence discovery limit exceeded")
                next_link = response.get("_links", {}).get("next")
                if next_link is not None and not isinstance(next_link, str):
                    raise ConfluenceError("Malformed Confluence pagination link")
                url = (
                    self._url(next_link, endpoint, current_url=url)
                    if isinstance(next_link, str) and next_link
                    else None
                )
        if len(items) > self.max_pages:
            raise ConfluenceLimitError("Confluence discovery limit exceeded")
        page_ids = []
        for page_id, item in items.items():
            if item.get("type") == "page" and item.get("status", "current") == "current":
                page_ids.append(page_id)
            else:
                skipped += 1
        if skipped:
            warnings.append(f"Skipped {skipped} non-current or unsupported descendants")

        async def fetch(page_id: str) -> tuple[str, dict[str, Any] | None]:
            return page_id, await self._get(f"{self.base_url}/api/v2/pages/{page_id}", root=page_id in roots)

        for offset in range(0, len(page_ids), self.concurrency):
            batch = [page_id for page_id in page_ids[offset : offset + self.concurrency] if page_id not in metadata]
            for page_id, page in await asyncio.gather(*(fetch(page_id) for page_id in batch)):
                if page is None or page.get("status", "current") != "current":
                    if len(warnings) < 100:
                        warnings.append(f"Omitted inaccessible page {page_id}")
                    continue
                metadata[page_id] = page
        pages = []
        for page_id in sorted(metadata):
            page = metadata[page_id]
            if str(page.get("id")) != page_id or not page.get("version", {}).get("number"):
                raise ConfluenceError("Malformed Confluence page metadata")
            ancestors = []
            seen = {page_id}
            parent_id = page.get("parentId", items[page_id].get("parentId"))
            current = str(parent_id) if parent_id is not None else None
            while current in items and current not in seen:
                seen.add(current)
                parent = metadata.get(current, items[current])
                ancestors.append(str(parent.get("title", current)))
                parent_id_next = parent.get("parentId")
                current = str(parent_id_next) if parent_id_next is not None else None
            if current in seen:
                raise ConfluenceError("Confluence hierarchy cycle")
            webui = page.get("_links", {}).get("webui")
            if webui and isinstance(webui, str):
                if webui.startswith("/spaces/") or webui.startswith("/pages/"):
                    webui = "/wiki" + webui
                canonical = urljoin(self.base_url + "/", webui)
            else:
                canonical = f"{self.base_url}/pages/{page_id}"
            if (
                urlsplit(canonical).netloc != urlsplit(self.base_url).netloc
                or urlsplit(canonical).scheme != urlsplit(self.base_url).scheme
            ):
                raise ConfluenceSecurityError("Rejected unsafe Confluence canonical URL")
            pages.append(
                PageMetadata(
                    page_id,
                    str(page["version"]["number"]),
                    str(page.get("title", "")),
                    canonical,
                    tuple(reversed(ancestors)),
                    owners[page_id],
                    str(parent_id) if parent_id is not None else None,
                )
            )
        return SourceSnapshot(tuple(pages), tuple(warnings), skipped)

    async def fetch_body(self, page: PageMetadata) -> str | None:
        response = await self._get(
            f"{self.base_url}/api/v2/pages/{page.page_id}?body-format=storage",
            root=page.page_id == page.root_page_id,
        )
        if response is None:
            return None
        if response.get("status", "current") != "current":
            if page.page_id == page.root_page_id:
                raise ConfluenceSecurityError("Configured Confluence root is no longer current")
            return None
        if (
            str(response.get("id")) != page.page_id
            or str(response.get("version", {}).get("number")) != page.provider_revision
        ):
            raise ConfluenceError("Confluence page changed during snapshot build; retry sync")
        body = response.get("body", {}).get("storage", {}).get("value")
        if not isinstance(body, str):
            raise ConfluenceError("Missing Confluence storage body")
        if len(body) > self.max_body_chars:
            raise ConfluenceLimitError("Confluence body exceeds limit")
        return body
