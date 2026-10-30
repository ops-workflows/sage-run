"""Unit tests for the starter workflow repository and custom MCP server."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import REPO_ROOT, is_read_only, load_module, tool_fn
from sage_run.validation import validate_workflow_repo

mcp_custom = load_module(
    "mcps/custom-mcp-example/mcp_custom_example.py",
    "mcp_custom_example",
    repo_root=REPO_ROOT,
)


def test_starter_repository_validates(tmp_path: Path) -> None:
    assert validate_workflow_repo(REPO_ROOT) == []


def test_example_lookup_validates_headers_and_returns_limit() -> None:
    assert is_read_only(mcp_custom.example_lookup)
    fn = tool_fn(mcp_custom.example_lookup)

    with pytest.raises(ValueError, match="Authorization header"):
        fn(query="status", headers={})

    with pytest.raises(ValueError, match="x-custom-example-base-url"):
        fn(query="status", headers={"authorization": "Bearer secret-token"})

    result = fn(
        query="node-01",
        headers={
            "authorization": "Bearer secret-token",
            "x-custom-example-base-url": "https://api.example.invalid/",
        },
    )
    assert result == {
        "base_url": "https://api.example.invalid",
        "query": "node-01",
        "limit": 10,
        "results": [],
    }
