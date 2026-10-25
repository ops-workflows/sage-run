-- SAGE Run — Database Initialization
-- Creates schemas and tables for task queue, control plane, and hindsight

-- ─── Schemas ─────────────────────────────────────────────────────────
CREATE SCHEMA IF NOT EXISTS task_queue;
CREATE SCHEMA IF NOT EXISTS control_plane;
CREATE SCHEMA IF NOT EXISTS hindsight;

-- ─── Extensions ──────────────────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS vector;

-- ─── Task Queue Schema ──────────────────────────────────────────────

CREATE TYPE task_queue.task_status AS ENUM (
    'queued', 'running', 'waiting_approval', 'waiting_user_input',
    'resume_pending', 'succeeded', 'failed',
    'lost', 'timed_out'
);

CREATE TABLE task_queue.tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow        TEXT NOT NULL,
    status          task_queue.task_status NOT NULL DEFAULT 'queued',
    prompt          TEXT NOT NULL,
    metadata        JSONB NOT NULL DEFAULT '{}',
    channel         TEXT,
    initiator       TEXT,
    message_channel TEXT,
    message_thread  TEXT,
    session_id      TEXT,
    container_id    TEXT,
    heartbeat       TIMESTAMPTZ,
    wait_reason     TEXT,
    wait_deadline   TIMESTAMPTZ,
    wait_started    TIMESTAMPTZ,
    waited_sec      FLOAT NOT NULL DEFAULT 0,
    result          JSONB,
    tokens_used     INT DEFAULT 0,
    duration_sec    FLOAT,
    error           TEXT,
    dedupe_keys     TEXT[],
    archived_at     TIMESTAMPTZ,
    created         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_tasks_status ON task_queue.tasks (status);
CREATE INDEX idx_tasks_workflow ON task_queue.tasks (workflow);
CREATE INDEX idx_tasks_dedupe_keys ON task_queue.tasks USING gin (dedupe_keys);
CREATE INDEX idx_tasks_heartbeat ON task_queue.tasks (heartbeat) WHERE status = 'running';
CREATE INDEX idx_tasks_created ON task_queue.tasks (created DESC);
CREATE INDEX idx_tasks_archived_at ON task_queue.tasks (archived_at);

CREATE TABLE task_queue.task_events (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id     UUID NOT NULL REFERENCES task_queue.tasks(id) ON DELETE CASCADE,
    event_type  TEXT NOT NULL,
    data        JSONB,
    created     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_task_events_task ON task_queue.task_events (task_id, created);

-- ─── Control Plane Schema ───────────────────────────────────────────

CREATE TABLE control_plane.agents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    version         TEXT,
    config          JSONB NOT NULL DEFAULT '{}',
    config_hash     TEXT,
    repo_path       TEXT,
    provisioned     BOOLEAN DEFAULT FALSE,
    paused          BOOLEAN NOT NULL DEFAULT TRUE,
    provisioned_at  TIMESTAMPTZ,
    created         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE control_plane.connector_states (
    connector_id    TEXT PRIMARY KEY,
    paused          BOOLEAN NOT NULL DEFAULT TRUE,
    updated         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE control_plane.sessions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID REFERENCES task_queue.tasks(id) ON DELETE SET NULL,
    agent_id        UUID REFERENCES control_plane.agents(id) ON DELETE SET NULL,
    container_id    TEXT,
    status          TEXT NOT NULL DEFAULT 'running',
    started         TIMESTAMPTZ DEFAULT now(),
    ended           TIMESTAMPTZ,
    duration_sec    FLOAT,
    tokens_input    INT DEFAULT 0,
    tokens_output   INT DEFAULT 0,
    cost_usd        FLOAT,
    turns           INT DEFAULT 0,
    tools_used      JSONB DEFAULT '[]',
    subagents_used  JSONB DEFAULT '[]',
    error           TEXT,
    archived_at     TIMESTAMPTZ
);

CREATE INDEX idx_sessions_task ON control_plane.sessions (task_id);
CREATE INDEX idx_sessions_agent ON control_plane.sessions (agent_id);
CREATE INDEX idx_sessions_status ON control_plane.sessions (status);

CREATE TABLE control_plane.session_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID REFERENCES task_queue.tasks(id) ON DELETE CASCADE,
    event_type      TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL DEFAULT now(),
    data            JSONB,
    archived_at     TIMESTAMPTZ
);

CREATE INDEX idx_session_events_task ON control_plane.session_events (task_id, timestamp);
CREATE INDEX idx_session_events_type ON control_plane.session_events (event_type);

