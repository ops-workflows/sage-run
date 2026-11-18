"""Generic ServiceNow Table API connector for creating workflow tasks."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import signal
from typing import Any

import httpx

from shared.lib.config_reload import active_config_revision
from shared.lib.connections import connection_environment, resolve_workflow_connections
from shared.lib.crypto import decrypt_agent_secrets
from shared.lib.platform_config import load_platform_config
from shared.lib.platform_secrets import (
    apply_platform_env_defaults,
    load_connector_instance,
    load_enabled_connector_instance,
)
from shared.lib.workflow_paths import find_workflow_package

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

_shutdown = False


def _signal_handler(sig, frame):
    global _shutdown
    _shutdown = True


def _platform_config_file() -> str:
    return os.environ.get("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml")


def _bootstrap_platform_env() -> None:
    identity = os.environ.get("AGE_IDENTITY", "") or None
    loaded = apply_platform_env_defaults(os.environ, path=_platform_config_file(), identity=identity)
    if loaded:
        logger.info("Loaded %s platform config entries from %s", len(loaded), _platform_config_file())


def _load_instance_config() -> dict:
    instance_id = os.environ.get("CONNECTOR_INSTANCE_ID", "").strip()
    if instance_id:
        config = load_connector_instance(_platform_config_file(), instance_id)
    else:
        instance_id, config = load_enabled_connector_instance(_platform_config_file(), "servicenow")
    if not config:
        raise RuntimeError("Set CONNECTOR_INSTANCE_ID or enable exactly one servicenow instance in platform config")
    source = config.get("source") if isinstance(config.get("source"), dict) else {}
    target = config.get("target") if isinstance(config.get("target"), dict) else {}
    if not str(source.get("table") or "").strip():
        raise RuntimeError("ServiceNow connector source.table must be configured")
    if not str(target.get("workflow") or "").strip():
        raise RuntimeError("ServiceNow connector target.workflow must be configured")
    if not str(target.get("prompt_template") or "").strip():
        raise RuntimeError("ServiceNow connector target.prompt_template must be configured")
    coalescing = config.get("coalescing") if isinstance(config.get("coalescing"), dict) else {}
    if coalescing.get("enabled") and not str(coalescing.get("key_field") or "").strip():
        raise RuntimeError("ServiceNow connector coalescing.key_field must be configured when coalescing is enabled")
    return {**config, "_instance_id": instance_id}


async def _connector_is_paused(connector_id: str) -> bool:
    from shared.lib.connector_state import connector_is_paused
    from shared.lib.db import async_session_factory

    async with async_session_factory() as session:
        return await connector_is_paused(session, connector_id)


def _load_target_workflow_env(config: dict) -> dict[str, str]:
    target = config.get("target") if isinstance(config.get("target"), dict) else {}
    workflow = str(target.get("workflow") or "").strip()
    if not workflow:
        raise RuntimeError("ServiceNow connector target.workflow must be configured")

    package = find_workflow_package(workflow)
    if package is None:
        raise RuntimeError(f"ServiceNow target workflow {workflow!r} was not found")

    workflow_env: dict[str, str] = {}
    configured_env = package.config.get("env")
    if isinstance(configured_env, dict):
        workflow_env.update(
            {
                str(key): str(value)
                for key, value in configured_env.items()
                if isinstance(value, (str, int, float, bool))
            }
        )

    identity = os.environ.get("AGE_IDENTITY", "")
    secrets = package.config.get("secrets")
    if isinstance(secrets, dict) and secrets:
        workflow_env.update(decrypt_agent_secrets(package.config, identity=identity))

    # Connections the target workflow lists supply its integration settings.
    platform_config = load_platform_config(os.environ.get("PLATFORM_CONFIG_FILE", "/app/platform-config.yaml"))
    connections = resolve_workflow_connections(platform_config, workflow, package.config)
    connection_env, connection_secrets = connection_environment(connections, identity=identity)
    workflow_env.update(connection_env)
    workflow_env.update(connection_secrets)
    return workflow_env


def _extract_nested(data: dict, dot_path: str) -> Any:
    """Extract a value from a nested dict using dot notation (e.g. 'caller_id.display_value')."""
    parts = dot_path.split(".")
    current = data
    for part in parts:
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _parse_record(record: dict, config: dict) -> dict[str, Any]:
    """Parse a ServiceNow record using the instance extraction mapping."""
    extract_config = config.get("parsing", {}).get("extract", {})
    parsed: dict[str, Any] = {}
    for field, path in extract_config.items():
        parsed[field] = _extract_nested(record, path)
    parsed["raw_record"] = json.dumps(record)[:5000]
    return parsed


class _SafeFormatMap(dict):
    def __missing__(self, key: str) -> str:
        return ""


def _build_prompt(parsed: dict, config: dict) -> str:
    target = config.get("target") if isinstance(config.get("target"), dict) else {}
    template = str(target.get("prompt_template") or "")
    values = _SafeFormatMap({key: "" if value is None else str(value) for key, value in parsed.items()})
    return template.format_map(values)


def _source_key(instance_url: str, table: str, workflow: str) -> str:
    identity = json.dumps([instance_url.rstrip("/"), table, workflow], separators=(",", ":"))
    return hashlib.sha256(identity.encode()).hexdigest()


async def _load_page_offset(connector_id: str, source_key: str, query_hash: str) -> int:
    from sqlalchemy import text

    from shared.lib.db import async_session_factory

    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT page_offset, query_hash FROM control_plane.servicenow_connector_checkpoints "
                "WHERE connector_id = :connector_id AND source_key = :source_key"
            ),
            {"connector_id": connector_id, "source_key": source_key},
        )
        checkpoint = result.one_or_none()
        return checkpoint.page_offset if checkpoint and checkpoint.query_hash == query_hash else 0


async def _save_page_offset(connector_id: str, source_key: str, query_hash: str, offset: int) -> None:
    from sqlalchemy import text

    from shared.lib.db import async_session_factory

    async with async_session_factory() as session:
        await session.execute(
            text(
                "INSERT INTO control_plane.servicenow_connector_checkpoints "
                "(connector_id, source_key, query_hash, page_offset) "
                "VALUES (:connector_id, :source_key, :query_hash, :offset) "
                "ON CONFLICT (connector_id, source_key) DO UPDATE "
                "SET query_hash = EXCLUDED.query_hash, page_offset = EXCLUDED.page_offset"
            ),
            {"connector_id": connector_id, "source_key": source_key, "query_hash": query_hash, "offset": offset},
        )
        await session.commit()


async def _create_task_from_record(parsed: dict, config: dict, source_key: str, sys_id: str) -> bool:
    """Commit the record receipt in the same transaction as its task."""
    from sqlalchemy import text

    from shared.lib.db import async_session_factory
    from shared.lib.task_queue import DedupeCheck, submit_task

    target = config.get("target", {})
    coalescing = config.get("coalescing", {})

    dedupe = []
    if coalescing.get("enabled"):
        key_field = str(coalescing["key_field"])
        dedupe.append(
            DedupeCheck(
                key=f"{target['workflow']}:{parsed.get(key_field, 'unknown')}",
                window_sec=int(coalescing.get("window_sec", 300)),
            )
        )

    prompt = _build_prompt(parsed, config)
    metadata = {**parsed, "source": "servicenow-connector"}

    async with async_session_factory() as session:
        receipt = await session.execute(
            text(
                "INSERT INTO control_plane.servicenow_connector_records (connector_id, source_key, sys_id) "
                "VALUES (:connector_id, :source_key, :sys_id) "
                "ON CONFLICT DO NOTHING RETURNING sys_id"
            ),
            {"connector_id": config["_instance_id"], "source_key": source_key, "sys_id": sys_id},
        )
        if receipt.scalar_one_or_none() is None:
            return False
        submission = await submit_task(
            session,
            workflow=target["workflow"],
            prompt=prompt,
            channel=str(target.get("channel") or "servicenow"),
            metadata=metadata,
            dedupe=dedupe,
        )
        logger.info("Submitted ServiceNow record to task %s", submission.task.id)
    return True


async def _poll_pages(client: httpx.AsyncClient, config: dict, instance_url: str, username: str, password: str) -> None:
    source = config["source"]
    table = str(source["table"])
    connector_id = str(config["_instance_id"])
    workflow = str(config["target"]["workflow"])
    source_key = _source_key(instance_url, table, workflow)
    query = str(source.get("query") or "")
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    page_size = source.get("page_size", 50)
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 10000:
        raise ValueError("ServiceNow source.page_size must be an integer between 1 and 10000")

    fields = list(source.get("fields") or [])
    if fields and "sys_id" not in fields:
        fields.append("sys_id")
    offset = await _load_page_offset(connector_id, source_key, query_hash)
    api_url = f"{instance_url.rstrip('/')}/api/now/table/{table}"
    new_count = 0
    while not _shutdown:
        if await _connector_is_paused(connector_id):
            break
        params = {
            "sysparm_query": query,
            "sysparm_display_value": "true",
            "sysparm_limit": str(page_size),
            "sysparm_offset": str(offset),
        }
        if fields:
            params["sysparm_fields"] = ",".join(fields)
        resp = await client.get(api_url, params=params, auth=(username, password))
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("result"), list):
            raise ValueError("ServiceNow returned an invalid list response")
        records = data["result"]
        total_header = resp.headers.get("X-Total-Count")
        if total_header is not None:
            try:
                total = int(total_header)
            except ValueError as exc:
                raise ValueError("ServiceNow returned an invalid X-Total-Count") from exc
            if total < 0:
                raise ValueError("ServiceNow returned a negative X-Total-Count")
        else:
            total = None
            logger.warning("ServiceNow omitted X-Total-Count; ACL-filtered pages may not be fully discoverable")
        logger.info(
            "ServiceNow poll: connector=%s table=%s query=%r fetched=%d limit=%s offset=%d",
            connector_id,
            table,
            query,
            len(records),
            page_size,
            offset,
        )
        for record in records:
            if (
                not isinstance(record, dict)
                or not isinstance(record.get("sys_id"), str)
                or not record["sys_id"].strip()
            ):
                raise ValueError("ServiceNow record is missing a valid sys_id")
            sys_id = record["sys_id"].strip()
            parsed = _parse_record(record, config)
            if await _create_task_from_record(parsed, config, source_key, sys_id):
                new_count += 1

        next_offset = offset + page_size
        finished = next_offset >= total if total is not None else len(records) < page_size
        await _save_page_offset(connector_id, source_key, query_hash, 0 if finished else next_offset)
        if finished:
            break
        offset = next_offset
    if new_count:
        logger.info("Processed %d new records from ServiceNow", new_count)


async def run_polling_consumer(config: dict | None = None) -> None:
    """Poll ServiceNow, reloading configuration after successful activation."""
    revision = await active_config_revision()
    config = config if config is not None else _load_instance_config()
    workflow_env = _load_target_workflow_env(config)
    next_poll = 0.0
    async with httpx.AsyncClient(headers={"Accept": "application/json"}, timeout=30.0) as client:
        while not _shutdown:
            latest = await active_config_revision()
            if latest is not None and latest != revision:
                config = _load_instance_config()
                workflow_env = _load_target_workflow_env(config)
                revision = latest
                next_poll = 0.0
                logger.info("Reloaded ServiceNow configuration after workflow activation")
            source = config.get("source", {})
            instance_url = workflow_env.get("SERVICENOW_INSTANCE_URL", "")
            username = workflow_env.get("SERVICENOW_USERNAME", "")
            password = workflow_env.get("SERVICENOW_PASSWORD", "")
            if not instance_url or not username or not password:
                raise RuntimeError("ServiceNow connection requires INSTANCE_URL, USERNAME and PASSWORD")
            interval = float(source.get("interval_sec", 60))
            if interval <= 0:
                raise ValueError("ServiceNow source.interval_sec must be positive")
            now = asyncio.get_running_loop().time()
            if now < next_poll or await _connector_is_paused(str(config.get("_instance_id") or "")):
                await asyncio.sleep(1)
                continue
            next_poll = now + interval
            try:
                await _poll_pages(client, config, instance_url, username, password)
            except httpx.HTTPStatusError as e:
                logger.error("ServiceNow API error: %s %s", e.response.status_code, e.response.text[:200])
            except Exception:
                logger.exception("Error polling ServiceNow")

            await asyncio.sleep(1)


async def main_async() -> None:
    from shared.lib.db import ensure_runtime_schema
    from shared.lib.health_server import start_health_server

    start_health_server()
    _bootstrap_platform_env()
    await ensure_runtime_schema()
    config = _load_instance_config()
    logger.info("ServiceNow Connector starting (config: %s)", config.get("name", "unknown"))
    await run_polling_consumer()


def main() -> None:
    signal.signal(signal.SIGTERM, _signal_handler)
    signal.signal(signal.SIGINT, _signal_handler)

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("ServiceNow Connector stopped")


if __name__ == "__main__":
    main()
