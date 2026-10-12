"""Dedicated deterministic synchronization for registered Knowledge Sources."""

from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import delete, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from shared.lib.background_jobs import (
    BackgroundJobClaimError,
    claim_background_job,
    finish_background_job,
    heartbeat_background_job,
    start_background_job,
)
from shared.lib.config import settings
from shared.lib.github_app import GitHubAppError, github_git_auth_environment, github_installation_token
from shared.lib.knowledge_source_confluence import ConfluenceClient, ConfluenceSecurityError, stable_hash
from shared.lib.knowledge_source_embeddings import EmbeddingClient, EmbeddingOptions
from shared.lib.knowledge_source_graphify import (
    GRAPHIFY_VERSION,
    build_knowledge_source_bundle,
    run_graphify_code_extraction,
)
from shared.lib.knowledge_source_hybrid_index import (
    INDEXER_VERSION,
    HybridIndexOptions,
    build_hybrid_index,
    index_config_hash,
)
from shared.lib.knowledge_source_publication import (
    fail_knowledge_source_version,
    promote_knowledge_source_version,
    publish_knowledge_source_bundle,
)
from shared.lib.models import BackgroundJobRun, KnowledgeSource, KnowledgeSourceVersion, KnowledgeSourceVersionDocument
from shared.lib.object_store import ObjectStore
from shared.lib.platform_secrets import load_confluence_connections

KNOWLEDGE_SOURCE_SYNC_JOB_TYPE = "knowledge_source_sync"
SUPPORTED_TRIGGERS = frozenset({"scheduled", "manual", "retry"})
_CONNECTION_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_GIT_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")


class KnowledgeSourceSyncError(RuntimeError):
    """Raised for a persisted Knowledge Source synchronization failure."""


class KnowledgeSourceBusyError(KnowledgeSourceSyncError):
    """Raised when another worker owns the source lock."""


@dataclass(frozen=True)
class KnowledgeSourceIndexerConfig:
    cache_root: Path
    object_store_bucket: str
    graphify_binary: str = "graphify"
    graphify_timeout_sec: int = 1800

    @classmethod
    def from_settings(cls) -> KnowledgeSourceIndexerConfig:
        return cls(
            cache_root=Path(settings.knowledge_source_indexer_cache_root).expanduser(),
            object_store_bucket=settings.knowledge_source_object_store_bucket.strip(),
            graphify_binary=settings.knowledge_source_graphify_binary.strip(),
            graphify_timeout_sec=int(settings.knowledge_source_graphify_timeout_sec),
        )

    def validate(self) -> None:
        if not self.object_store_bucket:
            raise KnowledgeSourceSyncError("KNOWLEDGE_SOURCE_OBJECT_STORE_BUCKET must be configured")
        if not self.graphify_binary:
            raise KnowledgeSourceSyncError("KNOWLEDGE_SOURCE_GRAPHIFY_BINARY must be configured")
        if self.graphify_timeout_sec <= 0:
            raise KnowledgeSourceSyncError("Knowledge Source Graphify timeout must be positive")


@dataclass(frozen=True)
class KnowledgeSourceSyncResult:
    status: str
    source_id: uuid.UUID
    version_id: uuid.UUID
    run_id: uuid.UUID
    commit_sha: str

    @property
    def source_revision(self) -> str:
        return self.commit_sha


