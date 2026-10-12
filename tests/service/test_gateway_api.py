"""Layer 1 — gateway HTTP APIs via ASGI transport.

Uses httpx.AsyncClient with ASGI transport to hit the gateway FastAPI app
in-process without spawning a network server.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import yaml

pytestmark = pytest.mark.service


async def _make_client(fixture_workflows_dir: Path) -> httpx.AsyncClient:
    from shared.lib.config import settings

    # Point the gateway at the synthetic test plugin tree for provisioner +
    # message routing.
    settings.workflow_repo_paths = str(fixture_workflows_dir)

    from gateway.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://gateway.test")


@pytest.mark.asyncio
async def test_health_endpoint(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["service"] == "gateway"


@pytest.mark.asyncio
async def test_task_initiator_is_generic_and_round_trips(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.post(
            "/api/tasks",
            json={
                "workflow": "platform-test",
                "prompt": "hello",
                "channel": "api",
                "initiator": "alice",
            },
        )
        assert response.status_code == 200, response.text
        task = response.json()
        assert task["initiator"] == "alice"
        assert (await client.get(f"/api/tasks/{task['id']}")).json()["initiator"] == "alice"
        listing = (await client.get("/api/tasks")).json()
        assert next(item for item in listing["items"] if item["id"] == task["id"])["initiator"] == "alice"
        response = await client.post(
            "/api/tasks",
            json={
                "workflow": "platform-test",
                "prompt": "scheduled",
                "channel": "schedule",
            },
        )
        assert response.json()["initiator"] is None


@pytest.mark.asyncio
async def test_user_info_returns_verified_identity_and_mapped_application_groups(
    async_engine, fixture_workflows_dir: Path, monkeypatch, tmp_path
) -> None:
    from shared.lib.config import settings

    config = tmp_path / "platform-config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "identity": {
                    "group_mapping": {
                        "platform-admin": ["entra-sage-run-admins"],
                        "workflow-operator": ["entra-sage-run-operators"],
                        "task-viewer": ["entra-sage-run-readers"],
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "platform_config_file", str(config))

    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get(
            "/api/user-info",
            headers={
                "X-User-Id": "alice@example.com",
                "X-User-Groups": "irrelevant-group, entra-sage-run-readers, entra-sage-run-admins",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "userId": "alice@example.com",
        "groups": ["platform-admin", "task-viewer"],
    }


@pytest.mark.asyncio
async def test_user_info_returns_empty_groups_when_group_header_is_missing(
    async_engine, fixture_workflows_dir: Path
) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get("/api/user-info", headers={"X-User-Id": "alice@example.com"})

    assert response.status_code == 200
    assert response.json() == {"userId": "alice@example.com", "groups": []}


@pytest.mark.asyncio
async def test_user_info_does_not_expose_unmapped_external_groups(
    async_engine, fixture_workflows_dir: Path, monkeypatch, tmp_path
) -> None:
    from shared.lib.config import settings

    config = tmp_path / "platform-config.yaml"
    config.write_text(
        yaml.safe_dump({"identity": {"group_mapping": {"task-viewer": ["entra-sage-run-readers"]}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "platform_config_file", str(config))

    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get(
            "/api/user-info",
            headers={"X-User-Id": "alice@example.com", "X-User-Groups": "finance, engineering"},
        )

    assert response.status_code == 200
    assert response.json() == {"userId": "alice@example.com", "groups": []}


@pytest.mark.asyncio
async def test_user_info_returns_not_found_without_user_header(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get("/api/user-info", headers={"X-User-Groups": "sage-run-admin"})

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_message_reply_endpoint_returns_websocket_ingested_reply(
    async_engine, fixture_workflows_dir: Path, db_session
) -> None:
    from shared.lib.models import SessionEvent, Task

    task = Task(
        id=uuid.uuid4(),
        workflow="platform-test",
        prompt="Need an answer",
        status="waiting_user_input",
        message_channel="platform-test-channel",
        message_thread="thread-xyz",
    )
    db_session.add(task)
    await db_session.commit()
    db_session.add(
        SessionEvent(
            task_id=task.id,
            event_type="user_question_reply",
            timestamp=datetime.now(UTC),
            data={"message": "the answer", "user_id": "user-1", "username": "alice"},
        )
    )
    await db_session.commit()

    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get(f"/api/tasks/{task.id}/message-reply", params={"after_ms": 0})

    assert response.status_code == 200
    assert response.json() == {"message": "the answer", "user_id": "user-1", "username": "alice"}


@pytest.mark.asyncio
async def test_session_detail_endpoint_returns_parsed_trace(
    async_engine, fixture_workflows_dir: Path, db_session
) -> None:
    from shared.lib.models import SessionEvent, Task

    task = Task(
        id=uuid.uuid4(),
        workflow="platform-test",
        prompt="Investigate alert",
        status="succeeded",
    )
    db_session.add(task)
    await db_session.commit()
    db_session.add(
        SessionEvent(
            task_id=task.id,
            event_type="session_start",
            timestamp=datetime.now(UTC),
            data={"agent": "test-coordinator", "prompt_preview": "Investigate alert"},
        )
    )
    db_session.add(
        SessionEvent(
            task_id=task.id,
            event_type="session_complete",
            timestamp=datetime.now(UTC),
            data={"result": "All clear", "input_tokens": 100, "output_tokens": 50},
        )
    )
    await db_session.commit()

    async with await _make_client(fixture_workflows_dir) as client:
        response = await client.get(f"/api/sessions/{task.id}")

    assert response.status_code == 200
    payload = response.json()
    assert "trace" in payload
    assert payload["trace"]["root"]["label"] == "test-coordinator"
    assert len(payload["trace"]["root"]["children"]) == 2
    assert payload["trace"]["root"]["children"][0]["badge"] == "REQUEST"
    assert payload["trace"]["root"]["children"][1]["label"] == "Final"
    assert payload["trace"]["root"]["children"][1]["body"] == "All clear"
    assert payload["trace"]["stats"]["tokensIn"] == 100
    assert payload["trace"]["stats"]["tokensOut"] == 50
    assert "events" not in payload


@pytest.mark.asyncio
async def test_unknown_route_returns_404(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.get("/definitely-not-a-route")
        assert resp.status_code == 404
