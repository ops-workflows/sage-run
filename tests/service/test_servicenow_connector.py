"""PostgreSQL transaction coverage for ServiceNow connector receipts."""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import psycopg
import pytest
import pytest_asyncio
from psycopg import sql
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

pytestmark = pytest.mark.service
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest_asyncio.fixture
async def connector_db(require_database, monkeypatch):
    from shared.lib import db

    url = make_url(require_database)
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+asyncpg")
    admin_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    database_name = f"sage_servicenow_test_{uuid4().hex}"
    test_url = url.set(database=database_name)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    engine = create_async_engine(test_url)
    try:
        bootstrap = (REPO_ROOT / "shared/lib/init_db.sql").read_text().split("CREATE TABLE control_plane.sessions")[0]
        bootstrap = bootstrap.replace("CREATE EXTENSION IF NOT EXISTS vector;\n", "")
        with psycopg.connect(test_url.set(drivername="postgresql").render_as_string(hide_password=False)) as connection:
            connection.execute(bootstrap, prepare=False)
        monkeypatch.setattr(db, "async_session_factory", async_sessionmaker(engine, expire_on_commit=False))
        yield engine
    finally:
        await engine.dispose()
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


def _connector():
    spec = importlib.util.spec_from_file_location(
        "servicenow_connector_service_test", REPO_ROOT / "connectors/servicenow-connector/main.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_receipt_and_task_are_atomic_and_survive_restart(connector_db, monkeypatch):
    from shared.lib import task_queue

    connector = _connector()
    config = {
        "_instance_id": "intake",
        "target": {"workflow": "triage", "prompt_template": "Handle {number}"},
    }
    parsed = {"number": "INC001"}
    key = connector._source_key("https://example.invalid", "incident", "triage")
    monkeypatch.setattr(task_queue, "_workflow_default_message_channel", AsyncMock(return_value=""))
    real_submit = task_queue.submit_task
    monkeypatch.setattr(task_queue, "submit_task", AsyncMock(side_effect=RuntimeError("submission failed")))

    with pytest.raises(RuntimeError, match="submission failed"):
        await connector._create_task_from_record(parsed, config, key, "record-1")
    async with connector_db.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM control_plane.servicenow_connector_records")) == 0
        assert await connection.scalar(text("SELECT count(*) FROM task_queue.tasks")) == 0

    monkeypatch.setattr(task_queue, "submit_task", real_submit)
    results = await asyncio.gather(
        connector._create_task_from_record(parsed, config, key, "record-1"),
        connector._create_task_from_record(parsed, config, key, "record-1"),
    )
    assert sorted(results) == [False, True]
    assert not await _connector()._create_task_from_record(parsed, config, key, "record-1")
    assert await connector._create_task_from_record(parsed, {**config, "_instance_id": "other"}, key, "record-1")
    async with connector_db.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM control_plane.servicenow_connector_records")) == 2
        assert await connection.scalar(text("SELECT count(*) FROM task_queue.tasks")) == 2


async def test_checkpoint_survives_restart_and_query_change_restarts_scan(connector_db):
    connector = _connector()
    await connector._save_page_offset("intake", "source", "query-1", 6)
    assert await _connector()._load_page_offset("intake", "source", "query-1") == 6
    assert await connector._load_page_offset("intake", "source", "query-2") == 0
    assert await connector._load_page_offset("other", "source", "query-1") == 0
    await connector._save_page_offset("intake", "source", "query-2", 3)
    assert await connector._load_page_offset("intake", "source", "query-2") == 3


async def test_migration_creates_tables_without_erasing_existing_progress(connector_db):
    from shared.lib.db import _ensure_servicenow_connector_schema

    async with connector_db.begin() as connection:
        await connection.execute(text("DROP TABLE control_plane.servicenow_connector_checkpoints"))
        await connection.execute(text("DROP TABLE control_plane.servicenow_connector_records"))
        await _ensure_servicenow_connector_schema(connection)
        await connection.execute(
            text("INSERT INTO control_plane.servicenow_connector_checkpoints VALUES ('intake', 'source', 'query', 6)")
        )
        await connection.execute(
            text(
                "INSERT INTO control_plane.servicenow_connector_records (connector_id, source_key, sys_id) "
                "VALUES ('intake', 'source', 'record')"
            )
        )
        await _ensure_servicenow_connector_schema(connection)
        assert (
            await connection.scalar(text("SELECT page_offset FROM control_plane.servicenow_connector_checkpoints")) == 6
        )
        assert await connection.scalar(text("SELECT count(*) FROM control_plane.servicenow_connector_records")) == 1


async def test_paged_intake_resumes_and_does_not_duplicate_tasks(connector_db, monkeypatch):
    from shared.lib import task_queue

    connector = _connector()
    records = [{"sys_id": f"id-{index:03}", "number": f"INC{index:03}"} for index in range(75)]
    offsets = []
    config = {
        "_instance_id": "intake",
        "source": {"table": "incident", "query": "active=true", "page_size": 3},
        "target": {"workflow": "triage", "prompt_template": "Handle {number}"},
        "parsing": {"extract": {"number": "number"}},
    }

    class Client:
        async def get(self, url, *, params, auth):
            offset = int(params["sysparm_offset"])
            offsets.append(offset)
            return SimpleNamespace(
                raise_for_status=lambda: None,
                json=lambda: {"result": records[offset : offset + 3]},
                headers={"X-Total-Count": str(len(records))},
            )

    monkeypatch.setattr(connector, "_connector_is_paused", AsyncMock(return_value=False))
    monkeypatch.setattr(task_queue, "_workflow_default_message_channel", AsyncMock(return_value=""))
    real_submit = task_queue.submit_task

    async def fail_on_fifth(session, **kwargs):
        if kwargs["metadata"]["number"] == "INC004":
            raise RuntimeError("interrupted")
        return await real_submit(session, **kwargs)

    monkeypatch.setattr(task_queue, "submit_task", fail_on_fifth)
    with pytest.raises(RuntimeError, match="interrupted"):
        await connector._poll_pages(Client(), config, "https://example.invalid", "user", "password")
    assert offsets == [0, 3]
    async with connector_db.connect() as connection:
        assert (
            await connection.scalar(text("SELECT page_offset FROM control_plane.servicenow_connector_checkpoints")) == 3
        )
        assert await connection.scalar(text("SELECT count(*) FROM task_queue.tasks")) == 4

    monkeypatch.setattr(task_queue, "submit_task", real_submit)
    restarted = _connector()
    monkeypatch.setattr(restarted, "_connector_is_paused", AsyncMock(return_value=False))
    offsets.clear()
    await restarted._poll_pages(Client(), config, "https://example.invalid", "user", "password")
    assert offsets == list(range(3, 75, 3))
    await restarted._poll_pages(Client(), config, "https://example.invalid", "user", "password")
    async with connector_db.connect() as connection:
        assert (
            await connection.scalar(text("SELECT page_offset FROM control_plane.servicenow_connector_checkpoints")) == 0
        )
        assert await connection.scalar(text("SELECT count(*) FROM control_plane.servicenow_connector_records")) == 75
        assert await connection.scalar(text("SELECT count(*) FROM task_queue.tasks")) == 75


async def test_coalesced_task_and_second_receipt_commit_together(connector_db, monkeypatch):
    from shared.lib import task_queue

    connector = _connector()
    monkeypatch.setattr(task_queue, "_workflow_default_message_channel", AsyncMock(return_value=""))
    config = {
        "_instance_id": "intake",
        "target": {"workflow": "triage", "prompt_template": "Handle {number}"},
        "coalescing": {"enabled": True, "key_field": "number", "window_sec": 300},
    }
    key = connector._source_key("https://example.invalid", "incident", "triage")
    assert await connector._create_task_from_record({"number": "INC001"}, config, key, "record-1")
    assert await connector._create_task_from_record({"number": "INC001"}, config, key, "record-2")
    assert not await connector._create_task_from_record({"number": "INC001"}, config, key, "record-2")
    async with connector_db.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM control_plane.servicenow_connector_records")) == 2
        assert await connection.scalar(text("SELECT count(*) FROM task_queue.tasks")) == 1
