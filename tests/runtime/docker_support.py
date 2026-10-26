"""Docker execution and volume helpers used only by runtime scenario tests."""

from __future__ import annotations

import io
import logging
import os
import sys
import tarfile
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import docker
from docker.errors import DockerException
from session_manager.runtime_launchers import (
    RuntimeHandle as BaseRuntimeHandle,
)
from session_manager.runtime_launchers import (
    RuntimeLaunchSpec as BaseRuntimeLaunchSpec,
)
from session_manager.runtime_launchers import (
    RuntimeSessionStatus,
    _environment_with_bundle_contract,
    _sandbox_profile,
)

from shared.lib.object_store import BUCKET_AGENT_MEMORY, download_file, upload_file

logger = logging.getLogger(__name__)
DEFAULT_DOCKER_NETWORK = "sage-run-test-network"
MEMORY_HELPER_IMAGE = "sage-run-agent-runtime:latest"
MEMORY_HELPER_PATH = "/memory"
_docker_client: docker.DockerClient | None = None


@dataclass(frozen=True)
class RuntimeLaunchSpec(BaseRuntimeLaunchSpec):
    plugin_dir: str | None = None
    shared_dir: str | None = None


@dataclass(frozen=True)
class RuntimeHandle(BaseRuntimeHandle):
    raw: Any = None

    def _require_raw(self) -> Any:
        if self.raw is None:
            raise AttributeError(
                f"RuntimeHandle for provider {self.provider!r} does not expose container-style methods"
            )
        return self.raw

    def wait(self, *args: Any, **kwargs: Any) -> Any:
        return self._require_raw().wait(*args, **kwargs)

    def logs(self, *args: Any, **kwargs: Any) -> Any:
        return self._require_raw().logs(*args, **kwargs)

    def remove(self, *args: Any, **kwargs: Any) -> Any:
        return self._require_raw().remove(*args, **kwargs)

    def kill(self, *args: Any, **kwargs: Any) -> Any:
        return self._require_raw().kill(*args, **kwargs)


def _get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def _docker_network() -> str:
    return os.environ.get("DOCKER_NETWORK", DEFAULT_DOCKER_NETWORK).strip() or DEFAULT_DOCKER_NETWORK


def _network_peer_hosts(client: docker.DockerClient, network_name: str) -> dict[str, str]:
    hosts: dict[str, str] = {}
    network = client.networks.get(network_name)
    for container in sorted(network.containers, key=lambda peer: peer.name):
        endpoint = container.attrs.get("NetworkSettings", {}).get("Networks", {}).get(network_name, {})
        address = str(endpoint.get("IPAddress", "")).strip()
        if not address:
            continue
        for name in endpoint.get("DNSNames") or []:
            if isinstance(name, str) and name and not any(character.isspace() for character in name):
                hosts[name] = address
    return hosts