CREATE TABLE control_plane.approvals (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES task_queue.tasks(id) ON DELETE CASCADE,
    workflow        TEXT,
    approval_kind   TEXT NOT NULL DEFAULT 'operator_approval',
    tool_name       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    request_preview TEXT,
    reason          TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ,
    archived_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_approvals_task ON control_plane.approvals (task_id, requested_at DESC);
CREATE INDEX idx_approvals_status ON control_plane.approvals (status, requested_at DESC);

CREATE TABLE control_plane.schedules (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID REFERENCES control_plane.agents(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    cron        TEXT NOT NULL,
    prompt      TEXT,
    enabled     BOOLEAN DEFAULT TRUE,
    last_run    TIMESTAMPTZ,
    next_run    TIMESTAMPTZ,
    created     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_schedules_agent ON control_plane.schedules (agent_id);
CREATE INDEX idx_schedules_enabled ON control_plane.schedules (enabled) WHERE enabled = TRUE;

CREATE TABLE control_plane.knowledge_sources (
    id                            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    canonical_alias               TEXT NOT NULL UNIQUE,
    display_name                  TEXT,
    source_kind                   TEXT NOT NULL DEFAULT 'github',
    index_kind                    TEXT NOT NULL DEFAULT 'code_graph',
    source_config                 JSONB NOT NULL DEFAULT '{}',
    repository_url                TEXT,
    default_ref                   TEXT,
    include_paths                 JSONB NOT NULL DEFAULT '[]',
    exclude_paths                 JSONB NOT NULL DEFAULT '[]',
    credential_ref                TEXT,
    sync_policy                   JSONB NOT NULL DEFAULT '{}',
    enabled                       BOOLEAN NOT NULL DEFAULT TRUE,
    serving_suspended_at          TIMESTAMPTZ,
    serving_suspension_reason      TEXT,
    current_successful_version_id UUID,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_knowledge_sources_kind_pair CHECK (
        (source_kind = 'github' AND index_kind = 'code_graph') OR
        (source_kind = 'confluence' AND index_kind = 'hybrid_vector')
    )
);

CREATE INDEX idx_knowledge_sources_enabled ON control_plane.knowledge_sources (enabled);

CREATE TABLE control_plane.knowledge_source_versions (
    id                     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id              UUID NOT NULL REFERENCES control_plane.knowledge_sources(id) ON DELETE CASCADE,
    source_revision        TEXT,
    index_kind             TEXT NOT NULL DEFAULT 'code_graph',
    indexer_version        TEXT,
    index_config_hash      TEXT,
    stats                  JSONB NOT NULL DEFAULT '{}',
    commit_sha             TEXT,
    status                 TEXT NOT NULL DEFAULT 'pending',
    graphify_version       TEXT,
    extraction_config_hash TEXT,
    artifact_keys          JSONB NOT NULL DEFAULT '{}',
    artifact_checksums     JSONB NOT NULL DEFAULT '{}',
    file_count             INT NOT NULL DEFAULT 0,
    node_count             INT NOT NULL DEFAULT 0,
    edge_count             INT NOT NULL DEFAULT 0,
    warnings               JSONB NOT NULL DEFAULT '[]',
    error                  TEXT,
    started_at             TIMESTAMPTZ,
    finished_at            TIMESTAMPTZ,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_source_versions_identity
        UNIQUE (source_id, commit_sha, graphify_version, extraction_config_hash),
    CONSTRAINT ck_knowledge_source_versions_index_identity CHECK (
        index_kind = 'code_graph' OR (index_kind = 'hybrid_vector' AND
        source_revision IS NOT NULL AND indexer_version IS NOT NULL AND index_config_hash IS NOT NULL)
    )
);

ALTER TABLE control_plane.knowledge_sources
    ADD CONSTRAINT fk_knowledge_sources_current_version
    FOREIGN KEY (current_successful_version_id)
    REFERENCES control_plane.knowledge_source_versions(id)
    ON DELETE SET NULL;

CREATE INDEX idx_knowledge_source_versions_source
    ON control_plane.knowledge_source_versions (source_id, created_at DESC);
CREATE INDEX idx_knowledge_source_versions_status
    ON control_plane.knowledge_source_versions (status, created_at DESC);
CREATE UNIQUE INDEX uq_knowledge_source_versions_generic_identity
    ON control_plane.knowledge_source_versions (source_id, source_revision, index_config_hash)
    WHERE index_kind <> 'code_graph';

CREATE TABLE control_plane.knowledge_document_revisions (
    id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id          UUID NOT NULL REFERENCES control_plane.knowledge_sources(id) ON DELETE CASCADE,
    external_id        TEXT NOT NULL,
    provider_revision  TEXT NOT NULL,
    title              TEXT NOT NULL,
    canonical_url      TEXT NOT NULL,
    hierarchy_path     JSONB NOT NULL DEFAULT '[]',
    normalized_content TEXT NOT NULL,
    content_hash       TEXT NOT NULL,
    metadata           JSONB NOT NULL DEFAULT '{}',
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_knowledge_document_revisions_identity UNIQUE (source_id, external_id, content_hash)
);

CREATE INDEX idx_knowledge_document_revisions_source
    ON control_plane.knowledge_document_revisions (source_id, external_id);

CREATE TABLE control_plane.knowledge_chunks (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_revision_id  UUID NOT NULL REFERENCES control_plane.knowledge_document_revisions(id) ON DELETE CASCADE,
    index_config_hash     TEXT NOT NULL,
    ordinal               INT NOT NULL,
    heading_path          JSONB NOT NULL DEFAULT '[]',
    content               TEXT NOT NULL,
    content_hash          TEXT NOT NULL,
    estimated_tokens      INT NOT NULL,
    lexical_text          TEXT NOT NULL,
    search_vector         TSVECTOR NOT NULL,
    embedding             VECTOR NOT NULL,
    embedding_model       TEXT NOT NULL,
    embedding_dimensions  INT NOT NULL,
    CONSTRAINT uq_knowledge_chunks_identity UNIQUE (document_revision_id, index_config_hash, ordinal),
    CONSTRAINT ck_knowledge_chunks_embedding_dimensions
        CHECK (embedding_dimensions > 0 AND vector_dims(embedding) = embedding_dimensions)
);

CREATE INDEX idx_knowledge_chunks_document ON control_plane.knowledge_chunks (document_revision_id);
CREATE INDEX idx_knowledge_chunks_search ON control_plane.knowledge_chunks USING gin (search_vector);

CREATE TABLE control_plane.knowledge_source_version_documents (
    version_id           UUID NOT NULL REFERENCES control_plane.knowledge_source_versions(id) ON DELETE CASCADE,
    document_revision_id UUID NOT NULL REFERENCES control_plane.knowledge_document_revisions(id) ON DELETE RESTRICT,
    external_id          TEXT NOT NULL,
    root_page_id         TEXT NOT NULL,
    PRIMARY KEY (version_id, external_id)
);

CREATE INDEX idx_knowledge_source_version_documents_revision
    ON control_plane.knowledge_source_version_documents (document_revision_id);

CREATE TABLE control_plane.background_job_runs (
    id                          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_type                    TEXT NOT NULL,
    scope                       TEXT,
    trigger                     TEXT,
    knowledge_source_id         UUID REFERENCES control_plane.knowledge_sources(id) ON DELETE SET NULL,
    knowledge_source_version_id UUID REFERENCES control_plane.knowledge_source_versions(id) ON DELETE SET NULL,
    status                      TEXT NOT NULL DEFAULT 'running',
    started_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    heartbeat_at                TIMESTAMPTZ,
    finished_at                 TIMESTAMPTZ,
    duration_sec                FLOAT,
    summary                     JSONB NOT NULL DEFAULT '{}',
    warnings                    JSONB NOT NULL DEFAULT '[]',
    error                       TEXT
);

CREATE INDEX idx_background_job_runs_job_type ON control_plane.background_job_runs (job_type, started_at DESC);
CREATE INDEX idx_background_job_runs_started_at ON control_plane.background_job_runs (started_at DESC);
CREATE INDEX idx_background_job_runs_source
    ON control_plane.background_job_runs (knowledge_source_id, started_at DESC);
CREATE INDEX idx_background_job_runs_version
    ON control_plane.background_job_runs (knowledge_source_version_id);

-- Singleton row (id=1) tracking the connected workflow repo's pinned
-- version and last sync outcome. Bootstrap-owned repo URL/PAT are never
-- stored here.
CREATE TABLE control_plane.workflow_repo_state (
    id                   INT PRIMARY KEY DEFAULT 1,
    pinned_ref           TEXT,
    last_synced_ref      TEXT,
    last_synced_commit   TEXT,
    last_synced_at       TIMESTAMPTZ,
    last_sync_status     TEXT,
    last_sync_error      TEXT,
    discovered_workflows JSONB NOT NULL DEFAULT '[]',
    bundle_errors        JSONB NOT NULL DEFAULT '{}',
    updated              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT workflow_repo_state_singleton CHECK (id = 1)
);

-- ─── Updated-at trigger ─────────────────────────────────────────────

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tasks_updated_at
    BEFORE UPDATE ON task_queue.tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER agents_updated_at
    BEFORE UPDATE ON control_plane.agents
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
