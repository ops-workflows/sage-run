"""Namespace-scoped deployment Jobs and the shared single-checkout lock."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import yaml

DEPLOY_JOB = "sage-run-deploy"
DEPLOY_LABEL = "sage-run/deployment"
REF_ANNOTATION = "sage-run/ref"
EXTRA_KINDS = (
    "Deployment",
    "StatefulSet",
    "Service",
    "Ingress",
    "NetworkPolicy",
    "ConfigMap",
    "Secret",
    "ServiceAccount",
    "Role",
    "RoleBinding",
    "PersistentVolumeClaim",
    "Job",
    "CronJob",
)


def extra_manifests(tree: Path, *, host_checkout: str, namespace: str) -> dict[tuple[str, str], dict]:
    """Render only namespace-scoped extras; hash checkout-backed subPath files."""
    resources = {}
    for path in sorted((tree / "deploy/k8s").glob("*.yaml")):
        rendered = path.read_text(encoding="utf-8").replace("${WORKFLOW_REPO_PATH}", host_checkout)
        for document in yaml.safe_load_all(rendered):
            if not document:
                continue
            metadata = document.setdefault("metadata", {})
            if document.get("kind") not in EXTRA_KINDS or metadata.get("namespace", namespace) != namespace:
                raise ValueError(f"{path.name}: extra manifests must use supported resources in {namespace}")
            name = metadata.get("name")
            if not name:
                raise ValueError(f"{path.name}: extra manifest needs metadata.name")
            metadata["namespace"] = namespace
            metadata.setdefault("labels", {})["sage-run/extra"] = namespace
            template = document.get("spec", {}).get("template")
            if template:
                digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode())
                pod = template.get("spec") or {}
                checkout_volumes = {
                    item["name"]
                    for item in pod.get("volumes", [])
                    if (item.get("hostPath") or {}).get("path") == host_checkout
                }
                for container in pod.get("containers", []):
                    for mount in container.get("volumeMounts", []):
                        if mount["name"] not in checkout_volumes or not mount.get("subPath"):
                            continue
                        source = (tree / mount["subPath"]).resolve()
                        if not source.is_relative_to(tree.resolve()) or not source.is_file():
                            raise ValueError(f"{path.name}: checkout subPath must name a file inside the repository")
                        digest.update(source.read_bytes())
                template.setdefault("metadata", {}).setdefault("annotations", {})["sage-run/source-checksum"] = (
                    digest.hexdigest()
                )
            key = (document["kind"], name)
            if key in resources:
                raise ValueError(f"Duplicate extra manifest: {key}")
            resources[key] = document
    return resources


def owned_extras(
    items: list[dict], namespace: str, *, desired: dict[tuple[str, str], dict]
) -> dict[tuple[str, str], dict]:
    resources = {}
    for item in items:
        metadata = item.get("metadata") or {}
        key = (item["kind"], metadata["name"])
        if metadata.get("labels", {}).get("sage-run/extra") != namespace:
            if key in desired:
                raise ValueError(
                    f"{key[0]}/{key[1]} exists without this instance's extra ownership; "
                    f"review it before explicitly labeling sage-run/extra={namespace}"
                )
            continue
        document = copy.deepcopy(item)
        document.pop("status", None)
        document["metadata"] = {
            key: value for key, value in metadata.items() if key in {"name", "namespace", "labels", "annotations"}
        }
        resources[key] = document
    return resources


def validate_ref(ref: str, *, remote: bool) -> str:
    ref = ref.strip()
    if not remote:
        if ref not in {"", "working-tree"}:
            raise ValueError("Local deployment uses the working tree, not a remote ref")
        return "working-tree"
    if ref != "main" and not re.fullmatch(r"v[A-Za-z0-9][A-Za-z0-9._-]{0,126}", ref):
        raise ValueError("Production deployment requires main or a v-prefixed tag")
    return ref


@contextmanager
def checkout_lock(checkout: Path) -> Iterator[None]:
    """Atomic mkdir also serializes macOS and Linux across Rancher's shared mount."""
    git_dir = checkout / ".git"
    if not git_dir.is_dir():
        raise ValueError("Deployment needs a Git checkout with a mounted .git directory")
    guard = git_dir / "sage-run-deploy.lock.d"
    try:
        guard.mkdir()
    except FileExistsError as exc:
        raise ValueError(
            f"Another deployment or backup owns {guard}; if stale, stop all writers before removing this directory"
        ) from exc
    # shortcut: forced termination leaves a guard; clear it only after all writers stop.
    try:
        yield
    finally:
        guard.rmdir()


