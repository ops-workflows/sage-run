from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text, update

from shared.lib.housekeeping import prune_knowledge_source_history
from shared.lib.models import (
    BackgroundJobRun,
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)

pytestmark = pytest.mark.asyncio

ANCHOR = datetime(2025, 1, 10, tzinfo=UTC)


async def _add_source(session, alias="documents"):
    source = KnowledgeSource(
        canonical_alias=alias,
        source_kind="confluence",
        index_kind="hybrid_vector",
        source_config={"root_page_ids": ["root"]},
    )
    session.add(source)
    await session.flush()
    return source


async def _add_version(session, source, index, status="succeeded", artifact_keys=None, index_config_hash="test-config"):
    version = KnowledgeSourceVersion(
        source_id=source.id,
        source_revision=f"revision-{index}",
        index_kind="hybrid_vector",
        indexer_version="test-indexer",
        index_config_hash=index_config_hash,
        status=status,
        artifact_keys=artifact_keys or {},
        created_at=ANCHOR + timedelta(minutes=index),
    )
    session.add(version)
    await session.flush()
    return version


async def _add_revision(session, source, external_id, versions=(), *, index_config_hashes=("test-config",)):
    revision = KnowledgeDocumentRevision(
        source_id=source.id,
        external_id=external_id,
        provider_revision="1",
        title=external_id,
        canonical_url=f"https://docs.example.com/pages/{external_id}",
        normalized_content=f"Content for {external_id}",
        content_hash=f"hash-{external_id}",
        created_at=ANCHOR,
    )
    session.add(revision)
    await session.flush()
    for index_config_hash in index_config_hashes:
        for ordinal in range(2):
            session.add(
                KnowledgeChunk(
                    document_revision_id=revision.id,
                    index_config_hash=index_config_hash,
                    ordinal=ordinal,
                    content=f"Chunk {ordinal} for {external_id}",
                    content_hash=f"chunk-{external_id}-{ordinal}",
                    estimated_tokens=5,
                    lexical_text=external_id,
                    search_vector=text("''::tsvector"),
                    embedding=[1.0, 0.0, 0.0],
                    embedding_model="test-embedding",
                    embedding_dimensions=3,
                )
            )
    for version in versions:
        session.add(
            KnowledgeSourceVersionDocument(
                version_id=version.id,
                document_revision_id=revision.id,
                external_id=external_id,
                root_page_id="root",
            )
        )
    await session.flush()
    return revision


async def test_retention_preserves_all_retained_memberships_and_cascades_orphan_chunks(db_session):
    source = await _add_source(db_session)
    versions = []
    revisions = []
    for index, status in enumerate(
        ("succeeded", "failed", "succeeded", "running", "pending", "succeeded", "succeeded")
    ):
        version = await _add_version(db_session, source, index, status)
        versions.append(version)
        revisions.append(await _add_revision(db_session, source, f"page-{index}", [version]))
    shared_revision = await _add_revision(db_session, source, "shared", [versions[0], versions[5]])
    await _add_revision(db_session, source, "failed-staging-orphan")
    source.current_successful_version_id = versions[2].id
    await db_session.commit()

    result = await prune_knowledge_source_history(db_session, keep_latest=2)

    assert result == (2, 0, [])
    assert set((await db_session.execute(select(KnowledgeSourceVersion.id))).scalars()) == {
        version.id for version in versions[2:]
    }
    retained_revision_ids = {revision.id for revision in revisions[2:]} | {shared_revision.id}
    assert set((await db_session.execute(select(KnowledgeDocumentRevision.id))).scalars()) == retained_revision_ids
    assert set((await db_session.execute(select(KnowledgeSourceVersionDocument.document_revision_id))).scalars()) == (
        retained_revision_ids
    )
    chunk_revision_ids = list((await db_session.execute(select(KnowledgeChunk.document_revision_id))).scalars())
    assert set(chunk_revision_ids) == retained_revision_ids
    assert len(chunk_revision_ids) == 2 * len(retained_revision_ids)
    await db_session.refresh(source)
    assert source.current_successful_version_id == versions[2].id


@pytest.mark.parametrize("keep_latest", [1, 2])
async def test_shared_document_chunks_follow_retained_version_config(db_session, keep_latest):
    source = await _add_source(db_session)
    previous = await _add_version(db_session, source, 0, index_config_hash="configA")
    current = await _add_version(db_session, source, 1, index_config_hash="configB")
    revision = await _add_revision(
        db_session, source, "shared", [previous, current], index_config_hashes=("configA", "configB")
    )
    source.current_successful_version_id = current.id
    await db_session.commit()

    assert await prune_knowledge_source_history(db_session, keep_latest=keep_latest) == (2 - keep_latest, 0, [])

    retained_version_ids = {current.id, previous.id} if keep_latest == 2 else {current.id}
    assert set((await db_session.execute(select(KnowledgeSourceVersion.id))).scalars()) == retained_version_ids
    assert set((await db_session.execute(select(KnowledgeSourceVersionDocument.version_id))).scalars()) == (
        retained_version_ids
    )
    assert list((await db_session.execute(select(KnowledgeDocumentRevision.id))).scalars()) == [revision.id]
    retained_configs = ("configA", "configB") if keep_latest == 2 else ("configB",)
    assert set(
        (
            await db_session.execute(
                select(KnowledgeChunk.document_revision_id, KnowledgeChunk.index_config_hash, KnowledgeChunk.ordinal)
            )
        ).all()
    ) == {(revision.id, config, ordinal) for config in retained_configs for ordinal in range(2)}

    if keep_latest == 2:
        assert await prune_knowledge_source_history(db_session, keep_latest=1) == (1, 0, [])
        assert list((await db_session.execute(select(KnowledgeDocumentRevision.id))).scalars()) == [revision.id]
        assert set(
            (await db_session.execute(select(KnowledgeChunk.index_config_hash, KnowledgeChunk.ordinal))).all()
        ) == {("configB", ordinal) for ordinal in range(2)}
    await db_session.refresh(source)
    assert source.current_successful_version_id == current.id


