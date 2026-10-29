"""Template for a custom SAGE Run v2 connector.

Demonstrates how external workflow repositories implement event intake using
the shared SAGE Run connector libraries:
- `load_connector_config` (`shared.lib.platform_secrets`) for age-decrypted config
- `connector_is_paused` (`shared.lib.connector_state`) for control-plane pause state
- `DedupeCheck` and `submit_task` (`shared.lib.task_queue`) for task submission
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from shared.lib.config import settings
from shared.lib.connector_state import connector_is_paused
from shared.lib.platform_secrets import (
    apply_platform_env_defaults,
    load_connector_instance,
    load_enabled_connector_instance,
)
from shared.lib.task_queue import DedupeCheck, submit_task

logger = logging.getLogger("custom-connector-example")

CONNECTOR_TYPE = "custom-example"


class _SafeFormatDict(dict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def load_enabled_instance() -> tuple[str, dict[str, Any]]:
    """Load the enabled `custom-example` connector instance from `platform-config.yaml`."""
    if (Path(settings.platform_config_file).parent / ".git/sage-run-deploy.lock.d").exists():
        return "", {}
    apply_platform_env_defaults(
        os.environ,
        path=settings.platform_config_file,
        identity=os.environ.get("AGE_IDENTITY") or None,
    )
    explicit_id = os.environ.get("CONNECTOR_INSTANCE_ID", "").strip()
    if explicit_id:
        return explicit_id, load_connector_instance(settings.platform_config_file, explicit_id)
    return load_enabled_connector_instance(settings.platform_config_file, CONNECTOR_TYPE)


def extract_event_fields(raw_event: dict[str, Any], extract_map: dict[str, str]) -> dict[str, str]:
    """Project raw event fields according to the connector `extract` mapping."""
    return {
        target_key: str(raw_event.get(source_key) or "").strip()
        for target_key, source_key in (extract_map or {}).items()
    }


def render_task_prompt(extracted: dict[str, str], template: str) -> str:
    """Render the target workflow prompt from extracted event fields."""
    return template.format_map(_SafeFormatDict(extracted)).strip()


async def fetch_pending_events(instance_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Poll the upstream API configured under `source` and `secrets`."""
    source_cfg = instance_cfg.get("source") or {}
    secrets_cfg = instance_cfg.get("secrets") or {}
    base_url = str(source_cfg.get("base_url") or "").rstrip("/")
    token = str(secrets_cfg.get("CUSTOM_CONNECTOR_TOKEN") or "").strip()
    if not base_url:
        return []

    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(f"{base_url}/events", headers=headers)
        response.raise_for_status()
        payload = response.json()
    return [item for item in (payload.get("items") or []) if isinstance(item, dict)]


async def ingest_event(
    session: AsyncSession,
    *,
    instance_id: str,
    instance_cfg: dict[str, Any],
    raw_event: dict[str, Any],
) -> dict[str, str]:
    """Submit a single upstream event into the SAGE Run task queue with deduplication."""
    if await connector_is_paused(session, f"connector:{instance_id}"):
        return {"status": "paused"}

    extract_cfg = instance_cfg.get("extract") or {"event_id": "id", "summary": "summary"}
    target_cfg = instance_cfg.get("target") or {}
    extracted = extract_event_fields(raw_event, extract_cfg)
    event_id = extracted.get("event_id")
    if not event_id:
        return {"status": "ignored_missing_id"}

    workflow = str(target_cfg.get("workflow") or "example-workflow")
    coalesce_window = int(target_cfg.get("coalesce_window_seconds") or 300)
    prompt_template = str(
        target_cfg.get("prompt_template")
        or "New event received from Custom Connector:\n- Event ID: {event_id}\n- Summary: {summary}\n"
    )
    prompt = render_task_prompt(extracted, prompt_template)
    dedupe_key = f"{CONNECTOR_TYPE}:{instance_id}:{event_id}"

    submission = await submit_task(
        session,
        workflow=workflow,
        prompt=prompt,
        dedupe=[DedupeCheck(key=dedupe_key, window_sec=coalesce_window)],
        channel="connector",
        initiator=f"{CONNECTOR_TYPE}:{instance_id}",
        metadata={
            "connector_type": CONNECTOR_TYPE,
            "connector_instance": instance_id,
            "event_id": event_id,
        },
    )
    if submission.duplicate_of is not None:
        return {"status": "deduplicated", "event_id": event_id, "task_id": str(submission.task.id)}
    return {"status": "submitted", "event_id": event_id, "task_id": str(submission.task.id)}
