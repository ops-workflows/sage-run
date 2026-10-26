"""The persisted successful activation revision shared by long-lived consumers."""

from datetime import datetime
from pathlib import Path

from sqlalchemy import select

from shared.lib.config import settings
from shared.lib.db import async_session_factory
from shared.lib.models import WorkflowRepoState


async def active_config_revision() -> datetime | None:
    if (Path(settings.workflow_repo_local_path) / ".git/sage-run-deploy.lock.d").exists():
        return None
    async with async_session_factory() as session:
        return await session.scalar(
            select(WorkflowRepoState.last_synced_at).where(
                WorkflowRepoState.id == 1, WorkflowRepoState.last_sync_status == "ok"
            )
        )
