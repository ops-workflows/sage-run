"""Schema contract tests for the Knowledge Source registry."""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import configure_mappers

from shared.lib.models import Base

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[2]


def _table(name: str):
    return Base.metadata.tables[f"control_plane.{name}"]


def test_knowledge_source_mappers_and_tables_are_registered():
    configure_mappers()

    assert {
        "control_plane.knowledge_sources",
        "control_plane.knowledge_source_versions",
        "control_plane.knowledge_document_revisions",
        "control_plane.knowledge_chunks",
        "control_plane.knowledge_source_version_documents",
    } <= set(Base.metadata.tables)
    source_columns = _table("knowledge_sources").c
    assert {"source_type", "provider", "host", "access_policy", "ownership_role"}.isdisjoint(source_columns)
    assert "control_plane.knowledge_source_dependencies" not in Base.metadata.tables


def test_generic_registry_defaults_and_nullable_git_fields():
    sources = _table("knowledge_sources")
    versions = _table("knowledge_source_versions")

    assert sources.c.source_kind.default.arg == "github"
    assert sources.c.index_kind.default.arg == "code_graph"
    assert sources.c.display_name.default is not None
    assert sources.c.source_config.default is not None
    assert sources.c.repository_url.nullable
    assert sources.c.default_ref.nullable
    assert {"serving_suspended_at", "serving_suspension_reason"} <= set(sources.c.keys())
    assert {"source_revision", "index_kind", "indexer_version", "index_config_hash", "stats"} <= set(versions.c.keys())
    assert all(versions.c[name].nullable for name in ("commit_sha", "graphify_version", "extraction_config_hash"))
    pair = next(constraint for constraint in sources.constraints if isinstance(constraint, CheckConstraint))
    assert "source_kind = 'confluence' AND index_kind = 'hybrid_vector'" in str(pair.sqltext)
    identity = next(
        index for index in versions.indexes if index.name == "uq_knowledge_source_versions_generic_identity"
    )
    assert identity.unique
    assert [column.name for column in identity.columns] == ["source_id", "source_revision", "index_config_hash"]
    assert str(identity.dialect_options["postgresql"]["where"]) == "index_kind <> 'code_graph'"


def test_version_identity_and_promotion_are_source_scoped():
    sources = _table("knowledge_sources")
    versions = _table("knowledge_source_versions")

    identity = next(
        constraint
        for constraint in versions.constraints
        if isinstance(constraint, UniqueConstraint) and constraint.name == "uq_knowledge_source_versions_identity"
    )
    assert [column.name for column in identity.columns] == [
        "source_id",
        "commit_sha",
        "graphify_version",
        "extraction_config_hash",
    ]
    assert {foreign_key.target_fullname for foreign_key in sources.c.current_successful_version_id.foreign_keys} == {
        "control_plane.knowledge_source_versions.id"
    }
    assert {foreign_key.target_fullname for foreign_key in versions.c.source_id.foreign_keys} == {
        "control_plane.knowledge_sources.id"
    }


def test_background_jobs_have_typed_knowledge_source_context():
    runs = _table("background_job_runs")

    assert {foreign_key.target_fullname for foreign_key in runs.c.knowledge_source_id.foreign_keys} == {
        "control_plane.knowledge_sources.id"
    }
    assert {foreign_key.target_fullname for foreign_key in runs.c.knowledge_source_version_id.foreign_keys} == {
        "control_plane.knowledge_source_versions.id"
    }
    assert {"trigger", "heartbeat_at"} <= {column.name for column in runs.c}


def test_bootstrap_sql_copies_share_the_knowledge_source_schema():
    shared_sql = (REPO_ROOT / "shared/lib/init_db.sql").read_text()
    deployment_sql = (REPO_ROOT / "deploy/k8s/sage-run/files/init_db.sql").read_text()

    assert shared_sql == deployment_sql
    for contract in (
        "CREATE TABLE control_plane.knowledge_sources",
        "CREATE TABLE control_plane.knowledge_source_versions",
        "CREATE TABLE control_plane.knowledge_document_revisions",
        "CREATE TABLE control_plane.knowledge_chunks",
        "CREATE TABLE control_plane.knowledge_source_version_documents",
        "embedding             VECTOR NOT NULL",
        "vector_dims(embedding) = embedding_dimensions",
        "root_page_id         TEXT NOT NULL",
        "fk_knowledge_sources_current_version",
        "knowledge_source_version_id UUID REFERENCES",
    ):
        assert contract in shared_sql
    for retired_contract in (
        "knowledge_source_dependencies",
        "access_policy",
        "ownership_role",
    ):
        assert retired_contract not in shared_sql
