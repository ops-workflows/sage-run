"""Local-only Knowledge Source serving tests."""

from __future__ import annotations

import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

import shared.lib.knowledge_source_serving as knowledge_serving
from shared.lib.knowledge_source_serving import (
    KnowledgeSourceAccessError,
    KnowledgeSourceServingRegistry,
    ServingSnapshot,
    explain_node,
    find_paths,
    get_graph_overview,
    get_neighbors,
    get_source_excerpt,
    query_graph,
    search_source,
    search_symbols,
    shortest_path,
)

pytestmark = pytest.mark.unit


def _snapshot(tmp_path: Path) -> ServingSnapshot:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "app.py").write_text("def main():\n    return helper()\n", encoding="utf-8")
    return ServingSnapshot(
        source_id=uuid.uuid4(),
        version_id=uuid.uuid4(),
        canonical_alias="org/example",
        commit_sha="a" * 40,
        graph={
            "nodes": [
                {"id": "function:main", "name": "main", "source_file": "app.py", "line": 1},
                {"id": "function:helper", "name": "helper", "source_file": "app.py", "line": 2},
            ],
            "links": [{"source": "function:main", "target": "function:helper", "relation": "CALLS"}],
            "hyperedges": [],
        },
        source_root=source_root,
    )


def test_local_graph_queries_return_commit_and_path_provenance(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    (snapshot.source_root / "errors.txt").write_text(
        "Total prices in request doesn't match calculated prices\n",
        encoding="utf-8",
    )

    matches = search_symbols(snapshot, "main")
    source_matches = search_source(snapshot, "TOTAL PRICES IN REQUEST")
    neighbors = get_neighbors(snapshot, "function:main", direction="outgoing")
    paths = find_paths(snapshot, "function:main", "function:helper")
    excerpt = get_source_excerpt(snapshot, "app.py", start_line=1, end_line=2)

    assert matches[0]["commit_sha"] == "a" * 40
    assert source_matches == {
        "source": "org/example",
        "commit_sha": "a" * 40,
        "query": "TOTAL PRICES IN REQUEST",
        "matches": [
            {
                "path": "errors.txt",
                "line": 1,
                "column": 1,
                "preview": "Total prices in request doesn't match calculated prices",
            }
        ],
        "count": 1,
        "truncated": False,
    }
    assert neighbors["neighbors"][0]["symbol"]["id"] == "function:helper"
    assert [item["id"] for item in paths[0]] == ["function:main", "function:helper"]
    assert excerpt["path"] == "app.py"
    assert "return helper()" in excerpt["content"]


def test_source_search_is_literal_bounded_and_skips_generated_content(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)
    (snapshot.source_root / "first.txt").write_text("needle one\nneedle two\n", encoding="utf-8")
    generated = snapshot.source_root / "node_modules" / "package"
    generated.mkdir(parents=True)
    (generated / "index.js").write_text("needle generated\n", encoding="utf-8")

    result = search_source(snapshot, "needle", limit=1)

    assert result["count"] == 1
    assert result["truncated"] is True
    assert result["matches"][0]["path"] == "first.txt"
    with pytest.raises(ValueError, match="one line"):
        search_source(snapshot, "needle\nsecond line")


def test_symbol_search_does_not_fall_back_to_source_scan(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    result = search_symbols(snapshot, "return helper()")

    assert result == []


def test_symbol_search_does_not_mix_graph_and_source_matches(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    result = search_symbols(snapshot, "main")

    assert [match["id"] for match in result] == ["function:main"]
    assert all("result_type" not in match for match in result)


def test_query_graph_ranks_and_traverses_commit_pinned_graph(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    result = query_graph(snapshot, "How does main call helper?", mode="bfs", depth=1, token_budget=1000)

    assert result["status"] == "matched"
    assert result["source"] == "org/example"
    assert result["commit_sha"] == "a" * 40
    assert result["query_terms"] == ["main", "call", "helper"]
    assert "Traversal: BFS depth=1" in result["context"]
    assert "Start: ['main', 'helper']" in result["context"]
    assert "NODE main [src=app.py" in result["context"]
    assert "NODE helper [src=app.py" in result["context"]

    main_result = query_graph(snapshot, "main", mode="bfs", depth=1, token_budget=1000)
    assert "Start: ['main']" in main_result["context"]
    assert "NODE main [src=app.py" in main_result["context"]
    assert "NODE helper [src=app.py" in main_result["context"]


def test_explain_node_uses_graphify_resolution_and_returns_provenance(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    result = explain_node(snapshot, "main")

    assert result["status"] == "resolved"
    assert result["source"] == "org/example"
    assert result["commit_sha"] == "a" * 40
    assert result["node"]["id"] == "function:main"
    assert result["connections"][0]["direction"] == "outgoing"
    assert result["connections"][0]["symbol"]["id"] == "function:helper"


def test_shortest_path_uses_graphify_resolution_and_edge_direction(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    result = shortest_path(snapshot, "main", "helper")
    reverse = shortest_path(snapshot, "helper", "main")

    assert result["status"] == "resolved"
    assert result["source"] == "org/example"
    assert result["commit_sha"] == "a" * 40
    assert "Shortest path (1 hops)" in result["context"]
    assert "main --CALLS--> helper" in result["context"]
    assert reverse["status"] == "not_connected"
    assert "No directed path" in reverse["context"]


def test_graph_overview_returns_commit_pinned_hubs(tmp_path: Path) -> None:
    snapshot = _snapshot(tmp_path)

    overview = get_graph_overview(snapshot)

    assert overview["source"] == "org/example"
    assert overview["commit_sha"] == "a" * 40
    assert overview["node_count"] == 2
    assert overview["link_count"] == 1
    assert [(node["id"], node["degree"]) for node in overview["hub_nodes"]] == [
        ("function:helper", 1),
        ("function:main", 1),
    ]


def test_query_graph_never_falls_back_to_source_search(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(tmp_path)

    def _unexpected_source_search(*args, **kwargs):
        raise AssertionError("query_graph must not inspect raw source files")

    monkeypatch.setattr(knowledge_serving, "search_source", _unexpected_source_search)

    result = query_graph(snapshot, "main", mode="bfs", depth=1, token_budget=1000)

    assert result["status"] == "matched"
    assert "NODE main [src=app.py" in result["context"]


def test_registry_authorizes_and_pins_workflow_with_knowledge_mcp(tmp_path: Path, monkeypatch) -> None:
    snapshot = _snapshot(tmp_path)
    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="knowledge")
    registry._by_alias[snapshot.canonical_alias] = snapshot
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    monkeypatch.setattr(
        knowledge_serving,
        "discover_workflow_packages",
        lambda: [SimpleNamespace(name="example-workflow", path=tmp_path, config={})],
    )

    with registry.pin("org/example", "example-workflow") as pinned:
        assert pinned.version_id == snapshot.version_id
        assert registry._pins[(snapshot.source_id, snapshot.version_id)] == 1
    assert registry._pins == {}

    with pytest.raises(KnowledgeSourceAccessError), registry.pin("org/example", "other-workflow"):
        pass


def test_workflow_access_requires_knowledge_mcp_declaration(tmp_path: Path, monkeypatch) -> None:
    workflow_dir = tmp_path / "investigator"
    workflow_dir.mkdir()
    (workflow_dir / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    monkeypatch.setattr(
        "shared.lib.knowledge_source_serving.discover_workflow_packages",
        lambda: [SimpleNamespace(name="investigator", path=workflow_dir, config={})],
    )

    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="knowledge")
    assert registry.grants("investigator").allows("wiki")
    assert not registry.grants("other-workflow").allows("wiki")
    (workflow_dir / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    assert not registry.grants("investigator").allows("wiki")


def test_registry_grants_filter_listing_and_pin(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path)
    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="knowledge")
    registry._by_alias[snapshot.canonical_alias] = snapshot
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    package = SimpleNamespace(name="example", path=tmp_path, config={"knowledge": {"sources": []}})
    monkeypatch.setattr(knowledge_serving, "discover_workflow_packages", lambda: [package])
    assert registry.list_sources("example") == []
    with pytest.raises(KnowledgeSourceAccessError), registry.pin(snapshot.canonical_alias, "example"):
        pass
    package.config["knowledge"]["sources"] = [snapshot.canonical_alias]
    assert registry.list_sources("example")[0]["alias"] == snapshot.canonical_alias
    with registry.pin(snapshot.canonical_alias, "example") as pinned:
        assert pinned == snapshot


@pytest.mark.asyncio
async def test_refresh_filters_graph_state_and_evicts_revoked_snapshot(tmp_path, monkeypatch):
    snapshot = _snapshot(tmp_path)
    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="knowledge")
    registry._by_alias[snapshot.canonical_alias] = snapshot
    statements = []

    async def execute(statement):
        statements.append(str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
        return SimpleNamespace(all=lambda: [])

    await registry.refresh(SimpleNamespace(execute=execute))
    assert registry._by_alias == {}
    assert "serving_suspended_at IS NULL" in statements[0]
    assert "source_kind = 'github'" in statements[0]
    assert "knowledge_source_versions.index_kind = 'code_graph'" in statements[0]
    assert "knowledge_sources.enabled IS true" in statements[0]
    assert "knowledge_source_versions.status = 'succeeded'" in statements[0]


@pytest.mark.asyncio
async def test_catalog_metadata_is_redacted_authorized_and_stateful(tmp_path, monkeypatch):
    from shared.lib.knowledge_source_serving import KnowledgeSourceCatalog

    registry = KnowledgeSourceServingRegistry(cache_root=tmp_path / "cache", bucket="knowledge")
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    package = SimpleNamespace(name="example", path=tmp_path, config={"knowledge": {"sources": ["wiki"]}})
    monkeypatch.setattr(knowledge_serving, "discover_workflow_packages", lambda: [package])
    source = SimpleNamespace(
        canonical_alias="wiki",
        display_name="Runbooks",
        source_kind="confluence",
        index_kind="hybrid_vector",
        enabled=True,
        serving_suspended_at=None,
        source_config={"description": "Operations", "token": "secret"},
    )
    version = SimpleNamespace(
        id=uuid.uuid4(),
        status="succeeded",
        index_kind="hybrid_vector",
        source_revision="revision",
        commit_sha=None,
        finished_at=None,
    )

    async def execute(statement):
        return SimpleNamespace(all=lambda: [(source, version)])

    catalog = KnowledgeSourceCatalog(registry)
    session = SimpleNamespace(execute=execute)
    listed = await catalog.list_sources(session, "example")
    assert listed[0]["capabilities"] == ["hybrid_search"]
    assert listed[0]["status"] == "ready"
    assert "secret" not in str(listed)
    source.serving_suspended_at = "revoked"
    assert (await catalog.list_sources(session, "example"))[0]["status"] == "suspended"
    source.serving_suspended_at = None
    source.enabled = False
    assert (await catalog.list_sources(session, "example"))[0]["status"] == "disabled"
    package.config["knowledge"]["sources"] = []
    assert await catalog.list_sources(session, "example") == []