def extraction_config_hash(source: KnowledgeSource) -> str:
    """Hash every extraction input that can change immutable output identity."""
    payload = {
        "schema_version": 2,
        "graphify_version": GRAPHIFY_VERSION,
        "include_paths": list(source.include_paths or []),
        "exclude_paths": list(source.exclude_paths or []),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


def resolve_knowledge_source_credential(
    credential_ref: str | None,
    *,
    platform_config_file: str | None = None,
    age_identity: str | None = None,
) -> str:
    """Resolve the registry's exact GitHub App connection reference."""
    if not credential_ref:
        return ""
    if not _CONNECTION_NAME_RE.fullmatch(credential_ref):
        raise KnowledgeSourceSyncError("Knowledge Source credential_ref must be a GitHub connection name")
    try:
        return github_installation_token(
            credential_ref,
            platform_config_file=platform_config_file or settings.platform_config_file,
            age_identity=age_identity if age_identity is not None else settings.age_identity or None,
        )
    except GitHubAppError as exc:
        raise KnowledgeSourceSyncError(str(exc)) from exc


def prepare_repository_snapshot(
    source: KnowledgeSource,
    cache_root: Path,
    credential_resolver: Callable[[str | None], str] = resolve_knowledge_source_credential,
) -> tuple[Path, str]:
    """Fetch one exact ref and materialize only its configured source scope."""
    repository_url = _validated_repository_url(source)
    ref = _validated_git_ref(source.default_ref)
    git_binary = shutil.which("git")
    if not git_binary:
        raise KnowledgeSourceSyncError("git is required by the Knowledge Source indexer")

    source_root = cache_root / str(source.id)
    repository_dir = source_root / "repository"
    snapshot_dir = source_root / "source"
    repository_dir.parent.mkdir(parents=True, exist_ok=True)
    credential = credential_resolver(source.credential_ref)
    with github_git_auth_environment(credential) as git_environment:
        if not (repository_dir / ".git").is_dir():
            shutil.rmtree(repository_dir, ignore_errors=True)
            repository_dir.mkdir(parents=True)
            _run_git(git_binary, repository_dir, git_environment, "init")
            _run_git(git_binary, repository_dir, git_environment, "remote", "add", "origin", repository_url)
        else:
            _run_git(git_binary, repository_dir, git_environment, "remote", "set-url", "origin", repository_url)
        _run_git(git_binary, repository_dir, git_environment, "fetch", "--force", "--prune", "origin", ref)
        commit_sha = _run_git(
            git_binary,
            repository_dir,
            git_environment,
            "rev-parse",
            "--verify",
            "FETCH_HEAD^{commit}",
        )
        if not re.fullmatch(r"[0-9a-f]{40}", commit_sha):
            raise KnowledgeSourceSyncError("git did not resolve the Knowledge Source ref to a commit SHA")
        _run_git(git_binary, repository_dir, git_environment, "checkout", "--force", "--detach", commit_sha)
        _run_git(git_binary, repository_dir, git_environment, "clean", "-ffdqx")

    _materialize_source_snapshot(
        repository_dir,
        snapshot_dir,
        include_paths=list(source.include_paths or []),
        exclude_paths=list(source.exclude_paths or []),
    )
    return snapshot_dir, commit_sha


async def run_knowledge_source_sync(
    engine: AsyncEngine,
    *,
    source_id: uuid.UUID,
    trigger: str,
    queued_run_id: uuid.UUID | None = None,
    config: KnowledgeSourceIndexerConfig | None = None,
    object_store: ObjectStore | None = None,
) -> KnowledgeSourceSyncResult:
    """Run the single scheduled/manual/retry handler under a per-source lock."""
    if trigger not in SUPPORTED_TRIGGERS:
        raise ValueError(f"Unsupported Knowledge Source sync trigger: {trigger}")
    active_config = config or KnowledgeSourceIndexerConfig.from_settings()
    lock_key = int.from_bytes(source_id.bytes[:8], byteorder="big", signed=True)

    async with engine.connect() as connection:
        acquired = bool(await connection.scalar(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key}))
        await connection.commit()
        if not acquired:
            raise KnowledgeSourceBusyError(f"Knowledge Source {source_id} is already synchronizing")
        session = AsyncSession(bind=connection, expire_on_commit=False)
        try:
            return await _run_locked_sync(
                session,
                source_id=source_id,
                trigger=trigger,
                queued_run_id=queued_run_id,
                config=active_config,
                object_store=object_store,
            )
        finally:
            await session.close()
            await connection.execute(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})
            await connection.commit()


