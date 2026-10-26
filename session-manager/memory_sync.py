"""Object-store memory restore/upload helpers for task-local Kubernetes volumes."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import sys
import tarfile
from datetime import UTC, datetime
from pathlib import Path

from shared.lib.object_store import BUCKET_AGENT_MEMORY, download_bytes, upload_bytes

logger = logging.getLogger(__name__)
MEMORY_COMPLETE_MARKER = ".sage-run-memory-complete"


def _directory_has_files(path: Path) -> bool:
    return path.exists() and any(path.iterdir())


def _tar_directory(path: Path) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for item in sorted(path.rglob("*")):
            archive.add(item, arcname=str(item.relative_to(path)))
    buffer.seek(0)
    return buffer.read()


def _extract_archive_to_directory(archive_bytes: bytes, path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    target_root = path.resolve()
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        for member in archive.getmembers():
            member_path = (path / member.name).resolve()
            if not str(member_path).startswith(f"{target_root}{os.sep}") and member_path != target_root:
                raise ValueError(f"Unsafe path in memory archive: {member.name}")
            if member.isdir():
                member_path.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isreg():
                continue
            member_path.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, member_path.open("wb") as target:
                shutil.copyfileobj(source, target)


async def restore_memory_to_path(agent_name: str, path: Path) -> bool:
    """Restore one agent archive into a Kubernetes Job's task-local volume."""
    archive_bytes = download_bytes(BUCKET_AGENT_MEMORY, f"{agent_name}/latest.tar.gz")
    if archive_bytes is None:
        logger.info("No backup found for '%s' — first session", agent_name)
        return False
    _extract_archive_to_directory(archive_bytes, path)
    logger.info("Restored memory for '%s' into %s", agent_name, path)
    return True


async def backup_memory_from_path(agent_name: str, path: Path) -> bool:
    """Persist one Kubernetes Job's task-local memory volume."""
    if not _directory_has_files(path):
        logger.info("No memory to backup for '%s'", agent_name)
        return False
    archive_bytes = _tar_directory(path)
    upload_bytes(BUCKET_AGENT_MEMORY, f"{agent_name}/latest.tar.gz", archive_bytes, content_type="application/gzip")
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    upload_bytes(
        BUCKET_AGENT_MEMORY,
        f"{agent_name}/{timestamp}.tar.gz",
        archive_bytes,
        content_type="application/gzip",
    )
    logger.info("Backed up memory for '%s' from %s", agent_name, path)
    return True


async def _memory_helper_main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[1] not in {"restore", "wait-upload"}:
        print(
            "usage: python -m session_manager.memory_sync {restore|wait-upload} AGENT_NAME MEMORY_PATH",
            file=sys.stderr,
        )
        return 2
    action, agent_name, raw_path = argv[1:]
    path = Path(raw_path)
    if action == "restore":
        await restore_memory_to_path(agent_name, path)
        return 0
    marker = path / MEMORY_COMPLETE_MARKER
    while not marker.exists():
        await asyncio.sleep(1)
    marker.unlink(missing_ok=True)
    await backup_memory_from_path(agent_name, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_memory_helper_main(sys.argv)))
