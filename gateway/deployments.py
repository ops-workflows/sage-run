"""Control-plane access to deployment Jobs; no deployment work runs in Gateway."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from sage_run.deployment import DEPLOY_LABEL, job_manifest, job_status, validate_ref
from shared.lib.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/platform/deployments")


class DeploymentRequest(BaseModel):
    ref: str = "main"
    expected_commit: str | None = None
    target_version: str | None = None


def _clients():
    from kubernetes import client, config

    config.load_incluster_config()
    return client.BatchV1Api(), client.AppsV1Api(), client.CoreV1Api(), client.ApiClient()


def _operation(
    *,
    ref: str | None = None,
    logs: bool = False,
    expected_commit: str | None = None,
    target_version: str | None = None,
) -> dict:
    from kubernetes.client.exceptions import ApiException
    from kubernetes.config.config_exception import ConfigException

    if not settings.workflow_repo_managed:
        raise HTTPException(503, "Deployment Jobs are not enabled for this instance; use the CLI")
    namespace = settings.kubernetes_namespace
    try:
        batch, apps, core, api = _clients()
        jobs = api.sanitize_for_serialization(
            batch.list_namespaced_job(namespace, label_selector=f"{DEPLOY_LABEL}=true")
        )["items"]
        jobs.sort(key=lambda item: item["metadata"].get("creationTimestamp", ""), reverse=True)
        if ref is not None:
            ref = validate_ref(ref, remote=settings.workflow_repo_source != "local")
            if any(job_status(item)["status"] in {"pending", "running"} for item in jobs):
                raise HTTPException(409, "A deployment is already in progress")
            gateway = api.sanitize_for_serialization(apps.read_namespaced_deployment("gateway", namespace))
            pod_list = api.sanitize_for_serialization(
                core.list_namespaced_pod(namespace, label_selector="app.kubernetes.io/component=gateway")
            )["items"]
            nodes = {item["spec"].get("nodeName") for item in pod_list if not item["metadata"].get("deletionTimestamp")}
            if len(nodes) != 1 or None in nodes:
                raise HTTPException(503, "Cannot determine the serving Gateway node")
            gateway["metadata"].setdefault("annotations", {})["sage-run/node"] = nodes.pop()
            target_image = None
            if target_version:
                from importlib.metadata import version

                from sage_run.incluster import resolve_service_image, resolve_target_images

                running_ver = version("sage-run")
                if target_version != running_ver:
                    target_image = resolve_service_image(
                        resolve_target_images({}, current_version=running_ver, target_version=target_version),
                        "gateway",
                    )
            job = api.sanitize_for_serialization(
                batch.create_namespaced_job(
                    namespace,
                    job_manifest(
                        gateway,
                        namespace=namespace,
                        ref=ref,
                        expected_commit=expected_commit,
                        target_version=target_version,
                        target_image=target_image,
                    ),
                )
            )
            return job_status(job)
        if not jobs:
            return {"deployment": None}
        result = job_status(jobs[0])
        if logs:
            pods = api.sanitize_for_serialization(
                core.list_namespaced_pod(namespace, label_selector=f"job-name={jobs[0]['metadata']['name']}")
            )["items"]
            result["logs"] = ""
            if pods and (pods[0].get("status") or {}).get("phase") != "Pending":
                response = core.read_namespaced_pod_log(
                    pods[0]["metadata"]["name"],
                    namespace,
                    container="deploy",
                    tail_lines=300,
                    limit_bytes=65536,
                    _preload_content=False,
                )
                try:
                    result["logs"] = response.data.decode("utf-8", errors="replace")
                finally:
                    response.close()
                    response.release_conn()
            pending = (pods[0].get("status") or {}).get("containerStatuses", []) if pods else []
            waiting = next((item["state"]["waiting"] for item in pending if "waiting" in item.get("state", {})), None)
            if waiting:
                result["error"] = waiting.get("message") or waiting.get("reason")
        return {"deployment": result}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except ApiException as exc:
        logger.exception("Deployment Kubernetes operation failed (status %s)", exc.status)
        raise HTTPException(409 if exc.status == 409 else 503, "Kubernetes deployment operation failed") from exc
    except ConfigException as exc:
        logger.exception("Deployment Kubernetes credentials are unavailable")
        raise HTTPException(503, "In-cluster deployment credentials are unavailable; use the CLI") from exc


def _plan_operation(ref: str) -> dict:
    from sage_run.incluster import plan_in_cluster

    if not settings.workflow_repo_managed:
        raise HTTPException(503, "Deployment Jobs are not enabled for this instance; use the CLI")
    try:
        return plan_in_cluster(ref)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.exception("Deployment plan computation failed")
        raise HTTPException(503, f"Deployment plan computation failed: {exc}") from exc


@router.get("")
async def latest_deployment():
    return await asyncio.to_thread(_operation, logs=True)


@router.get("/plan")
async def get_deployment_plan(ref: str = "main"):
    return await asyncio.to_thread(_plan_operation, ref)


@router.post("", status_code=202)
async def create_deployment(payload: DeploymentRequest):
    return await asyncio.to_thread(
        _operation,
        ref=payload.ref,
        expected_commit=payload.expected_commit,
        target_version=payload.target_version,
    )
