"""Controlled Knowledge MCP backed only by checksum-verified local bundles."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from pathlib import Path
from typing import Annotated, Any

from fastmcp import FastMCP
from fastmcp.dependencies import CurrentHeaders
from fastmcp.server.lifespan import lifespan

from mcps.common import bootstrap_platform_env
from shared.lib.config import settings
from shared.lib.db import async_session_factory, ensure_runtime_schema
from shared.lib.knowledge_source_serving import KnowledgeSourceServingRegistry
from shared.lib.knowledge_source_serving import explain_node as explain_local_node
from shared.lib.knowledge_source_serving import find_paths as find_local_paths
from shared.lib.knowledge_source_serving import get_graph_overview as get_local_graph_overview
from shared.lib.knowledge_source_serving import get_neighbors as get_local_neighbors
from shared.lib.knowledge_source_serving import get_source_excerpt as get_local_source_excerpt
from shared.lib.knowledge_source_serving import get_symbol as get_local_symbol
from shared.lib.knowledge_source_serving import query_graph as query_local_graph
from shared.lib.knowledge_source_serving import search_source as search_local_source
from shared.lib.knowledge_source_serving import search_symbols as search_local_symbols
from shared.lib.knowledge_source_serving import shortest_path as find_local_shortest_path
from shared.lib.task_call_budget import TaskCallBudget

bootstrap_platform_env()
logger = logging.getLogger(__name__)


def _registry_from_settings() -> KnowledgeSourceServingRegistry:
    return KnowledgeSourceServingRegistry(
        cache_root=Path(settings.knowledge_source_serving_cache_root),
        bucket=settings.knowledge_source_object_store_bucket,
        versions_to_keep=int(settings.knowledge_source_cache_versions_to_keep),
    )


registry = _registry_from_settings()
ONLINE_ALERTS_WORKFLOW = "online-alerts-investigator"
ONLINE_ALERTS_KNOWLEDGE_CALL_LIMIT = 20
MAX_TRACKED_TASK_BUDGETS = 10_000


task_call_budget = TaskCallBudget(
    limit=ONLINE_ALERTS_KNOWLEDGE_CALL_LIMIT,
    max_tasks=MAX_TRACKED_TASK_BUDGETS,
    resource_name="Knowledge MCP",
    exhausted_instruction="Return not_grounded with the evidence already collected; do not retry.",
)


async def _refresh_once() -> None:
    async with async_session_factory() as session:
        await registry.refresh(session)


async def _refresh_loop() -> None:
    interval = int(settings.knowledge_source_refresh_interval_sec)
    if interval <= 0:
        raise ValueError("KNOWLEDGE_SOURCE_REFRESH_INTERVAL_SEC must be positive")
    while True:
        await asyncio.sleep(interval)
        try:
            await _refresh_once()
        except Exception:
            logger.exception("Knowledge Source cache refresh failed")


@lifespan
async def knowledge_lifespan(_server):
    await ensure_runtime_schema()
    await _refresh_once()
    refresh_task = asyncio.create_task(_refresh_loop())
    try:
        yield {"knowledge_registry": registry}
    finally:
        refresh_task.cancel()
        with suppress(asyncio.CancelledError):
            await refresh_task


mcp = FastMCP("Controlled Knowledge MCP", lifespan=knowledge_lifespan)


def _workflow(headers: dict[str, str]) -> str:
    workflow = headers.get("x-task-workflow", "").strip().lower()
    if not workflow:
        raise PermissionError("Knowledge Source tools require x-task-workflow")
    return workflow


def _authorized_workflow(headers: dict[str, str]) -> str:
    workflow = _workflow(headers)
    task_id = headers.get("x-task-id", "").strip()
    if workflow == ONLINE_ALERTS_WORKFLOW and task_id:
        task_call_budget.consume(task_id)
    return workflow


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def list_sources(headers: dict[str, str] = CurrentHeaders()) -> list[dict[str, Any]]:
    """List locally ready Knowledge Sources authorized for the current workflow."""
    return registry.list_sources(_authorized_workflow(headers))


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def query_graph(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    question: Annotated[
        str,
        "Natural-language code question grounded in provider evidence. The service ranks Graphify nodes and "
        "returns a bounded BFS or DFS graph traversal; it never scans source files as a fallback.",
    ],
    headers: dict[str, str] = CurrentHeaders(),
    mode: Annotated[str, "bfs for local context or dfs for a specific dependency chain."] = "bfs",
    depth: Annotated[int, "Traversal depth, from 1 through 6."] = 3,
    token_budget: Annotated[int, "Approximate maximum output tokens, from 200 through 5000."] = 2000,
    context_filters: Annotated[
        list[str] | None,
        "Optional Graphify relationship filters such as call, import, inherit, or reference.",
    ] = None,
) -> dict[str, Any]:
    """Run Graphify's ranked query and traversal against one commit-pinned graph."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return query_local_graph(
            snapshot,
            question,
            mode=mode,
            depth=depth,
            token_budget=token_budget,
            context_filters=context_filters,
        )


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def explain_node(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    concept: Annotated[
        str,
        "Graphify node ID, repository-relative path, or precise symbol label returned by query_graph.",
    ],
    headers: dict[str, str] = CurrentHeaders(),
    limit: Annotated[int, "Maximum connected nodes to return, from 1 through 50."] = 20,
) -> dict[str, Any]:
    """Resolve and explain one Graphify concept, including ambiguity and its strongest connections."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return explain_local_node(snapshot, concept, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def shortest_path(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    source_concept: Annotated[str, "Precise starting symbol label, path, or Graphify node ID."],
    target_concept: Annotated[str, "Precise target symbol label, path, or Graphify node ID."],
    headers: dict[str, str] = CurrentHeaders(),
    max_hops: Annotated[int, "Maximum path length, from 1 through 12."] = 8,
    undirected: Annotated[
        bool,
        "False follows stored caller-to-callee direction; true is a deliberate fallback that ignores direction.",
    ] = False,
) -> dict[str, Any]:
    """Resolve two concepts and return Graphify's deterministic shortest relationship path."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return find_local_shortest_path(
            snapshot,
            source_concept,
            target_concept,
            max_hops=max_hops,
            undirected=undirected,
        )


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_graph_overview(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    headers: dict[str, str] = CurrentHeaders(),
    limit: Annotated[int, "Maximum high-degree graph nodes to return, from 1 through 20."] = 10,
) -> dict[str, Any]:
    """Get commit-pinned graph size and high-degree nodes for broad source orientation."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return get_local_graph_overview(snapshot, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def search_symbols(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    query: Annotated[
        str,
        "One exact symbol, filename, code identifier, or literal log substring. Matching is case-insensitive "
        "literal substring search, not semantic or tokenized search; use one anchor per call.",
    ],
    headers: dict[str, str] = CurrentHeaders(),
    limit: Annotated[int, "Maximum results, from 1 through 50."] = 20,
) -> list[dict[str, Any]]:
    """Use exact graph lookup only when query_graph misses a provider-known identifier."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return search_local_symbols(snapshot, query, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def search_source(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    query: Annotated[
        str,
        "One literal source substring from verified evidence, matched case-insensitively. Do not combine unrelated "
        "terms or use an alert title as a semantic query.",
    ],
    headers: dict[str, str] = CurrentHeaders(),
    limit: Annotated[int, "Maximum matching source lines, from 1 through 50."] = 20,
) -> dict[str, Any]:
    """Use literal source lookup only for a provider-known exact string after graph retrieval misses."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return search_local_source(snapshot, query, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_symbol(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    symbol_id: Annotated[str, "Exact Graphify symbol ID returned by query_graph, explain_node, or search_symbols."],
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Get one symbol with repository, commit, and source provenance."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return get_local_symbol(snapshot, symbol_id)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_neighbors(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    symbol_id: Annotated[str, "Exact Graphify symbol ID."],
    headers: dict[str, str] = CurrentHeaders(),
    direction: Annotated[str, "incoming, outgoing, or both."] = "both",
    limit: Annotated[int, "Maximum results, from 1 through 100."] = 50,
) -> dict[str, Any]:
    """Get bounded graph neighbors from one locally pinned source version."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return get_local_neighbors(snapshot, symbol_id, direction=direction, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def find_paths(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    from_symbol_id: Annotated[str, "Exact starting Graphify symbol ID."],
    to_symbol_id: Annotated[str, "Exact target Graphify symbol ID."],
    headers: dict[str, str] = CurrentHeaders(),
    max_depth: Annotated[int, "Maximum directed path depth, from 1 through 12."] = 6,
    limit: Annotated[int, "Maximum paths, from 1 through 20."] = 10,
) -> list[list[dict[str, Any]]]:
    """Find bounded directed paths in one locally pinned source graph."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return find_local_paths(snapshot, from_symbol_id, to_symbol_id, max_depth=max_depth, limit=limit)


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def get_source_excerpt(
    source_alias: Annotated[str, "Approved canonical Knowledge Source alias."],
    source_file: Annotated[str, "Repository-relative source path returned by a symbol lookup."],
    start_line: Annotated[int, "One-based first line."],
    end_line: Annotated[int, "One-based final line, at most 200 lines after start_line."],
    headers: dict[str, str] = CurrentHeaders(),
) -> dict[str, Any]:
    """Read a bounded excerpt from one authorized immutable source snapshot."""
    with registry.pin(source_alias, _authorized_workflow(headers)) as snapshot:
        return get_local_source_excerpt(snapshot, source_file, start_line=start_line, end_line=end_line)


app = mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=False)
