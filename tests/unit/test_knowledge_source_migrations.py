"""Executable legacy migration, bootstrap parity, and relational retention checks."""

from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from sqlalchemy import delete, insert, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from shared.lib import db
from shared.lib.models import (
    Base,
    KnowledgeChunk,
    KnowledgeDocumentRevision,
    KnowledgeSource,
    KnowledgeSourceVersion,
    KnowledgeSourceVersionDocument,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
LEGACY_SQL = """
CREATE SCHEMA control_plane;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE control_plane.knowledge_sources (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), canonical_alias TEXT NOT NULL UNIQUE,
    repository_url TEXT NOT NULL, default_ref TEXT NOT NULL,
    include_paths JSONB NOT NULL DEFAULT '[]', exclude_paths JSONB NOT NULL DEFAULT '[]',
    credential_ref TEXT, sync_policy JSONB NOT NULL DEFAULT '{}', enabled BOOLEAN NOT NULL DEFAULT TRUE,
    current_successful_version_id UUID, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE control_plane.knowledge_source_versions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id UUID NOT NULL REFERENCES control_plane.knowledge_sources(id) ON DELETE CASCADE,
    commit_sha TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', graphify_version TEXT NOT NULL,
    extraction_config_hash TEXT NOT NULL, artifact_keys JSONB NOT NULL DEFAULT '{}',
    artifact_checksums JSONB NOT NULL DEFAULT '{}', file_count INT NOT NULL DEFAULT 0,
    node_count INT NOT NULL DEFAULT 0, edge_count INT NOT NULL DEFAULT 0,
    warnings JSONB NOT NULL DEFAULT '[]', error TEXT, started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_source_versions_identity
    UNIQUE (source_id, commit_sha, graphify_version, extraction_config_hash)
);
ALTER TABLE control_plane.knowledge_sources ADD CONSTRAINT fk_knowledge_sources_current_version
FOREIGN KEY (current_successful_version_id) REFERENCES control_plane.knowledge_source_versions(id) ON DELETE SET NULL;
CREATE INDEX idx_knowledge_sources_enabled ON control_plane.knowledge_sources (enabled);
CREATE INDEX idx_knowledge_source_versions_source
ON control_plane.knowledge_source_versions (source_id, created_at DESC);
CREATE INDEX idx_knowledge_source_versions_status ON control_plane.knowledge_source_versions (status, created_at DESC);
"""


@asynccontextmanager
async def _integrity_error(connection):
    with pytest.raises(IntegrityError):
        async with connection.begin_nested():
            yield


@pytest.fixture(params=["legacy", "bootstrap", "kubernetes"])
async def migrated_registry(request, require_database):
    database_name = f"sage_knowledge_test_{uuid4().hex}"
    url = make_url(require_database)
    admin_dsn = url.set(drivername="postgresql").render_as_string(hide_password=False)
    test_url = url.set(database=database_name)
    with psycopg.connect(admin_dsn, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
    engine = create_async_engine(test_url)
    try:
        bootstrap = {
            "legacy": LEGACY_SQL,
            "bootstrap": (REPO_ROOT / "shared/lib/init_db.sql").read_text(),
            "kubernetes": (REPO_ROOT / "sage_run/chart/files/init_db.sql").read_text(),
        }[request.param]
        with psycopg.connect(test_url.set(drivername="postgresql").render_as_string(hide_password=False)) as initial:
            initial.execute(bootstrap, prepare=False)
        async with engine.begin() as connection:
            if request.param != "legacy":
                await _assert_registry_contract(connection)
            source_id = (
                await connection.execute(
                    text(
                        "INSERT INTO control_plane.knowledge_sources "
                        "(canonical_alias, repository_url, default_ref, include_paths, exclude_paths) "
                        "VALUES ('legacy', 'https://github.example/service.git', 'main', '[\"src/**\"]', "
                        "'[\"vendor/**\"]') RETURNING id"
                    )
                )
            ).scalar_one()
            version_id = (
                await connection.execute(
                    text(
                        "INSERT INTO control_plane.knowledge_source_versions "
                        "(source_id, commit_sha, graphify_version, extraction_config_hash, status) "
                        "VALUES (:source, 'commit', 'graphify-1', 'config', 'succeeded') RETURNING id"
                    ),
                    {"source": source_id},
                )
            ).scalar_one()
            await connection.execute(
                text("UPDATE control_plane.knowledge_sources SET current_successful_version_id = :version"),
                {"version": version_id},
            )
            await db._ensure_knowledge_schema(connection)
            await db._ensure_knowledge_schema(connection)
            yield connection, source_id, version_id
    finally:
        await engine.dispose()
        with psycopg.connect(admin_dsn, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(database_name)))


@pytest.mark.unit
async def test_runtime_schema_calls_knowledge_migration_once(monkeypatch):
    connection = AsyncMock()

    @asynccontextmanager
    async def begin():
        yield connection

    migration = AsyncMock()
    monkeypatch.setattr(db, "engine", Mock(begin=begin))
    monkeypatch.setattr(db, "_schema_ready", False)
    monkeypatch.setattr(db, "_ensure_knowledge_schema", migration)
    await db.ensure_runtime_schema()
    await db.ensure_runtime_schema()
    migration.assert_awaited_once_with(connection)


@pytest.mark.service
async def test_existing_github_identity_and_pointer_survive_idempotent_migration(migrated_registry):
    connection, source_id, version_id = migrated_registry
    source = (await connection.execute(select(KnowledgeSource.__table__))).mappings().one()
    version = (await connection.execute(select(KnowledgeSourceVersion.__table__))).mappings().one()
    assert source["id"] == source_id
    assert source["canonical_alias"] == source["display_name"] == "legacy"
    assert source["current_successful_version_id"] == version_id
    assert source["source_kind"] == "github"
    assert source["index_kind"] == "code_graph"
    assert source["source_config"] == {
        "repository_url": "https://github.example/service.git",
        "default_ref": "main",
        "include_paths": ["src/**"],
        "exclude_paths": ["vendor/**"],
    }
    assert version["source_revision"] == version["commit_sha"] == "commit"
    assert version["indexer_version"] == version["graphify_version"] == "graphify-1"
    assert version["index_config_hash"] == version["extraction_config_hash"] == "config"
    assert version["index_kind"] == "code_graph"
    assert version["stats"] == {}
    await connection.execute(
        KnowledgeSource.__table__.update()
        .where(KnowledgeSource.id == source_id)
        .values(display_name="Operator name", source_config={"repository_url": "new"})
    )
    await connection.execute(
        KnowledgeSourceVersion.__table__.update()
        .where(KnowledgeSourceVersion.id == version_id)
        .values(indexer_version="custom-indexer")
    )
    await db._ensure_knowledge_schema(connection)
    updated = (await connection.execute(select(KnowledgeSource.__table__))).mappings().one()
    assert updated["display_name"] == "Operator name"
    assert updated["source_config"] == {"repository_url": "new"}
    assert (await connection.execute(select(KnowledgeSourceVersion.indexer_version))).scalar_one() == "custom-indexer"


@pytest.mark.service
async def test_schema_columns_constraints_and_indexes_match_models(migrated_registry):
    connection, _, _ = migrated_registry
    await _assert_registry_contract(connection)


async def _assert_registry_contract(connection):
    for name in (
        "knowledge_sources",
        "knowledge_source_versions",
        "knowledge_document_revisions",
        "knowledge_chunks",
        "knowledge_source_version_documents",
    ):
        table = Base.metadata.tables[f"control_plane.{name}"]
        actual = (
            (
                await connection.execute(
                    text(
                        "SELECT attname, format_type(atttypid, atttypmod) AS type, attnotnull "
                        "FROM pg_attribute WHERE attrelid = to_regclass(:table) AND attnum > 0 AND NOT attisdropped"
                    ),
                    {"table": f"control_plane.{name}"},
                )
            )
            .mappings()
            .all()
        )
        assert {row["attname"] for row in actual} == set(table.c.keys())
        for row in actual:
            column = table.c[row["attname"]]
            assert row["attnotnull"] == (not column.nullable), (name, column.name)
            expected_type = str(column.type.compile(dialect=connection.dialect)).lower()
            assert row["type"] == expected_type, (name, column.name)
        indexes = set(
            (
                await connection.execute(
                    text("SELECT indexname FROM pg_indexes WHERE schemaname = 'control_plane' AND tablename = :table"),
                    {"table": name},
                )
            ).scalars()
        )
        assert {index.name for index in table.indexes} <= indexes
        constraints = set(
            (
                await connection.execute(
                    text("SELECT conname FROM pg_constraint WHERE conrelid = to_regclass(:table)"),
                    {"table": f"control_plane.{name}"},
                )
            ).scalars()
        )
        assert {constraint.name for constraint in table.constraints if constraint.name} <= constraints
        foreign_keys = await connection.run_sync(
            lambda sync_connection, table_name=name: inspect(sync_connection).get_foreign_keys(
                table_name, schema="control_plane"
            )
        )
        assert {
            (
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_schema"],
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key["options"].get("ondelete", "NO ACTION"),
            )
            for foreign_key in foreign_keys
        } == {
            (
                tuple(constraint.column_keys),
                constraint.referred_table.schema,
                constraint.referred_table.name,
                tuple(element.column.name for element in constraint.elements),
                constraint.ondelete or "NO ACTION",
            )
            for constraint in table.foreign_key_constraints
        }


@pytest.mark.service
async def test_legacy_orm_writes_receive_generic_defaults(migrated_registry):
    connection, _, _ = migrated_registry
    source = (
        (
            await connection.execute(
                insert(KnowledgeSource)
                .values(canonical_alias="new-git", repository_url="https://github.example/new.git", default_ref="main")
                .returning(KnowledgeSource.__table__)
            )
        )
        .mappings()
        .one()
    )
    assert source["display_name"] == "new-git"
    assert source["source_config"] == {
        "repository_url": "https://github.example/new.git",
        "default_ref": "main",
        "include_paths": [],
        "exclude_paths": [],
    }
    version = (
        (
            await connection.execute(
                insert(KnowledgeSourceVersion)
                .values(
                    source_id=source["id"],
                    commit_sha="new-commit",
                    graphify_version="new-graphify",
                    extraction_config_hash="new-config",
                )
                .returning(KnowledgeSourceVersion.__table__)
            )
        )
        .mappings()
        .one()
    )
    assert version["source_revision"] == "new-commit"
    assert version["indexer_version"] == "new-graphify"
    assert version["index_config_hash"] == "new-config"


@pytest.mark.service
async def test_git_and_generic_uniqueness_preserve_compatibility(migrated_registry):
    connection, source_id, _ = migrated_registry
    git_version = {
        "source_id": source_id,
        "commit_sha": "commit",
        "graphify_version": "graphify-2",
        "extraction_config_hash": "config",
    }
    await connection.execute(insert(KnowledgeSourceVersion).values(**git_version))
    async with _integrity_error(connection):
        await connection.execute(insert(KnowledgeSourceVersion).values(**git_version))
    confluence_id = (
        await connection.execute(
            insert(KnowledgeSource)
            .values(
                canonical_alias="wiki",
                source_kind="confluence",
                index_kind="hybrid_vector",
                source_config={"root_page_ids": ["123"]},
            )
            .returning(KnowledgeSource.id)
        )
    ).scalar_one()
    generic = {
        "source_id": confluence_id,
        "source_revision": "snapshot",
        "index_kind": "hybrid_vector",
        "indexer_version": "hybrid-1",
        "index_config_hash": "hybrid-config",
    }
    version = (
        (
            await connection.execute(
                insert(KnowledgeSourceVersion).values(**generic).returning(KnowledgeSourceVersion.__table__)
            )
        )
        .mappings()
        .one()
    )
    assert version["commit_sha"] is version["graphify_version"] is version["extraction_config_hash"] is None
    async with _integrity_error(connection):
        await connection.execute(insert(KnowledgeSourceVersion).values(**{**generic, "indexer_version": "hybrid-2"}))
    await connection.execute(insert(KnowledgeSourceVersion).values(**{**generic, "index_config_hash": "new-config"}))


@pytest.mark.service
async def test_invalid_source_pairs_and_incomplete_hybrid_identities_are_rejected(migrated_registry):
    connection, source_id, _ = migrated_registry
    for source_kind, index_kind in (("github", "hybrid_vector"), ("confluence", "code_graph"), ("other", "code_graph")):
        async with _integrity_error(connection):
            await connection.execute(
                insert(KnowledgeSource).values(
                    canonical_alias="invalid", source_kind=source_kind, index_kind=index_kind
                )
            )
    async with _integrity_error(connection):
        await connection.execute(insert(KnowledgeSourceVersion).values(source_id=source_id, index_kind="hybrid_vector"))


async def _revision_and_chunk(connection, source_id):
    revision_id = (
        await connection.execute(
            insert(KnowledgeDocumentRevision)
            .values(
                source_id=source_id,
                external_id="123",
                provider_revision="1",
                title="Runbook",
                canonical_url="https://wiki.example/pages/123",
                normalized_content="Recovery procedure",
                content_hash="body-hash",
            )
            .returning(KnowledgeDocumentRevision.id)
        )
    ).scalar_one()
    chunk = {
        "document_revision_id": revision_id,
        "index_config_hash": "config",
        "ordinal": 0,
        "content": "Recovery procedure",
        "content_hash": "chunk-hash",
        "estimated_tokens": 3,
        "lexical_text": "Runbook Recovery procedure",
        "search_vector": text("to_tsvector('simple', 'Runbook Recovery procedure')"),
        "embedding": [1.0, 0.0, 0.5],
        "embedding_model": "test-embedding",
        "embedding_dimensions": 3,
    }
    await connection.execute(insert(KnowledgeChunk).values(**chunk))
    return revision_id, chunk


@pytest.mark.service
async def test_vector_dimension_document_and_chunk_uniqueness_are_enforced(migrated_registry):
    connection, source_id, _ = migrated_registry
    revision_id, chunk = await _revision_and_chunk(connection, source_id)
    async with _integrity_error(connection):
        await connection.execute(insert(KnowledgeChunk).values(**chunk))
    for dimensions in (0, 2, 4):
        async with _integrity_error(connection):
            await connection.execute(
                insert(KnowledgeChunk).values(**{**chunk, "ordinal": 1, "embedding_dimensions": dimensions})
            )
    await connection.execute(
        insert(KnowledgeChunk).values(
            **{**chunk, "index_config_hash": "new-dimension", "embedding": [1.0, 0.0], "embedding_dimensions": 2}
        )
    )
    async with _integrity_error(connection):
        await connection.execute(
            insert(KnowledgeDocumentRevision).from_select(
                [
                    "source_id",
                    "external_id",
                    "provider_revision",
                    "title",
                    "canonical_url",
                    "hierarchy_path",
                    "normalized_content",
                    "content_hash",
                    "metadata",
                ],
                select(
                    KnowledgeDocumentRevision.source_id,
                    KnowledgeDocumentRevision.external_id,
                    KnowledgeDocumentRevision.provider_revision,
                    KnowledgeDocumentRevision.title,
                    KnowledgeDocumentRevision.canonical_url,
                    KnowledgeDocumentRevision.hierarchy_path,
                    KnowledgeDocumentRevision.normalized_content,
                    KnowledgeDocumentRevision.content_hash,
                    KnowledgeDocumentRevision.document_metadata,
                ).where(KnowledgeDocumentRevision.id == revision_id),
            )
        )


@pytest.mark.service
async def test_membership_fk_unique_and_non_nullable_root_are_enforced(migrated_registry):
    connection, source_id, version_id = migrated_registry
    revision_id, _ = await _revision_and_chunk(connection, source_id)
    membership = {
        "version_id": version_id,
        "document_revision_id": revision_id,
        "external_id": "123",
        "root_page_id": "first-root",
    }
    await connection.execute(insert(KnowledgeSourceVersionDocument).values(**membership))
    for changed in (
        {},
        {"root_page_id": None, "external_id": "456"},
        {"version_id": uuid4()},
        {"document_revision_id": uuid4(), "external_id": "456"},
    ):
        async with _integrity_error(connection):
            await connection.execute(insert(KnowledgeSourceVersionDocument).values(**{**membership, **changed}))


@pytest.mark.service
async def test_version_deletion_preserves_shared_revisions_and_chunks(migrated_registry):
    connection, source_id, version_id = migrated_registry
    revision_id, _ = await _revision_and_chunk(connection, source_id)
    next_version = (
        await connection.execute(
            insert(KnowledgeSourceVersion)
            .values(
                source_id=source_id, commit_sha="next", graphify_version="graphify-1", extraction_config_hash="config"
            )
            .returning(KnowledgeSourceVersion.id)
        )
    ).scalar_one()
    for member_version in (version_id, next_version):
        await connection.execute(
            insert(KnowledgeSourceVersionDocument).values(
                version_id=member_version, document_revision_id=revision_id, external_id="123", root_page_id="123"
            )
        )
    await connection.execute(delete(KnowledgeSourceVersion).where(KnowledgeSourceVersion.id == version_id))
    assert (await connection.execute(select(KnowledgeSourceVersionDocument.version_id))).scalar_one() == next_version
    assert (await connection.execute(select(KnowledgeChunk.document_revision_id))).scalar_one() == revision_id
    async with _integrity_error(connection):
        await connection.execute(delete(KnowledgeDocumentRevision).where(KnowledgeDocumentRevision.id == revision_id))
    await connection.execute(delete(KnowledgeSourceVersion).where(KnowledgeSourceVersion.id == next_version))
    assert (await connection.execute(select(KnowledgeSourceVersionDocument.version_id))).first() is None
    assert (await connection.execute(select(KnowledgeChunk.id))).first() is not None
    await connection.execute(delete(KnowledgeDocumentRevision).where(KnowledgeDocumentRevision.id == revision_id))
    assert (await connection.execute(select(KnowledgeChunk.id))).first() is None


@pytest.mark.service
async def test_source_deletion_cascades_versions_memberships_revisions_and_chunks(migrated_registry):
    connection, source_id, version_id = migrated_registry
    revision_id, _ = await _revision_and_chunk(connection, source_id)
    await connection.execute(
        insert(KnowledgeSourceVersionDocument).values(
            version_id=version_id, document_revision_id=revision_id, external_id="123", root_page_id="123"
        )
    )
    await connection.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))
    for model in (KnowledgeSourceVersion, KnowledgeSourceVersionDocument, KnowledgeDocumentRevision, KnowledgeChunk):
        assert (await connection.execute(select(model.__table__))).first() is None
