"""Layer 1 — schedule firing and agent pause/resume."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from apscheduler.triggers.date import DateTrigger
from sqlalchemy import select

pytestmark = pytest.mark.service


@pytest.mark.asyncio
async def test_running_scheduler_reloads_only_after_activation_writer_finishes(
    async_engine, fixture_workflows_dir: Path, tmp_path, monkeypatch
) -> None:
    from contextlib import suppress

    from gateway import scheduler
    from gateway.main import _watch_deployments
    from gateway.provisioner import run_provisioner_scan
    from shared.lib import config_reload
    from shared.lib.config import settings
    from shared.lib.db import async_session_factory
    from shared.lib.models import Agent, Schedule, WorkflowRepoState

    monkeypatch.setattr(settings, "workflow_repo_paths", str(fixture_workflows_dir))
    monkeypatch.setattr(settings, "workflow_repo_local_path", str(tmp_path))
    monkeypatch.setattr(config_reload, "async_session_factory", async_session_factory)
    await run_provisioner_scan()
    await scheduler.start_scheduler()
    running_scheduler = scheduler._scheduler
    assert running_scheduler is not None
    handler_started, handler_release, handler_finished = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def in_flight_handler():
        handler_started.set()
        await handler_release.wait()
        handler_finished.set()

    running_scheduler.add_job(in_flight_handler, DateTrigger(run_date=datetime.now(UTC)))
    await asyncio.wait_for(handler_started.wait(), timeout=1)
    watch = asyncio.create_task(_watch_deployments())
    try:
        guard = tmp_path / ".git/sage-run-deploy.lock.d"
        guard.mkdir(parents=True)
        async with async_session_factory() as session:
            agent = (await session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
            schedule = (
                await session.execute(
                    select(Schedule).where(Schedule.agent_id == agent.id, Schedule.name == "test-daily")
                )
            ).scalar_one()
            schedule.name = "reloaded"
            schedule.prompt = "new activated prompt"
            state = await session.get(WorkflowRepoState, 1)
            if state is None:
                state = WorkflowRepoState(id=1)
                session.add(state)
            state.last_synced_at = datetime.now(UTC)
            state.last_sync_status = "ok"
            await session.commit()
        await asyncio.sleep(1.1)
        assert running_scheduler.get_job("platform-test:reloaded") is None
        guard.rmdir()

        async def wait_for_reload():
            while running_scheduler.get_job("platform-test:reloaded") is None:
                await asyncio.sleep(0.05)

        await asyncio.wait_for(wait_for_reload(), timeout=3)
        assert scheduler._scheduler is running_scheduler
        assert running_scheduler.get_job("platform-test:test-daily") is None
        assert running_scheduler.get_job("platform-test:reloaded").args[2] == "new activated prompt"
        handler_release.set()
        await asyncio.wait_for(handler_finished.wait(), timeout=1)
        async with async_session_factory() as session:
            agent = (await session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
            assert agent.paused is True
            schedule = (
                await session.execute(
                    select(Schedule).where(Schedule.agent_id == agent.id, Schedule.name == "reloaded")
                )
            ).scalar_one()
            schedule.cron = "invalid"
            await session.commit()
        jobs = running_scheduler.get_jobs()
        with pytest.raises(ValueError, match="5-field cron"):
            await scheduler.reload_schedules()
        assert running_scheduler.get_jobs() == jobs
    finally:
        handler_release.set()
        watch.cancel()
        with suppress(asyncio.CancelledError):
            await watch
        await scheduler.stop_scheduler()


async def _make_client(fixture_workflows_dir: Path) -> httpx.AsyncClient:
    from shared.lib.config import settings

    settings.workflow_repo_paths = str(fixture_workflows_dir)
    from gateway.main import app

    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://gateway.test")


# ── Agent pause/resume ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_agent_pause_and_resume_toggles_paused_flag(async_engine, fixture_workflows_dir: Path) -> None:
    from gateway.provisioner import run_provisioner_scan
    from shared.lib.config import settings
    from shared.lib.models import Agent

    with patch.object(settings, "workflow_repo_paths", str(fixture_workflows_dir)):
        await run_provisioner_scan()

    from shared.lib.db import async_session_factory

    async with async_session_factory() as session:
        agent = (await session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
        assert agent.paused is True

    async with await _make_client(fixture_workflows_dir) as client:
        # Pause
        resp = await client.post("/api/agents/platform-test/pause")
        assert resp.status_code == 200, resp.text
        assert resp.json()["paused"] is True

        # Resume
        resp = await client.post("/api/agents/platform-test/resume")
        assert resp.status_code == 200, resp.text
        assert resp.json()["paused"] is False

    # Verify DB state
    async with async_session_factory() as session:
        agent = (await session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
        assert agent.paused is False


@pytest.mark.asyncio
async def test_pause_unknown_agent_returns_404(async_engine, fixture_workflows_dir: Path) -> None:
    async with await _make_client(fixture_workflows_dir) as client:
        resp = await client.post("/api/agents/does-not-exist/pause")
        assert resp.status_code == 404


# ── Scheduler handler creates tasks ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_handler_creates_task_and_updates_last_run(
    async_engine, fixture_workflows_dir: Path, db_session
) -> None:
    """Calling the schedule handler directly should queue a task and stamp last_run."""
    from gateway.provisioner import run_provisioner_scan
    from gateway.scheduler import _schedule_job_handler
    from shared.lib.config import settings
    from shared.lib.models import Agent, Schedule, Task

    with patch.object(settings, "workflow_repo_paths", str(fixture_workflows_dir)):
        await run_provisioner_scan()

    agent = (await db_session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
    agent.paused = False
    await db_session.commit()

    # Fire the scheduled handler directly (simulates a cron fire).
    await _schedule_job_handler(
        agent_name="platform-test",
        schedule_name="test-daily",
        prompt="scheduled test prompt",
        message_channel="platform-test-channel",
    )

    # Verify task was created with triggered_by=scheduler
    tasks = (await db_session.execute(select(Task))).scalars().all()
    scheduled = [t for t in tasks if (t.task_metadata or {}).get("triggered_by") == "scheduler"]
    assert len(scheduled) == 1
    t = scheduled[0]
    assert t.workflow == "platform-test"
    assert t.prompt == "scheduled test prompt"
    assert t.message_channel == "platform-test-channel"
    assert (t.task_metadata or {}).get("schedule") == "test-daily"

    # Verify last_run was stamped
    agent = (await db_session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
    sched = (
        await db_session.execute(select(Schedule).where(Schedule.agent_id == agent.id, Schedule.name == "test-daily"))
    ).scalar_one()
    assert sched.last_run is not None


@pytest.mark.asyncio
async def test_schedule_handler_skips_paused_agent(async_engine, fixture_workflows_dir: Path, db_session) -> None:
    from gateway.provisioner import run_provisioner_scan
    from gateway.scheduler import _schedule_job_handler
    from shared.lib.config import settings
    from shared.lib.models import Agent, Schedule, Task

    with patch.object(settings, "workflow_repo_paths", str(fixture_workflows_dir)):
        await run_provisioner_scan()

    await _schedule_job_handler(
        agent_name="platform-test",
        schedule_name="test-daily",
        prompt="scheduled test prompt",
        message_channel="platform-test-channel",
    )

    assert (await db_session.execute(select(Task))).scalars().all() == []
    agent = (await db_session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
    sched = (
        await db_session.execute(select(Schedule).where(Schedule.agent_id == agent.id, Schedule.name == "test-daily"))
    ).scalar_one()
    assert sched.last_run is None


@pytest.mark.asyncio
async def test_scheduler_executes_registered_job_and_queues_task(
    async_engine, fixture_workflows_dir: Path, db_session
) -> None:
    from gateway.provisioner import run_provisioner_scan
    from gateway.scheduler import start_scheduler, stop_scheduler
    from shared.lib.config import settings
    from shared.lib.models import Agent, Schedule, Task

    run_at = datetime.now(UTC) + timedelta(seconds=1)

    with (
        patch.object(settings, "workflow_repo_paths", str(fixture_workflows_dir)),
        patch("gateway.scheduler._parse_cron", return_value=DateTrigger(run_date=run_at)),
    ):
        await run_provisioner_scan()

        agent = (await db_session.execute(select(Agent).where(Agent.name == "platform-test"))).scalar_one()
        agent.paused = False
        await db_session.commit()
        agent_id = agent.id

        await start_scheduler()

        try:
            deadline = asyncio.get_running_loop().time() + 5
            scheduled_task = None
            sched = None
            while asyncio.get_running_loop().time() < deadline:
                db_session.expire_all()
                tasks = (await db_session.execute(select(Task).where(Task.workflow == "platform-test"))).scalars().all()
                scheduled_task = next(
                    (task for task in tasks if (task.task_metadata or {}).get("triggered_by") == "scheduler"),
                    None,
                )
                sched = (
                    await db_session.execute(
                        select(Schedule).where(Schedule.agent_id == agent_id, Schedule.name == "test-daily")
                    )
                ).scalar_one()
                if scheduled_task is not None and sched.last_run is not None:
                    break
                await asyncio.sleep(0.1)

            assert scheduled_task is not None
            assert scheduled_task.prompt == "run the synthetic daily test workflow"
            assert scheduled_task.message_channel == "platform-test-channel"

            assert sched is not None
            assert sched.last_run is not None
        finally:
            await stop_scheduler()