def job_manifest(gateway: dict, *, namespace: str, ref: str) -> dict:
    """Reuse the running Gateway's pinned image, mounts, networking and secrets."""
    name = f"{DEPLOY_JOB}-{uuid4().hex[:12]}"
    template = copy.deepcopy(gateway["spec"]["template"])
    spec = template["spec"]
    container = next(item for item in spec["containers"] if item["name"] == "gateway")
    container.pop("ports", None)
    for field in ("readinessProbe", "livenessProbe", "startupProbe"):
        container.pop(field, None)
    container["name"] = "deploy"
    container["command"] = ["python", "-m", "sage_run", "deploy-in-cluster", "--ref", ref]
    container.setdefault("env", []).append({"name": "SAGE_RUN_DEPLOY_JOB", "value": name})
    container.pop("args", None)
    spec["containers"] = [container]
    spec.pop("initContainers", None)
    spec["serviceAccountName"] = "sage-run-deployer"
    spec["restartPolicy"] = "Never"
    for mount in container.get("volumeMounts", []):
        if mount["name"] == "workflow-repo":
            mount["readOnly"] = False
    environment = {item["name"]: item.get("value", "") for item in container.get("env", [])}
    backup_path = environment.get("SAGE_RUN_BACKUP_HOST_PATH")
    if backup_path:
        spec.setdefault("volumes", []).append(
            {"name": "backups", "hostPath": {"path": backup_path, "type": "DirectoryOrCreate"}}
        )
        container.setdefault("volumeMounts", []).append(
            {"name": "backups", "mountPath": "/var/backups/sage-run/managed"}
        )
    if environment.get("SAGE_RUN_BACKUP_HINDSIGHT") == "true":
        spec.setdefault("volumes", []).append(
            {"name": "backup-hindsight", "persistentVolumeClaim": {"claimName": "hindsight-data", "readOnly": True}}
        )
        container.setdefault("volumeMounts", []).append(
            {"name": "backup-hindsight", "mountPath": "/var/lib/sage-run/backup-hindsight", "readOnly": True}
        )
    # hostPath and local-path PVCs must stay on the serving node.
    node = (gateway.get("metadata", {}).get("annotations") or {}).get("sage-run/node")
    if node:
        spec["nodeName"] = node
    template["metadata"] = {"labels": {DEPLOY_LABEL: "true"}}
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {DEPLOY_LABEL: "true"},
            "annotations": {REF_ANNOTATION: ref},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": 3600,
            "ttlSecondsAfterFinished": 604800,
            "template": template,
        },
    }


def job_status(job: dict) -> dict:
    status = job.get("status") or {}
    conditions = status.get("conditions") or []
    failed = next((item for item in conditions if item.get("type") == "Failed" and item.get("status") == "True"), None)
    complete = any(item.get("type") == "Complete" and item.get("status") == "True" for item in conditions)
    metadata = job["metadata"]
    return {
        "id": metadata["name"],
        "ref": (metadata.get("annotations") or {}).get(REF_ANNOTATION, ""),
        "status": "failed" if failed else "succeeded" if complete else "running" if status.get("active") else "pending",
        "started_at": status.get("startTime") or metadata.get("creationTimestamp"),
        "finished_at": status.get("completionTime") or (failed or {}).get("lastTransitionTime"),
        "error": (failed or {}).get("message") or (failed or {}).get("reason"),
        "commit": (metadata.get("annotations") or {}).get("sage-run/commit"),
        "phase": (metadata.get("annotations") or {}).get("sage-run/phase", "queued"),
    }