async def _run_locked_sync(
    session: AsyncSession,
    *,
    source_id: uuid.UUID,
    trigger: str,
    queued_run_id: uuid.UUID | None,
    config: KnowledgeSourceIndexerConfig,
    object_store: ObjectStore | None,
) -> KnowledgeSourceSyncResult:
    source = await session.get(KnowledgeSource, source_id)
    if queued_run_id is not None:
        try:
            run = await claim_background_job(session, queued_run_id)
        except BackgroundJobClaimError as exc:
            raise KnowledgeSourceBusyError(str(exc)) from exc
        if (
            run.job_type != KNOWLEDGE_SOURCE_SYNC_JOB_TYPE
            or run.knowledge_source_id != source_id
            or run.trigger != trigger
        ):
            await finish_background_job(
                session,
                run.id,
                status="failed",
                summary={"failure_phase": "claim"},
                error="Queued Knowledge Source request does not match worker claim",
            )
            raise KnowledgeSourceSyncError("Queued Knowledge Source request does not match worker claim")
    else:
        if source is None:
            raise KnowledgeSourceSyncError(f"Knowledge Source {source_id} does not exist")
        run = await start_background_job(
            session,
            job_type=KNOWLEDGE_SOURCE_SYNC_JOB_TYPE,
            scope=source.canonical_alias,
            trigger=trigger,
            knowledge_source_id=source.id,
            summary={"phase": "resolve_ref"},
        )
    if source is None or not source.enabled:
        label = source.canonical_alias if source is not None else str(source_id)
        await finish_background_job(
            session,
            run.id,
            status="failed",
            summary={"failure_phase": "claim"},
            error=f"Knowledge Source {label!r} is unavailable or disabled",
        )
        raise KnowledgeSourceSyncError(f"Knowledge Source {label!r} is unavailable or disabled")
    if (source.source_kind, source.index_kind) == ("confluence", "hybrid_vector"):
        return await _run_locked_hybrid_sync(session, source=source, run=run)
    phase = "resolve_ref"
    phase_started = time.monotonic()
    phase_timings: dict[str, float] = {}
    version: KnowledgeSourceVersion | None = None
    commit_sha = ""
    try:
        if (source.source_kind, source.index_kind) != ("github", "code_graph"):
            raise KnowledgeSourceSyncError("Unsupported Knowledge Source source/index pair")
        config.validate()
        config.cache_root.mkdir(parents=True, exist_ok=True)
        snapshot_dir, commit_sha = await asyncio.to_thread(prepare_repository_snapshot, source, config.cache_root)
        phase_timings[phase] = _elapsed(phase_started)
        config_hash = extraction_config_hash(source)
        existing = await session.scalar(
            select(KnowledgeSourceVersion).where(
                KnowledgeSourceVersion.source_id == source.id,
                KnowledgeSourceVersion.commit_sha == commit_sha,
                KnowledgeSourceVersion.graphify_version == GRAPHIFY_VERSION,
                KnowledgeSourceVersion.extraction_config_hash == config_hash,
            )
        )
        if existing is not None and existing.status == "succeeded":
            completed_at = datetime.now(UTC)
            source.current_successful_version_id = existing.id
            run.knowledge_source_version_id = existing.id
            run.status = "skipped"
            run.heartbeat_at = completed_at
            run.finished_at = completed_at
            run.duration_sec = max(0.0, (completed_at - run.started_at).total_seconds())
            run.summary = {
                "commit_sha": commit_sha,
                "skip_reason": "unchanged_commit_and_config",
                "phase_timings_sec": phase_timings,
            }
            await session.commit()
            return KnowledgeSourceSyncResult("skipped", source.id, existing.id, run.id, commit_sha)

        version = existing or KnowledgeSourceVersion(
            source_id=source.id,
            commit_sha=commit_sha,
            graphify_version=GRAPHIFY_VERSION,
            extraction_config_hash=config_hash,
        )
        version.status = "running"
        version.started_at = datetime.now(UTC)
        version.finished_at = None
        version.error = None
        session.add(version)
        await session.flush()
        run.knowledge_source_version_id = version.id
        await session.commit()

        phase = "extract"
        phase_started = time.monotonic()
        await heartbeat_background_job(
            session,
            run.id,
            summary={"phase": phase, "commit_sha": commit_sha, "phase_timings_sec": phase_timings},
        )
        working_root = config.cache_root / str(source.id) / "graphify"
        graphify = await asyncio.to_thread(
            run_graphify_code_extraction,
            snapshot_dir,
            working_root,
            graphify_binary=config.graphify_binary,
            timeout_sec=config.graphify_timeout_sec,
        )
        phase_timings[phase] = _elapsed(phase_started)

        phase = "bundle"
        phase_started = time.monotonic()
        await heartbeat_background_job(
            session,
            run.id,
            summary={"phase": phase, "commit_sha": commit_sha, "phase_timings_sec": phase_timings},
        )
        staging_root = config.cache_root / str(source.id) / "staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f"{version.id}-", dir=staging_root) as temporary_dir:
            bundle = await asyncio.to_thread(
                build_knowledge_source_bundle,
                source_id=str(source.id),
                canonical_alias=source.canonical_alias,
                repository_url=source.repository_url,
                commit_sha=commit_sha,
                source_dir=snapshot_dir,
                graphify=graphify,
                bundle_dir=Path(temporary_dir) / "bundle",
                include_paths=list(source.include_paths or []),
                exclude_paths=list(source.exclude_paths or []),
                extraction_config_hash=config_hash,
                extraction_stdout=graphify.stdout,
                extraction_stderr=graphify.stderr,
            )
            phase_timings[phase] = _elapsed(phase_started)
            phase = "publish"
            phase_started = time.monotonic()
            await heartbeat_background_job(
                session,
                run.id,
                summary={"phase": phase, "commit_sha": commit_sha, "phase_timings_sec": phase_timings},
            )
            publication = await asyncio.to_thread(
                publish_knowledge_source_bundle,
                bundle,
                bucket=config.object_store_bucket,
                object_store=object_store,
            )
            phase_timings[phase] = _elapsed(phase_started)
            version.source_revision = commit_sha
            version.indexer_version = GRAPHIFY_VERSION
            version.index_config_hash = config_hash
            version.index_kind = "code_graph"
            version.stats = {
                "file_count": bundle.file_count,
                "node_count": bundle.node_count,
                "edge_count": bundle.edge_count,
            }
            await promote_knowledge_source_version(
                session,
                source_id=source.id,
                version_id=version.id,
                run_id=run.id,
                publication=publication,
                file_count=bundle.file_count,
                node_count=bundle.node_count,
                edge_count=bundle.edge_count,
                phase_timings=phase_timings,
            )
        return KnowledgeSourceSyncResult("succeeded", source.id, version.id, run.id, commit_sha)
    except Exception as exc:
        phase_timings[phase] = _elapsed(phase_started)
        error = str(exc)[-4000:] or exc.__class__.__name__
        if version is None:
            await finish_background_job(
                session,
                run.id,
                status="failed",
                summary={
                    "commit_sha": commit_sha,
                    "failure_phase": phase,
                    "phase_timings_sec": phase_timings,
                },
                error=error,
            )
        else:
            await fail_knowledge_source_version(
                session,
                source_id=source.id,
                version_id=version.id,
                run_id=run.id,
                failure_phase=phase,
                error=error,
                phase_timings=phase_timings,
            )
        raise KnowledgeSourceSyncError(
            f"Knowledge Source {source.canonical_alias!r} failed during {phase}: {error}"
        ) from exc