@pytest.mark.parametrize("with_retained_version", [False, True])
async def test_orphans_are_collected_even_without_history_deletions(db_session, async_engine, with_retained_version):
    source = await _add_source(db_session)
    retained_revision_ids = set()
    if with_retained_version:
        version = await _add_version(db_session, source, 0)
        revision = await _add_revision(db_session, source, "retained", [version])
        retained_revision_ids.add(revision.id)
    await _add_revision(db_session, source, "failed-staging-orphan")
    await db_session.commit()

    assert await prune_knowledge_source_history(db_session) == (0, 0, [])

    async with async_engine.connect() as connection:
        assert set((await connection.execute(select(KnowledgeDocumentRevision.id))).scalars()) == retained_revision_ids
        assert set((await connection.execute(select(KnowledgeChunk.document_revision_id))).scalars()) == (
            retained_revision_ids
        )
        lock_key = int.from_bytes(source.id.bytes[:8], byteorder="big", signed=True)
        assert await connection.scalar(text("SELECT pg_try_advisory_xact_lock(:lock_key)"), {"lock_key": lock_key})


async def test_worker_lock_skips_history_artifacts_and_staged_vectors_until_release(
    db_session, async_engine, monkeypatch
):
    monkeypatch.setattr("shared.lib.housekeeping.settings.knowledge_source_object_store_bucket", "knowledge")
    source = await _add_source(db_session, "locked")
    version = await _add_version(db_session, source, 0, artifact_keys={"manifest": "locked/manifest.json"})
    revision = await _add_revision(db_session, source, "old", [version])
    run = BackgroundJobRun(
        job_type="knowledge_source_sync",
        knowledge_source_id=source.id,
        knowledge_source_version_id=version.id,
        status="succeeded",
        started_at=ANCHOR,
    )
    db_session.add(run)
    other_source = await _add_source(db_session, "unlocked")
    await _add_revision(db_session, other_source, "unlocked-orphan")
    await db_session.commit()
    deleted_keys = []

    class Store:
        def delete_object(self, bucket, key):
            assert bucket == "knowledge"
            deleted_keys.append(key)
            return True

    lock_key = int.from_bytes(source.id.bytes[:8], byteorder="big", signed=True)
    async with async_engine.connect() as worker:
        assert await worker.scalar(text("SELECT pg_try_advisory_lock(:lock_key)"), {"lock_key": lock_key})
        await worker.commit()
        try:
            await worker.execute(
                KnowledgeDocumentRevision.__table__.insert().values(
                    source_id=source.id,
                    external_id="staged",
                    provider_revision="1",
                    title="Staged",
                    canonical_url="https://docs.example.com/pages/staged",
                    normalized_content="Staged content",
                    content_hash="hash-staged",
                )
            )
            await worker.commit()

            assert await prune_knowledge_source_history(db_session, keep_latest=0, object_store=Store()) == (0, 0, [])
            assert deleted_keys == []
            assert list((await db_session.execute(select(KnowledgeSourceVersion.id))).scalars()) == [version.id]
            assert list((await db_session.execute(select(BackgroundJobRun.id))).scalars()) == [run.id]
            assert set((await db_session.execute(select(KnowledgeDocumentRevision.external_id))).scalars()) == {
                "old",
                "staged",
            }
            assert list((await db_session.execute(select(KnowledgeChunk.document_revision_id))).scalars()) == [
                revision.id,
                revision.id,
            ]
        finally:
            assert await worker.scalar(text("SELECT pg_advisory_unlock(:lock_key)"), {"lock_key": lock_key})
            await worker.commit()

    assert await prune_knowledge_source_history(db_session, keep_latest=0, object_store=Store()) == (1, 1, [])
    assert deleted_keys == ["locked/manifest.json"]
    for model in (KnowledgeSourceVersion, BackgroundJobRun, KnowledgeDocumentRevision, KnowledgeChunk):
        assert not list((await db_session.execute(select(model))).scalars())


async def test_retention_reloads_current_pointer_after_lock_acquisition(db_session, async_engine):
    source = await _add_source(db_session)
    previous = await _add_version(db_session, source, 0)
    promoted = await _add_version(db_session, source, 1)
    promoted_revision = await _add_revision(db_session, source, "promoted", [promoted])
    await _add_revision(db_session, source, "previous", [previous])
    source.current_successful_version_id = previous.id
    await db_session.commit()
    async with async_engine.begin() as connection:
        await connection.execute(
            update(KnowledgeSource)
            .where(KnowledgeSource.id == source.id)
            .values(current_successful_version_id=promoted.id)
        )
    assert source.current_successful_version_id == previous.id

    assert await prune_knowledge_source_history(db_session, keep_latest=0) == (1, 0, [])

    assert source.current_successful_version_id == promoted.id
    assert list((await db_session.execute(select(KnowledgeSourceVersion.id))).scalars()) == [promoted.id]
    assert list((await db_session.execute(select(KnowledgeDocumentRevision.id))).scalars()) == [promoted_revision.id]
    assert list((await db_session.execute(select(KnowledgeChunk.document_revision_id))).scalars()) == [
        promoted_revision.id,
        promoted_revision.id,
    ]
