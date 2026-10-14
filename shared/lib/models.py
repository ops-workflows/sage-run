"""SQLAlchemy ORM models for task_queue and control_plane schemas."""

from __future__ import annotations

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ─── Task Queue ───────────────────────────────────────────────────────


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        Index("idx_tasks_status", "status"),
        Index("idx_tasks_workflow", "workflow"),
        Index("idx_tasks_created", "created"),
        {"schema": "task_queue"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workflow: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(
            "queued",
            "running",
            "waiting_approval",
            "waiting_user_input",
            "resume_pending",
            "succeeded",
            "failed",
            "lost",
            "timed_out",
            name="task_status",
            schema="task_queue",
        ),
        nullable=False,
        default="queued",
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    task_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    channel: Mapped[str | None] = mapped_column(Text)
    initiator: Mapped[str | None] = mapped_column(Text)
    message_channel: Mapped[str | None] = mapped_column(Text)
    message_thread: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[str | None] = mapped_column(Text)
    container_id: Mapped[str | None] = mapped_column(Text)
    heartbeat: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    wait_reason: Mapped[str | None] = mapped_column(Text)
    wait_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSONB)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    duration_sec: Mapped[float | None] = mapped_column(Float)
    error: Mapped[str | None] = mapped_column(Text)
    coalesce_key: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    events: Mapped[list[TaskEvent]] = relationship("TaskEvent", back_populates="task", cascade="all, delete-orphan")
    approvals: Mapped[list[Approval]] = relationship("Approval", back_populates="task", cascade="all, delete-orphan")


