"""Full recovery-set creation and independent nightly/deployment copy rotation."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

BACKUP_FORMAT = "sage-run-backup-v1"
KEEP = {"nightly": 7, "deployment": 3}


def checksum(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def prune_backups(root: Path, *, namespace: str, kind: str) -> None:
    """Only completed, owned sets in this exact category are eligible."""
    keep = KEEP[kind]
    eligible: list[tuple[str, Path]] = []
    for path in root.iterdir():
        manifest_path = path / "manifest.json"
        if path.is_symlink() or not path.is_dir() or not manifest_path.is_file():
            continue
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("format") == BACKUP_FORMAT
            and manifest.get("namespace") == namespace
            and manifest.get("kind") == kind
            and manifest.get("complete") is True
            and not manifest.get("protected")
        ):
            eligible.append((manifest["completed_at"], path))
    eligible.sort(key=lambda item: item[0], reverse=True)
    for _, path in eligible[keep:]:
        shutil.rmtree(path)
        print(f"Removed older {kind} backup {path.name}", flush=True)


def _export_objects(root: Path) -> dict:
    from minio import Minio

    from shared.lib.config import settings

    if settings.object_store_provider != "s3":
        raise ValueError("Full deployment backup currently requires the qualified S3-compatible object store")
    client = Minio(
        settings.object_store_endpoint,
        settings.object_store_access_key,
        settings.object_store_secret_key,
        secure=settings.object_store_secure,
    )
    inventory: dict = {}
    root.mkdir(mode=0o700)
    for bucket in client.list_buckets():
        before = {
            item.object_name: (item.etag, item.size)
            for item in client.list_objects(bucket.name, recursive=True)
            if item.object_name
        }
        objects = []
        for key, (etag, size) in before.items():
            filename = hashlib.sha256(f"{bucket.name}/{key}".encode()).hexdigest()
            target = root / filename
            response = client.get_object(bucket.name, key)
            try:
                if response.headers.get("ETag", "").strip('"') != etag:
                    raise ValueError(f"Object changed during backup: {bucket.name}/{key}")
                with target.open("wb") as output:
                    shutil.copyfileobj(response, output)
            finally:
                response.close()
                response.release_conn()
            if target.stat().st_size != size:
                raise ValueError(f"Object changed during backup: {bucket.name}/{key}")
            objects.append({"key": key, "file": filename, "sha256": checksum(target), "etag": etag, "size": size})
        after = {
            item.object_name: (item.etag, item.size)
            for item in client.list_objects(bucket.name, recursive=True)
            if item.object_name
        }
        if before != after:
            raise ValueError(f"Object-store bucket {bucket.name} changed during backup; retry after writes settle")
        inventory[bucket.name] = objects
    return inventory


def create_backup(*, namespace: str, kind: str, checkout: Path) -> Path:
    """Caller holds checkout_lock across backup, rotation and deployment."""
    from shared.lib.config import settings

    if kind not in KEEP:
        raise ValueError("Backup kind must be nightly or deployment")
    root = Path(os.environ.get("SAGE_RUN_BACKUP_ROOT", "/var/backups/sage-run/managed"))
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = root / f"{stamp}-{kind}-{uuid4().hex[:8]}"
    target.mkdir(mode=0o700)
    kubectl = [shutil.which("kubectl") or "kubectl", "-n", namespace]
    print(f"Creating {kind} recovery set {target.name}", flush=True)
    dump = target / "postgres.dump"
    with dump.open("wb") as output:
        subprocess.run(  # noqa: S603 - fixed kubectl invocation
            [*kubectl, "exec", "postgres-0", "--", "pg_dump", "-U", settings.pg_user, "-d", settings.pg_db, "-Fc"],
            stdout=output,
            check=True,
        )
    with dump.open("rb") as source:
        subprocess.run(  # noqa: S603 - validates the dump with the matching PostgreSQL tool
            [*kubectl, "exec", "-i", "postgres-0", "--", "pg_restore", "--list"],
            stdin=source,
            stdout=subprocess.DEVNULL,
            check=True,
        )
    inventory = _export_objects(target / "objects")
    (target / "objects.json").write_text(json.dumps(inventory, sort_keys=True), encoding="utf-8")
    hindsight = Path("/var/lib/sage-run/backup-hindsight")
    if os.environ.get("SAGE_RUN_BACKUP_HINDSIGHT") == "true":
        if not hindsight.is_dir():
            raise ValueError("Hindsight data mount is missing; refusing an incomplete backup")
        archive = target / "hindsight.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(hindsight, arcname="hindsight")
        with tarfile.open(archive, "r:gz") as tar:
            for member in tar:
                if member.isfile():
                    stream = tar.extractfile(member)
                    if stream is not None:
                        while stream.read(1024 * 1024):
                            pass
    for config in checkout.glob("platform-config*.yaml"):
        shutil.copyfile(config, target / config.name)
    subprocess.run(  # noqa: S603 - archive committed workflow history without copying Git credentials
        [
            shutil.which("git") or "git",
            "-c",
            f"safe.directory={checkout}",
            "-C",
            str(checkout),
            "bundle",
            "create",
            str(target / "workflow.bundle"),
            "--all",
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(  # noqa: S603 - verify the standalone Git recovery archive
        [
            shutil.which("git") or "git",
            "-c",
            f"safe.directory={checkout}",
            "-C",
            str(checkout),
            "bundle",
            "verify",
            str(target / "workflow.bundle"),
        ],
        check=True,
        capture_output=True,
    )
    with (target / "helm-values.json").open("w") as output:
        subprocess.run(  # noqa: S603 - release values contain encrypted rather than decrypted credentials
            [shutil.which("helm") or "helm", "get", "values", "sage-run", "-n", namespace, "--all", "-o", "json"],
            stdout=output,
            check=True,
        )
    files = {path.relative_to(target).as_posix(): checksum(path) for path in target.rglob("*") if path.is_file()}
    manifest = {
        "format": BACKUP_FORMAT,
        "namespace": namespace,
        "kind": kind,
        "completed_at": datetime.now(UTC).isoformat(),
        "complete": True,
        "platform_version": version("sage-run"),
        "source_commit": subprocess.run(  # noqa: S603 - fixed read-only Git command
            [
                shutil.which("git") or "git",
                "-c",
                f"safe.directory={checkout}",
                "-C",
                str(checkout),
                "rev-parse",
                "HEAD",
            ],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "consistency": "online pg_dump; object inventory checked for concurrent changes; no cross-service transaction",
        "files": files,
    }
    # Completion marker is published last; failed/in-progress sets cannot rotate good sets.
    temporary = target / "manifest.pending"
    temporary.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")
    temporary.replace(target / "manifest.json")
    prune_backups(root, namespace=namespace, kind=kind)
    print(f"Verified {kind} backup {target.name}; retained newest {KEEP[kind]} copies", flush=True)
    return target