class DockerRuntimeLauncher:
    provider = "docker"

    def __init__(self, client: docker.DockerClient | None = None, *, workflow_root: Path | None = None) -> None:
        self.client = client or _get_docker_client()
        self.workflow_root = workflow_root

    def _cleanup_stale_container_name(self, container_name: str) -> None:
        try:
            existing = self.client.containers.get(container_name)
        except docker.errors.NotFound:
            return

        status = getattr(existing, "status", None)
        if status == "running":
            raise DockerException(f"Container name {container_name} is already in use by a running container")

        logger.info("Removing stale container %s before retry", container_name)
        existing.remove(force=True)

    def launch(self, spec: BaseRuntimeLaunchSpec) -> RuntimeHandle:
        if not isinstance(spec, RuntimeLaunchSpec):
            spec = RuntimeLaunchSpec(
                **vars(spec),
                plugin_dir=str(self.workflow_root / "workflows" / spec.workflow) if self.workflow_root else None,
                shared_dir=str(self.workflow_root / "shared") if self.workflow_root else None,
            )
        volumes: dict[str, dict[str, str]] = {}
        mounted_bundle_path = "/workflow-bundle" if spec.workflow_bundle_path else None
        if spec.workflow_bundle_path:
            volumes[spec.workflow_bundle_path] = {"bind": mounted_bundle_path, "mode": "ro"}
        elif spec.plugin_dir:
            volumes[spec.plugin_dir] = {"bind": "/plugin-src", "mode": "ro"}
        if spec.shared_dir and not spec.workflow_bundle_path:
            volumes[spec.shared_dir] = {"bind": "/shared", "mode": "ro"}
        if spec.memory_volume_name:
            volumes[spec.memory_volume_name] = {"bind": "/memory", "mode": "rw"}

        container_name = spec.container_name or f"session-{spec.task_id[:8]}-{spec.workflow}"
        self._cleanup_stale_container_name(container_name)
        run_kwargs = {
            "image": spec.image,
            "environment": _environment_with_bundle_contract(spec, mounted_bundle_path=mounted_bundle_path),
            "volumes": volumes,
            "network": _docker_network(),
            "detach": True,
            "name": container_name,
            "labels": {
                "sage_run.task_id": spec.task_id,
                "sage_run.workflow": spec.workflow,
                "sage_run.type": "agent-session",
                "sage_run.runtime_provider": self.provider,
            },
        }
        if sys.platform == "linux":
            run_kwargs["extra_hosts"] = {"host.docker.internal": "host-gateway"}
        sandbox_profile = _sandbox_profile()
        if sandbox_profile == "local":
            run_kwargs["security_opt"] = ["seccomp=unconfined"]
            run_kwargs["environment"]["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] = "1"
        elif sandbox_profile == "ci":
            run_kwargs["security_opt"] = ["seccomp=unconfined", "apparmor=unconfined"]
            run_kwargs["cap_add"] = ["SYS_ADMIN"]
            run_kwargs["environment"]["CLAUDE_SANDBOX_ENABLE_WEAKER_NESTED"] = "1"
        elif sandbox_profile == "gvisor":
            run_kwargs["runtime"] = os.environ.get("TEST_GVISOR_DOCKER_RUNTIME", "runsc")
            run_kwargs.setdefault("extra_hosts", {}).update(_network_peer_hosts(self.client, run_kwargs["network"]))

        container = self.client.containers.run(**run_kwargs)
        return RuntimeHandle(
            id=container.id,
            short_id=container.short_id,
            provider=self.provider,
            task_id=spec.task_id,
            workflow=spec.workflow,
            raw=container,
        )

    def list_sessions(self) -> list[RuntimeSessionStatus]:
        containers = self.client.containers.list(all=True, filters={"label": "sage_run.type=agent-session"})
        statuses: list[RuntimeSessionStatus] = []
        for container in containers:
            task_id = container.labels.get("sage_run.task_id", "")
            workflow = container.labels.get("sage_run.workflow", "")
            exit_code = None
            logs = ""
            if container.status == "exited":
                exit_code = container.attrs.get("State", {}).get("ExitCode", -1)
                logs = container.logs(tail=200).decode("utf-8", errors="replace")
            statuses.append(
                RuntimeSessionStatus(
                    id=container.id,
                    short_id=container.short_id,
                    provider=self.provider,
                    task_id=task_id,
                    workflow=workflow,
                    status=container.status,
                    exit_code=exit_code,
                    logs=logs,
                    raw=container,
                )
            )
        return statuses

    def cleanup_session(self, status: RuntimeSessionStatus) -> None:
        container = status.raw or self.client.containers.get(status.id)
        container.remove(force=True)

    def cancel(self, runtime_id: str | None = None, *, task_id: str | None = None) -> bool:
        containers = []
        if runtime_id:
            try:
                containers = [self.client.containers.get(runtime_id)]
            except docker.errors.NotFound:
                return False
        elif task_id:
            containers = self.client.containers.list(all=True, filters={"label": f"sage_run.task_id={task_id}"})
        else:
            return False

        removed = False
        for container in containers:
            if container.status == "running":
                container.stop(timeout=5)
            container.remove(force=True)
            removed = True
        return removed


def _get_volume_name(agent_name: str) -> str:
    return f"agent-memory-{agent_name}"


def _create_memory_helper(volume_name: str, *, mode: str):
    client = _get_docker_client()
    helper_name = f"memory-helper-{volume_name}-{datetime.now(UTC).strftime('%Y%m%d%H%M%S%f')}"
    container = client.containers.create(
        image=MEMORY_HELPER_IMAGE,
        command=["sh", "-lc", "sleep 600"],
        name=helper_name,
        detach=True,
        volumes={volume_name: {"bind": MEMORY_HELPER_PATH, "mode": mode}},
        labels={"sage-run.memory-helper": "true"},
    )
    container.start()
    return container


def _helper_has_memory_files(container) -> bool:
    result = container.exec_run(["sh", "-lc", f"find {MEMORY_HELPER_PATH} -mindepth 1 -print -quit"])
    output = (
        result.output.decode("utf-8", errors="ignore")
        if isinstance(result.output, (bytes, bytearray))
        else str(result.output)
    )
    return result.exit_code == 0 and bool(output.strip())


def _stream_to_bytes(stream) -> bytes:
    return b"".join(chunk for chunk in stream)


def _normalize_archive(raw_archive: bytes) -> bytes:
    source_buffer = io.BytesIO(raw_archive)
    normalized_buffer = io.BytesIO()

    with (
        tarfile.open(fileobj=source_buffer, mode="r:") as source_tar,
        tarfile.open(fileobj=normalized_buffer, mode="w:") as normalized_tar,
    ):
        for member in source_tar.getmembers():
            parts = [part for part in member.name.split("/") if part not in {"", "."}]
            if len(parts) <= 1:
                continue

            member.name = "/".join(parts[1:])
            file_obj = source_tar.extractfile(member) if member.isfile() else None
            normalized_tar.addfile(member, fileobj=file_obj)
            if file_obj is not None:
                file_obj.close()

    normalized_buffer.seek(0)
    return normalized_buffer.read()


async def backup_memory(agent_name: str) -> bool:
    """Backup agent memory volume to MinIO after session completion.

    Creates both a 'latest' and a timestamped version for history.
    """
    volume_name = _get_volume_name(agent_name)
    helper = None
    tar_path: str | None = None

    try:
        helper = _create_memory_helper(volume_name, mode="ro")
        if not _helper_has_memory_files(helper):
            logger.info("No memory to backup for agent '%s'", agent_name)
            return False

        raw_archive_stream, _ = helper.get_archive(MEMORY_HELPER_PATH)
        normalized_archive = _normalize_archive(_stream_to_bytes(raw_archive_stream))
        if not normalized_archive:
            logger.info("No memory to backup for agent '%s'", agent_name)
            return False

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tar_path = tmp.name

        with (
            tarfile.open(tar_path, mode="w:gz") as archive,
            tarfile.open(fileobj=io.BytesIO(normalized_archive), mode="r:") as normalized_tar,
        ):
            for member in normalized_tar.getmembers():
                file_obj = normalized_tar.extractfile(member) if member.isfile() else None
                archive.addfile(member, fileobj=file_obj)
                if file_obj is not None:
                    file_obj.close()

        # Upload as latest
        upload_file(BUCKET_AGENT_MEMORY, f"{agent_name}/latest.tar.gz", tar_path)

        # Upload timestamped version
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        upload_file(BUCKET_AGENT_MEMORY, f"{agent_name}/{timestamp}.tar.gz", tar_path)

        file_size = os.path.getsize(tar_path)
        logger.info("Backed up memory for '%s' to MinIO (%d bytes)", agent_name, file_size)
        return True

    except Exception:
        logger.exception("Failed to backup memory for '%s'", agent_name)
        return False
    finally:
        if helper is not None:
            try:
                helper.remove(force=True)
            except Exception:
                logger.warning("Failed to remove memory helper for '%s'", agent_name)
        # Cleanup temp file
        if tar_path and os.path.exists(tar_path):
            os.unlink(tar_path)


async def restore_memory(agent_name: str) -> bool:
    """Restore agent memory from MinIO if Docker volume is empty.

    Called before spawning a new session. If the volume already has data,
    this is a no-op (data from the previous session is still there).
    """
    volume_name = _get_volume_name(agent_name)
    helper = None
    restore_path: str | None = None

    try:
        helper = _create_memory_helper(volume_name, mode="rw")
        if _helper_has_memory_files(helper):
            logger.debug("Memory volume for '%s' already has data, skipping restore", agent_name)
            return False

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            restore_path = tmp.name

        # Download latest backup from MinIO
        found = download_file(BUCKET_AGENT_MEMORY, f"{agent_name}/latest.tar.gz", restore_path)
        if not found:
            logger.info("No backup found for '%s' — first session", agent_name)
            return False

        with tarfile.open(restore_path, mode="r:gz") as compressed_tar:
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w:") as plain_tar:
                for member in compressed_tar.getmembers():
                    file_obj = compressed_tar.extractfile(member) if member.isfile() else None
                    plain_tar.addfile(member, fileobj=file_obj)
                    if file_obj is not None:
                        file_obj.close()

        tar_buffer.seek(0)
        if not helper.put_archive(MEMORY_HELPER_PATH, tar_buffer.read()):
            logger.error("Failed to extract memory archive into volume for '%s'", agent_name)
            return False

        logger.info("Restored memory for '%s' from MinIO", agent_name)
        return True

    except Exception:
        logger.exception("Failed to restore memory for '%s'", agent_name)
        return False
    finally:
        if helper is not None:
            try:
                helper.remove(force=True)
            except Exception:
                logger.warning("Failed to remove restore helper for '%s'", agent_name)
        if restore_path and os.path.exists(restore_path):
            os.unlink(restore_path)
