"""Generic ServiceNow Table API connector for creating workflow tasks."""

from __future__ import annotations

import asyncio
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


async def _create_task_from_record(parsed: dict, config: dict) -> None:
    """Create a task in Postgres from a parsed ServiceNow record."""
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
        submission = await submit_task(
            session,
            workflow=target["workflow"],
            prompt=prompt,
            channel=str(target.get("channel") or "servicenow"),
            metadata=metadata,
            dedupe=dedupe,
        )
        logger.info("Submitted ServiceNow record to task %s", submission.task.id)


async def run_polling_consumer(config: dict | None = None) -> None:
    """Poll ServiceNow, reloading configuration after successful activation."""
    revision = await active_config_revision()
    config = config if config is not None else _load_instance_config()
    workflow_env = _load_target_workflow_env(config)
    seen_sys_ids: set[str] = set()
    next_poll = 0.0
    source_identity = None
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
            table = str(source["table"])
            interval = float(source.get("interval_sec", 60))
            if interval <= 0:
                raise ValueError("ServiceNow source.interval_sec must be positive")
            identity = (instance_url, table, (config.get("target") or {}).get("workflow"))
            if identity != source_identity:
                seen_sys_ids.clear()
                source_identity = identity
            now = asyncio.get_running_loop().time()
            if now < next_poll or await _connector_is_paused(str(config.get("_instance_id") or "")):
                await asyncio.sleep(1)
                continue
            next_poll = now + interval
            api_url = f"{instance_url.rstrip('/')}/api/now/table/{table}"
            query = str(source.get("query") or "")
            params = {
                "sysparm_query": query,
                "sysparm_display_value": "true",
                "sysparm_limit": "50",
            }
            fields = source.get("fields", [])
            if fields:
                params["sysparm_fields"] = ",".join(fields)
            try:
                resp = await client.get(api_url, params=params, auth=(username, password))
                resp.raise_for_status()
                data = resp.json()

                records = data.get("result", [])
                logger.info(
                    "ServiceNow poll: connector=%s table=%s query=%r fetched=%d limit=%s",
                    config.get("_instance_id", "unknown"),
                    table,
                    query,
                    len(records),
                    params["sysparm_limit"],
                )
                new_count = 0
                for record in records:
                    sys_id = record.get("sys_id", "")
                    if sys_id in seen_sys_ids:
                        continue
                    seen_sys_ids.add(sys_id)

                    parsed = _parse_record(record, config)
                    await _create_task_from_record(parsed, config)
                    new_count += 1

                if new_count:
                    logger.info("Processed %d new records from ServiceNow", new_count)

                # Prevent unbounded memory growth — keep only recent IDs
                if len(seen_sys_ids) > 10000:
                    seen_sys_ids.clear()

            except httpx.HTTPStatusError as e:
                logger.error("ServiceNow API error: %s %s", e.response.status_code, e.response.text[:200])
            except Exception:
                logger.exception("Error polling ServiceNow")

            await asyncio.sleep(1)


async def main_async() -> None:
    from shared.lib.health_server import start_health_server

    start_health_server()
    _bootstrap_platform_env()
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