class TaskEvent(Base):
    __tablename__ = "task_events"
    __table_args__ = (
        Index("idx_task_events_task", "task_id", "created"),
        {"schema": "task_queue"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_queue.tasks.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB)
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    task: Mapped[Task] = relationship("Task", back_populates="events")


# ─── Control Plane ────────────────────────────────────────────────────


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = {"schema": "control_plane"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    config_hash: Mapped[str | None] = mapped_column(Text)
    repo_path: Mapped[str | None] = mapped_column(Text)
    provisioned: Mapped[bool] = mapped_column(Boolean, default=False)
    paused: Mapped[bool] = mapped_column(Boolean, default=True)
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    sessions: Mapped[list[Session]] = relationship("Session", back_populates="agent")
    schedules: Mapped[list[Schedule]] = relationship("Schedule", back_populates="agent", cascade="all, delete-orphan")


class ConnectorState(Base):
    __tablename__ = "connector_states"
    __table_args__ = {"schema": "control_plane"}

    connector_id: Mapped[str] = mapped_column(Text, primary_key=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        onupdate=text("now()"),
    )


class Session(Base):
    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_task", "task_id"),
        Index("idx_sessions_agent", "agent_id"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_queue.tasks.id", ondelete="SET NULL")
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.agents.id", ondelete="SET NULL")
    )
    container_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    ended: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float | None] = mapped_column(Float)
    turns: Mapped[int] = mapped_column(Integer, default=0)
    tools_used: Mapped[list] = mapped_column(JSONB, default=list)
    subagents_used: Mapped[list] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    agent: Mapped[Agent | None] = relationship("Agent", back_populates="sessions")


class SessionEvent(Base):
    __tablename__ = "session_events"
    __table_args__ = (
        Index("idx_session_events_task", "task_id", "timestamp"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_queue.tasks.id", ondelete="CASCADE")
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    data: Mapped[dict | None] = mapped_column(JSONB)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        Index("idx_approvals_task", "task_id", "requested_at"),
        Index("idx_approvals_status", "status", "requested_at"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("task_queue.tasks.id", ondelete="CASCADE")
    )
    workflow: Mapped[str | None] = mapped_column(Text)
    approval_kind: Mapped[str] = mapped_column(Text, nullable=False, default="operator_approval")
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    request_preview: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    approval_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    task: Mapped[Task] = relationship("Task", back_populates="approvals")


class Schedule(Base):
    __tablename__ = "schedules"
    __table_args__ = {"schema": "control_plane"}

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.agents.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    cron: Mapped[str] = mapped_column(Text, nullable=False)
    prompt: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_run: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    agent: Mapped[Agent] = relationship("Agent", back_populates="schedules")


class BackgroundJobRun(Base):
    __tablename__ = "background_job_runs"
    __table_args__ = (
        Index("idx_background_job_runs_job_type", "job_type", "started_at"),
        Index("idx_background_job_runs_source", "knowledge_source_id", "started_at"),
        Index("idx_background_job_runs_version", "knowledge_source_version_id"),
        Index("idx_background_job_runs_started_at", "started_at"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    trigger: Mapped[str | None] = mapped_column(Text)
    knowledge_source_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.knowledge_sources.id", ondelete="SET NULL")
    )
    knowledge_source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.knowledge_source_versions.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_sec: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        CheckConstraint(
            "(source_kind = 'github' AND index_kind = 'code_graph') OR "
            "(source_kind = 'confluence' AND index_kind = 'hybrid_vector')",
            name="ck_knowledge_sources_kind_pair",
        ),
        Index("idx_knowledge_sources_enabled", "enabled"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    canonical_alias: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str | None] = mapped_column(
        Text, default=lambda context: context.get_current_parameters()["canonical_alias"]
    )
    source_kind: Mapped[str] = mapped_column(Text, nullable=False, default="github", server_default="github")
    index_kind: Mapped[str] = mapped_column(Text, nullable=False, default="code_graph", server_default="code_graph")
    source_config: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=lambda context: (
            {
                key: (context.get_current_parameters().get(key) or [])
                if key.endswith("_paths")
                else context.get_current_parameters().get(key)
                for key in ("repository_url", "default_ref", "include_paths", "exclude_paths")
            }
            if context.get_current_parameters().get("source_kind", "github") == "github"
            else {}
        ),
        server_default=text("'{}'::jsonb"),
    )
    repository_url: Mapped[str | None] = mapped_column(Text)
    default_ref: Mapped[str | None] = mapped_column(Text)
    include_paths: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    exclude_paths: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    credential_ref: Mapped[str | None] = mapped_column(Text)
    sync_policy: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    serving_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    serving_suspension_reason: Mapped[str | None] = mapped_column(Text)
    current_successful_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.knowledge_source_versions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    versions: Mapped[list[KnowledgeSourceVersion]] = relationship(
        "KnowledgeSourceVersion",
        back_populates="source",
        cascade="all, delete-orphan",
        foreign_keys="KnowledgeSourceVersion.source_id",
    )
    current_successful_version: Mapped[KnowledgeSourceVersion | None] = relationship(
        "KnowledgeSourceVersion",
        foreign_keys=[current_successful_version_id],
        post_update=True,
    )


class KnowledgeSourceVersion(Base):
    __tablename__ = "knowledge_source_versions"
    __table_args__ = (
        CheckConstraint(
            "index_kind = 'code_graph' OR (index_kind = 'hybrid_vector' AND "
            "source_revision IS NOT NULL AND indexer_version IS NOT NULL AND index_config_hash IS NOT NULL)",
            name="ck_knowledge_source_versions_index_identity",
        ),
        UniqueConstraint(
            "source_id",
            "commit_sha",
            "graphify_version",
            "extraction_config_hash",
            name="uq_knowledge_source_versions_identity",
        ),
        Index(
            "uq_knowledge_source_versions_generic_identity",
            "source_id",
            "source_revision",
            "index_config_hash",
            unique=True,
            postgresql_where=text("index_kind <> 'code_graph'"),
        ),
        Index("idx_knowledge_source_versions_source", "source_id", "created_at"),
        Index("idx_knowledge_source_versions_status", "status", "created_at"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    source_revision: Mapped[str | None] = mapped_column(
        Text, default=lambda context: context.get_current_parameters().get("commit_sha")
    )
    index_kind: Mapped[str] = mapped_column(Text, nullable=False, default="code_graph", server_default="code_graph")
    indexer_version: Mapped[str | None] = mapped_column(
        Text, default=lambda context: context.get_current_parameters().get("graphify_version")
    )
    index_config_hash: Mapped[str | None] = mapped_column(
        Text, default=lambda context: context.get_current_parameters().get("extraction_config_hash")
    )
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    commit_sha: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="pending")
    graphify_version: Mapped[str | None] = mapped_column(Text)
    extraction_config_hash: Mapped[str | None] = mapped_column(Text)
    artifact_keys: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    artifact_checksums: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))

    source: Mapped[KnowledgeSource] = relationship(
        "KnowledgeSource", back_populates="versions", foreign_keys=[source_id]
    )


class KnowledgeDocumentRevision(Base):
    __tablename__ = "knowledge_document_revisions"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", "content_hash", name="uq_knowledge_document_revisions_identity"),
        Index("idx_knowledge_document_revisions_source", "source_id", "external_id"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("control_plane.knowledge_sources.id", ondelete="CASCADE"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    provider_revision: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_url: Mapped[str] = mapped_column(Text, nullable=False)
    hierarchy_path: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    document_metadata: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("document_revision_id", "index_config_hash", "ordinal", name="uq_knowledge_chunks_identity"),
        CheckConstraint(
            "embedding_dimensions > 0 AND vector_dims(embedding) = embedding_dimensions",
            name="ck_knowledge_chunks_embedding_dimensions",
        ),
        Index("idx_knowledge_chunks_document", "document_revision_id"),
        Index("idx_knowledge_chunks_search", "search_vector", postgresql_using="gin"),
        {"schema": "control_plane"},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, server_default=text("uuid_generate_v4()")
    )
    document_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("control_plane.knowledge_document_revisions.id", ondelete="CASCADE"),
        nullable=False,
    )
    index_config_hash: Mapped[str] = mapped_column(Text, nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    heading_path: Mapped[list] = mapped_column(JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    lexical_text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(TSVECTOR, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(), nullable=False)
    embedding_model: Mapped[str] = mapped_column(Text, nullable=False)
    embedding_dimensions: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeSourceVersionDocument(Base):
    __tablename__ = "knowledge_source_version_documents"
    __table_args__ = (
        Index("idx_knowledge_source_version_documents_revision", "document_revision_id"),
        {"schema": "control_plane"},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("control_plane.knowledge_source_versions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    document_revision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("control_plane.knowledge_document_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    external_id: Mapped[str] = mapped_column(Text, primary_key=True)
    root_page_id: Mapped[str] = mapped_column(Text, nullable=False)


class WorkflowRepoState(Base):
    """Singleton row tracking the connected workflow repo's pinned version and last sync.

    One platform instance targets exactly one workflow repo, so this table
    always has a single row (id=1). The bootstrap-owned repo URL/PAT are
    never stored here — only the operator-facing pinned ref and sync status.
    """

    __tablename__ = "workflow_repo_state"
    __table_args__ = {"schema": "control_plane"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    pinned_ref: Mapped[str | None] = mapped_column(Text)
    last_synced_ref: Mapped[str | None] = mapped_column(Text)
    last_synced_commit: Mapped[str | None] = mapped_column(Text)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(Text)
    last_sync_error: Mapped[str | None] = mapped_column(Text)
    discovered_workflows: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    bundle_errors: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    updated: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"))
