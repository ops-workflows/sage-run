"""Approval and clarification waits do not count toward the runtime timeout."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

pytestmark = pytest.mark.service

from session_manager import heartbeat  # noqa: E402
from sqlalchemy import update  # noqa: E402

from gateway.event_collector import EventPayload, receive_event  # noqa: E402
from shared.lib.models import Session, Task  # noqa: E402
from shared.lib.task_queue import create_task, dequeue_task  # noqa: E402


async def _event(task_id, event_type: str, data: dict | None = None) -> None:
    await receive_event(
        EventPayload(
            task_id=str(task_id),
            event_type=event_type,
            timestamp=datetime.now(UTC).isoformat(),
            data=data or {},
        )
    )


async def _reload(db_session, task_id) -> Task:
    task = await db_session.get(Task, task_id)
    await db_session.refresh(task)
    return task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "data", "timeout"),
    [
        ("approval_requested", {"tool_name": "Bash", "request_id": "test"}, 120),
        ("user_question_requested", {"questions": [{"question": "Proceed?"}]}, 240),
    ],
)
async def test_custom_wait_deadline_matches_runtime_budget_and_retries_do_not_extend_it(
    db_session, event_type, data, timeout
) -> None:
    task = await create_task(db_session, workflow="platform-test", prompt="custom wait")
    await dequeue_task(db_session, workflow="platform-test")
    event = EventPayload(task_id=str(task.id), event_type=event_type, data=data, wait_timeout_sec=timeout)
    await receive_event(event)
    waiting = await _reload(db_session, task.id)
    assert waiting.wait_deadline - waiting.wait_started == timedelta(seconds=timeout)
    first_deadline = waiting.wait_deadline
    await receive_event(event)
    assert (await _reload(db_session, task.id)).wait_deadline == first_deadline


@pytest.mark.parametrize("timeout", [0, -1, True, 604801, "120"])
def test_invalid_wait_budget_is_rejected(timeout):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EventPayload(event_type="user_question_requested", wait_timeout_sec=timeout)


@pytest.mark.asyncio
async def test_clarification_wait_is_tracked_once_and_closed_on_resolution(db_session) -> None:
    task = await create_task(db_session, workflow="platform-test", prompt="ask then continue")
    await dequeue_task(db_session, workflow="platform-test")

    await _event(task.id, "user_question_requested", {"questions": [{"question": "Proceed?"}]})
    waiting = await _reload(db_session, task.id)
    assert waiting.status == "waiting_user_input"
    first_start = waiting.wait_started
    assert first_start is not None

    await db_session.execute(
        update(Task).where(Task.id == task.id).values(wait_started=first_start - timedelta(hours=2))
    )
    await db_session.commit()
    await _event(task.id, "user_question_delivery_failed", {"error": "retry"})
    assert (await _reload(db_session, task.id)).wait_started == first_start - timedelta(hours=2)

    await _event(task.id, "user_question_resolved", {"question_count": 1})
    resumed = await _reload(db_session, task.id)
    assert resumed.status == "resume_pending"
    assert resumed.wait_started is None
    assert resumed.waited_sec >= 2 * 3600

    redequeued = await dequeue_task(db_session, workflow="platform-test", max_running=1)
    assert redequeued is not None and redequeued.status == "running"
    assert (await _reload(db_session, task.id)).waited_sec == resumed.waited_sec


@pytest.mark.asyncio
async def test_runtime_timeout_sweep_ignores_wait_time_but_enforces_active_time(db_session, monkeypatch) -> None:
    monkeypatch.setattr(heartbeat, "_workflow_runtime_timeout_sec", lambda workflow: 300)
    now = datetime.now(UTC)
    tasks = {}
    for name, waited_sec in (("waited", 2 * 3600), ("busy", 0)):
        task = await create_task(db_session, workflow="platform-test", prompt=name)
        await dequeue_task(db_session, workflow="platform-test")
        await db_session.execute(update(Task).where(Task.id == task.id).values(waited_sec=waited_sec))
        db_session.add(
            Session(
                task_id=task.id, container_id=f"c-{name}", status="running", started=now - timedelta(hours=2, minutes=2)
            )
        )
        tasks[name] = task.id
    await db_session.commit()

    timed_out = await heartbeat._runtime_timeout_sweep(db_session)

    assert timed_out == [tasks["busy"]]
    assert (await _reload(db_session, tasks["waited"])).status == "running"
    assert (await _reload(db_session, tasks["busy"])).status == "timed_out"
