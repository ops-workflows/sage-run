"""Source grants are exact, bounded and fail closed."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft7Validator

from shared.lib.knowledge_source_authorization import (
    source_grants,
    workflow_source_grants,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "knowledge",
    [
        None,
        [],
        "wiki",
        {"sources": None},
        {"sources": "wiki"},
        {"sources": ["*"]},
        {"sources": [" wiki"]},
        {"sources": ["wiki", "wiki"]},
        {"sources": [1]},
        {"sources": [f"wiki-{index}" for index in range(101)]},
        {"source": ["wiki"]},
    ],
)
def test_malformed_grants_deny_every_source(knowledge):
    grants = source_grants({"knowledge": knowledge})
    assert not grants.allows("wiki")
    assert not grants.compatibility_all


def test_exact_aliases_and_explicit_empty():
    grants = source_grants({"knowledge": {"sources": ["org/example", "Wiki"]}})
    assert grants.allows("org/example")
    assert grants.allows("Wiki")
    assert not grants.allows("wiki")
    assert not grants.allows("org/other")
    assert not source_grants({"knowledge": {"sources": []}}).allows("Wiki")


def test_absent_grants_compatibility_and_strict_mode(tmp_path, caplog):
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    package = SimpleNamespace(name="example", path=tmp_path, config={})
    options = {"package_loader": lambda: [package]}
    assert workflow_source_grants("example", **options).allows("wiki")
    assert "deprecated" in caplog.text
    assert not workflow_source_grants("example", require_explicit=True, **options).allows("wiki")
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{}}', encoding="utf-8")
    assert not workflow_source_grants("example", **options).allows("wiki")


def test_authorization_discovers_package_once(tmp_path):
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    package = SimpleNamespace(name="example", path=tmp_path, config={"knowledge": {"sources": ["wiki"]}})
    calls = []

    def load_packages():
        calls.append(True)
        return [package]

    assert workflow_source_grants("example", package_loader=load_packages).allows("wiki")
    assert len(calls) == 1


def test_workflow_loader_and_mcp_declaration(tmp_path):
    package = SimpleNamespace(name="example", path=tmp_path, config={"knowledge": {"sources": ["wiki"]}})
    options = {"package_loader": lambda: [package]}
    assert not workflow_source_grants("example", **options).allows("wiki")
    (tmp_path / ".mcp.json").write_text('{"mcpServers":{"knowledge":{}}}', encoding="utf-8")
    grants = workflow_source_grants("example", **options)
    assert grants.allows("wiki")
    assert not grants.allows("other")
    assert not workflow_source_grants("missing", **options).allows("wiki")
    (tmp_path / ".mcp.json").write_text("[]", encoding="utf-8")
    assert not workflow_source_grants("example", **options).allows("wiki")


@pytest.mark.parametrize("sources", [["wiki"], [], ["*"], [" wiki"], ["wiki\n"], ["wiki", "wiki"], [True]])
def test_schema_agrees_with_runtime_grants(sources):
    schema = json.loads((Path(__file__).resolve().parents[2] / "schemas" / "agent-yaml-schema.json").read_text())
    validator = Draft7Validator(schema["properties"]["knowledge"])
    valid = validator.is_valid({"sources": sources})
    assert valid is (sources in [["wiki"], []])
    assert bool(source_grants({"knowledge": {"sources": sources}}).aliases) is (valid and bool(sources))