def _hybrid_source_config_hash(source: KnowledgeSource) -> str:
    return stable_hash(
        {
            "source_kind": source.source_kind,
            "index_kind": source.index_kind,
            "source_config": source.source_config,
            "credential_ref": source.credential_ref,
        }
    )


async def _run_locked_hybrid_sync(
    session: AsyncSession,
    *,
    source: KnowledgeSource,
    run: BackgroundJobRun,
) -> KnowledgeSourceSyncResult:
    source_id, run_id, alias = source.id, run.id, source.canonical_alias
    captured_hash = _hybrid_source_config_hash(source)
    captured_updated_at = source.updated_at
    version_id: uuid.UUID | None = None
    phase = "configure"
    started = time.monotonic()
    phase_timings: dict[str, float] = {}
    revision = ""
    try:
        connections = await asyncio.to_thread(
            load_confluence_connections,
            settings.platform_config_file,
            identity=settings.age_identity,
        )
        connection = connections.get(source.credential_ref or "")
        if connection is None or not connection.token.strip():
            raise KnowledgeSourceSyncError("Confluence connection or decrypted token is missing")
        embedding_options = EmbeddingOptions.from_settings(settings)
        options = HybridIndexOptions(
            max_pages=settings.knowledge_source_max_pages,
            max_chunks=settings.knowledge_source_max_chunks,
            concurrency=settings.knowledge_source_fetch_concurrency,
            lexical_config=(source.source_config or {}).get("lexical_config", "simple"),
        )
        heartbeat_lock = asyncio.Lock()
        last_heartbeat = time.monotonic()

        async def heartbeat() -> None:
            nonlocal last_heartbeat
            async with heartbeat_lock:
                if time.monotonic() - last_heartbeat < 10:
                    return
                await heartbeat_background_job(session, run_id, summary={"phase": phase})
                last_heartbeat = time.monotonic()

        async with httpx.AsyncClient() as client:
            embeddings = EmbeddingClient(embedding_options, client)
            confluence = ConfluenceClient(
                connection,
                client,
                concurrency=options.concurrency,
                max_pages=options.max_pages,
                max_body_chars=options.max_body_chars,
                timeout_sec=settings.knowledge_source_request_timeout_sec,
                retries=settings.knowledge_source_request_retries,
                heartbeat=heartbeat,
            )
            version_id = uuid.uuid4()
            version = KnowledgeSourceVersion(
                id=version_id,
                source_id=source_id,
                source_revision=f"pending:{version_id}",
                index_kind="hybrid_vector",
                indexer_version=INDEXER_VERSION,
                index_config_hash=index_config_hash(options, embeddings),
                status="pending",
                started_at=datetime.now(UTC),
            )
            session.add(version)
            await session.flush()
            run.knowledge_source_version_id = version_id
            run.summary = {"phase": "build"}
            await session.commit()
            phase_timings[phase] = _elapsed(started)
            phase, started = "build", time.monotonic()
            build = await build_hybrid_index(
                session,
                source,
                version,
                connection,
                client,
                embeddings,
                options=options,
                confluence=confluence,
                heartbeat=heartbeat,
            )
        phase_timings[phase] = _elapsed(started)
        revision = build.source_revision
        phase, started = "promote", time.monotonic()
        current = await session.scalar(
            select(KnowledgeSource)
            .where(KnowledgeSource.id == source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            current is None
            or not current.enabled
            or current.updated_at != captured_updated_at
            or _hybrid_source_config_hash(current) != captured_hash
        ):
            raise KnowledgeSourceSyncError("Knowledge Source was disabled or edited during synchronization")
        existing = await session.scalar(
            select(KnowledgeSourceVersion).where(
                KnowledgeSourceVersion.source_id == source_id,
                KnowledgeSourceVersion.index_kind == "hybrid_vector",
                KnowledgeSourceVersion.source_revision == revision,
                KnowledgeSourceVersion.index_config_hash == build.index_config_hash,
                KnowledgeSourceVersion.id != version_id,
            )
        )
        skipped = existing is not None and existing.status == "succeeded"
        if existing is not None:
            run.knowledge_source_version_id = existing.id
            await session.flush()
            if skipped:
                await session.execute(
                    delete(KnowledgeSourceVersionDocument).where(
                        KnowledgeSourceVersionDocument.version_id == version_id
                    )
                )
            else:
                await session.execute(
                    delete(KnowledgeSourceVersionDocument).where(
                        KnowledgeSourceVersionDocument.version_id == existing.id
                    )
                )
                await session.execute(
                    update(KnowledgeSourceVersionDocument)
                    .where(KnowledgeSourceVersionDocument.version_id == version_id)
                    .values(version_id=existing.id)
                )
            await session.delete(version)
            await session.flush()
            version = existing
        if not skipped:
            version.source_revision = revision
            version.index_config_hash = build.index_config_hash
            version.indexer_version = build.indexer_version
            version.stats = build.stats
            version.warnings = list(build.warnings)
            version.status = "succeeded"
            version.error = None
            version.finished_at = datetime.now(UTC)
        current.current_successful_version_id = version.id
        current.serving_suspended_at = None
        current.serving_suspension_reason = None
        phase_timings[phase] = _elapsed(started)
        result = KnowledgeSourceSyncResult(
            "skipped" if skipped else "succeeded", source_id, version.id, run_id, revision
        )
        summary = {"source_revision": revision, "stats": build.stats, "phase_timings_sec": phase_timings}
        if skipped:
            summary["skip_reason"] = "unchanged_revision_and_config"
        await finish_background_job(
            session,
            run_id,
            status=result.status,
            knowledge_source_version_id=version.id,
            summary=summary,
            warnings=list(build.warnings),
        )
        return result
    except Exception as exc:
        phase_timings[phase] = _elapsed(started)
        error = str(exc)[-4000:] or exc.__class__.__name__
        await session.rollback()
        current = await session.scalar(
            select(KnowledgeSource)
            .where(KnowledgeSource.id == source_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            isinstance(exc, ConfluenceSecurityError)
            and current is not None
            and current.updated_at == captured_updated_at
            and _hybrid_source_config_hash(current) == captured_hash
        ):
            current.serving_suspended_at = datetime.now(UTC)
            current.serving_suspension_reason = error
        if version_id is not None:
            failed = await session.get(KnowledgeSourceVersion, version_id, populate_existing=True)
            if failed is not None:
                await session.execute(
                    delete(KnowledgeSourceVersionDocument).where(
                        KnowledgeSourceVersionDocument.version_id == version_id
                    )
                )
                failed.status = "failed"
                failed.finished_at = datetime.now(UTC)
                failed.error = error
        await finish_background_job(
            session,
            run_id,
            status="failed",
            summary={"source_revision": revision, "failure_phase": phase, "phase_timings_sec": phase_timings},
            error=error,
        )
        raise KnowledgeSourceSyncError(f"Knowledge Source {alias!r} failed during {phase}: {error}") from exc


def _validated_repository_url(source: KnowledgeSource) -> str:
    value = source.repository_url.strip()
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise KnowledgeSourceSyncError("Knowledge Source repository_url must be credential-free HTTPS")
    return value


def _validated_git_ref(value: str) -> str:
    ref = value.strip()
    if not _GIT_REF_RE.fullmatch(ref) or ".." in ref or "//" in ref or ref.endswith(("/", ".")) or "/." in ref:
        raise KnowledgeSourceSyncError("Knowledge Source default_ref has invalid Git ref syntax")
    return ref


def _run_git(git_binary: str, repository_dir: Path, environment: Mapping[str, str], *arguments: str) -> str:
    try:
        completed = subprocess.run(  # noqa: S603 - arguments are indexer-owned and validated.
            [git_binary, "-C", str(repository_dir), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=300,
            env=dict(environment),
        )
    except subprocess.TimeoutExpired as exc:
        raise KnowledgeSourceSyncError(f"git {arguments[0]} timed out") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or f"git {arguments[0]} failed").strip()
        raise KnowledgeSourceSyncError(detail[-2000:]) from exc
    except OSError as exc:
        raise KnowledgeSourceSyncError(f"Could not execute git: {exc}") from exc
    return completed.stdout.strip()


def _materialize_source_snapshot(
    repository_dir: Path,
    snapshot_dir: Path,
    *,
    include_paths: list[str],
    exclude_paths: list[str],
) -> None:
    temporary_dir = snapshot_dir.with_name(f".{snapshot_dir.name}-{uuid.uuid4().hex}")
    temporary_dir.mkdir(parents=True)
    try:
        for path in repository_dir.rglob("*"):
            if path.is_symlink() or not path.is_file():
                continue
            relative_path = path.relative_to(repository_dir).as_posix()
            if ".git" in Path(relative_path).parts:
                continue
            included = not include_paths or any(
                fnmatch.fnmatchcase(relative_path, pattern) for pattern in include_paths
            )
            excluded = any(fnmatch.fnmatchcase(relative_path, pattern) for pattern in exclude_paths)
            if not included or excluded:
                continue
            destination = temporary_dir / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        shutil.rmtree(snapshot_dir, ignore_errors=True)
        temporary_dir.replace(snapshot_dir)
    except Exception:
        shutil.rmtree(temporary_dir, ignore_errors=True)
        raise


def _elapsed(started_at: float) -> float:
    return round(max(0.0, time.monotonic() - started_at), 6)
