"""Dedicated Knowledge Source worker scheduling tests."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

pytestmark = pytest.mark.unit


def _worker_module():
    path = Path(__file__).parents[2] / "knowledge-indexer" / "main.py"
    spec = importlib.util.spec_from_file_location("knowledge_indexer_main", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_source_schedule_requires_explicit_positive_interval() -> None:
    worker = _worker_module()
    now = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)

    assert worker.source_is_due({}, last_started_at=None, now=now) is False
    assert worker.source_is_due({"interval_sec": True}, last_started_at=None, now=now) is False
    assert worker.source_is_due({"interval_sec": 0}, last_started_at=None, now=now) is False
    assert worker.source_is_due({"interval_sec": 300}, last_started_at=None, now=now) is True
    assert (
        worker.source_is_due(
            {"interval_sec": 300},
            last_started_at=now - timedelta(seconds=299),
            now=now,
        )
        is False
    )
    assert (
        worker.source_is_due(
            {"interval_sec": 300},
            last_started_at=now - timedelta(seconds=300),
            now=now,
        )
        is True
    )


@pytest.mark.asyncio
async def test_worker_startup_does_not_require_graph_bucket(monkeypatch, tmp_path) -> None:
    worker = _worker_module()
    config = worker.KnowledgeSourceIndexerConfig(cache_root=tmp_path, object_store_bucket="")
    validate = Mock(side_effect=AssertionError("Graph validation must happen only for graph jobs"))
    monkeypatch.setattr(worker.KnowledgeSourceIndexerConfig, "from_settings", lambda: config)
    monkeypatch.setattr(worker.KnowledgeSourceIndexerConfig, "validate", validate)
    monkeypatch.setattr(worker, "ensure_runtime_schema", AsyncMock())
    reconcile = AsyncMock(return_value=[])
    monkeypatch.setattr(worker, "reconcile_worker_startup", reconcile)
    worker._shutdown.set()

    await worker.worker_loop()

    validate.assert_not_called()
    reconcile.assert_awaited_once()
