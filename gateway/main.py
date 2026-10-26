"""Gateway — main FastAPI application.

The Gateway is the web-facing HTTP service. It receives all inbound requests,
writes to Postgres, and returns. No heavy processing — it's a thin routing layer.

Mounts:
    - Gateway-owned message ingress (human → agent)
  - Event collector (agent → control plane, replaces Langfuse)
  - Control-plane API (UI data)
  - Scheduler (APScheduler for cron jobs)
  - Provisioner (agent discovery & registration)
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from gateway.api import router as api_router
from gateway.deployments import router as deployment_router
from gateway.event_collector import router as event_router
from gateway.message import router as message_router
from gateway.message_ingress import GatewayMessageIngress
from gateway.provisioner import run_provisioner_scan
from gateway.scheduler import reload_schedules, start_scheduler, stop_scheduler
from shared.lib.config_reload import active_config_revision
from shared.lib.connector_state import MESSAGE_INGRESS_CONNECTOR_ID, connector_is_paused
from shared.lib.db import async_session_factory, ensure_runtime_schema

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _watch_deployments() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    revision = None
    while True:
        try:
            latest = await active_config_revision()
            if latest is not None and latest != revision:
                await reload_schedules()
                revision = latest
                logger.info("Reloaded schedules after workflow activation")
        except (SQLAlchemyError, ValueError, RuntimeError):
            logger.exception("Failed to reload activated schedules; will retry")
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle."""
    logger.info("Gateway starting up")
    await ensure_runtime_schema()
    # Run initial provisioner scan (discover agent.yaml files)
    await run_provisioner_scan()
    # Start APScheduler (reads cron from agent.yaml)
    await start_scheduler()
    message_ingress = GatewayMessageIngress()
    async with async_session_factory() as session:
        message_ingress_paused = await connector_is_paused(session, MESSAGE_INGRESS_CONNECTOR_ID)
    if message_ingress_paused:
        logger.info("Message ingress is paused")
    else:
        await message_ingress.start()
    app.state.message_ingress = message_ingress
    reload_task = asyncio.create_task(_watch_deployments())
    logger.info("Gateway ready")
    yield
    reload_task.cancel()
    with suppress(asyncio.CancelledError):
        await reload_task
    await message_ingress.stop()
    # Shutdown
    await stop_scheduler()
    logger.info("Gateway shut down")


app = FastAPI(
    title="SAGE Run — Gateway",
    description="Web-facing gateway: webhooks, event collector, control-plane API",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS for control-plane UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://control-plane-ui:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount route modules
app.include_router(message_router, prefix="/webhooks", tags=["webhooks"])
app.include_router(event_router, tags=["events"])
app.include_router(api_router, prefix="/api", tags=["control-plane"])
app.include_router(deployment_router, prefix="/api", tags=["deployments"])


@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "gateway"}
