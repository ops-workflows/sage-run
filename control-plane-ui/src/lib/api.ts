export async function apiFetch<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = body?.detail;
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail
              .map(
                (item) =>
                  `${item.loc?.filter((part: unknown) => part !== 'body').join('.') || 'Request'}: ${item.msg}`,
              )
              .join('; ')
          : res.statusText;
    throw new Error(`API error ${res.status}: ${message}`);
  }
  return res.json();
}

export interface UserInfo {
  userId: string;
  groups: string[];
}

export async function fetchUserInfo(
  signal?: AbortSignal,
): Promise<UserInfo | null> {
  const response = await fetch('/api/user-info', { signal });
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

// Types matching the FastAPI response models

export interface Agent {
  id: string;
  name: string;
  description: string | null;
  version: string | null;
  provisioned: boolean;
  paused: boolean;
  provisioned_at: string | null;
  config: Record<string, unknown>;
  repo_path: string | null;
  created: string;
  updated: string;
}

export interface AgentFilesResult {
  agent_yaml: string;
  files: Record<string, string>;
}

export interface Task {
  id: string;
  workflow: string;
  prompt: string;
  status: string;
  channel: string | null;
  initiator: string | null;
  metadata: Record<string, unknown>;
  message_channel: string | null;
  message_thread: string | null;
  tokens_used: number;
  duration_sec: number | null;
  error: string | null;
  wait_reason: string | null;
  wait_deadline: string | null;
  archived_at: string | null;
  created: string;
  updated: string;
}

export interface TaskListResult {
  items: Task[];
  total: number;
  limit: number;
  offset: number;
  workflows: string[];
  channels: string[];
}

export type NodeKind =
  | 'session'
  | 'user'
  | 'assistant'
  | 'thinking'
  | 'messaging'
  | 'tool_call'
  | 'tool_result'
  | 'subagent'
  | 'subagent_progress'
  | 'hook'
  | 'lifecycle'
  | 'result'
  | 'error';

export interface TraceNode {
  id: string;
  kind: NodeKind;
  timestamp: string;
  label: string;
  detail?: string | null;
  body?: string | null;
  duration?: number | null;
  isError?: boolean;
  badge?: string | null;
  children: TraceNode[];
  raw?: unknown;
  meta?: Record<string, string>;
}

export interface SessionStats {
  toolCalls: number;
  toolErrors: number;
  assistantMessages: number;
  subagentSpawns: number;
  totalTurns: number;
  tokensIn: number;
  tokensOut: number;
}

export interface SessionTrace {
  root: TraceNode;
  stats: SessionStats;
  heartbeats: Array<Record<string, unknown>>;
  skillsUsed: string[];
  mcpsUsed: string[];
  eventCount: number;
}

export interface SessionDetail {
  id: string;
  task_id: string | null;
  agent_id: string | null;
  status: string;
  started: string | null;
  ended: string | null;
  duration_sec: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  cost_usd?: number | null;
  turns: number | null;
  task: Task | null;
  tools_used: Array<{ name: string; count: number; total_duration: number }>;
  subagents_used: Array<{ name: string; turns: number; tokens: number }>;
  error: string | null;
  trace: SessionTrace | null;
}

export interface SessionEvent {
  id: string;
  event_type: string;
  timestamp: string;
  data: Record<string, unknown>;
}

export interface Analytics {
  total_tasks: number;
  succeeded: number;
  failed: number;
  avg_duration_sec: number | null;
  total_tokens: number;
  tasks_by_workflow: Record<string, number>;
  tasks_by_status: Record<string, number>;
  daily_counts: Array<{ date: string; count: number }>;
  tokens_by_workflow?: Record<string, number>;
}

export interface TaskResetResult {
  status: string;
  task: Task;
}

export interface TaskDeleteResult {
  status: string;
  task_id: string;
  workflow: string;
  container_removed: boolean;
}

export interface TaskArchiveResult {
  status: string;
  task: Task;
}

export interface Schedule {
  id: string;
  agent_name: string;
  schedule_name: string;
  cron_expression: string;
  prompt: string;
  enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
}

export interface ApprovalItem {
  id: string;
  task_id: string;
  workflow: string | null;
  task_status: string | null;
  approval_kind: string;
  tool_name: string;
  status: string;
  request_preview: string | null;
  reason: string | null;
  resolved_by: string | null;
  resolved_by_user_id: string | null;
  requested_at: string;
  resolved_at: string | null;
  archived_at: string | null;
}

export interface PlatformApprovals {
  counts_by_status: Record<string, number>;
  items: ApprovalItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface McpTool {
  name: string;
  description: string;
  read_only: boolean;
  open_world: boolean;
}

export interface McpServer {
  id: string;
  group: 'platform' | 'workflow';
  name: string;
  description: string;
  usage_count: number;
  used_by: string[];
  tools: McpTool[];
}

export interface Connector {
  id: string;
  name: string;
  summary: string;
  description: string | null;
  source_type: string;
  source_label: string;
  target_workflow: string | null;
  target_channel: string | null;
  tags: string[];
  type: string;
  paused: boolean;
}

export interface WorkflowRepoStatus {
  deployment_enabled: boolean;
  platform_version: string;
  source_url: string | null;
  source_path: string | null;
  source_mode: 'remote' | 'local';
  default_ref: string | null;
  pinned_ref: string | null;
  last_synced_ref: string | null;
  last_synced_commit: string | null;
  last_synced_at: string | null;
  last_sync_status: string | null;
  last_sync_error: string | null;
  discovered_workflows: string[];
  bundle_errors: Record<string, string>;
}

export interface WorkflowRepoVersion {
  name: string;
  commit_sha: string | null;
}

export interface DeploymentStatus {
  id: string;
  ref: string;
  commit: string | null;
  status: 'pending' | 'running' | 'succeeded' | 'failed';
  phase: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  logs?: string;
}

export interface HindsightBank {
  bank_id: string;
  label: string;
  kind: string;
  workflows: string[];
  listed_in_hindsight: boolean;
}

export interface AgentMemory {
  agent_name: string;
  latest_key: string | null;
  latest_updated_at: string | null;
  version_count: number;
}

export interface PlatformMemories {
  hindsight_available: boolean;
  hindsight_banks: HindsightBank[];
  agent_memories: AgentMemory[];
}

export interface BackgroundJobRun {
  id: string;
  job_type: string;
  scope: string | null;
  trigger: string | null;
  knowledge_source_id: string | null;
  knowledge_source_version_id: string | null;
  status: string;
  started_at: string;
  heartbeat_at: string | null;
  finished_at: string | null;
  duration_sec: number | null;
  summary: Record<string, unknown>;
  warnings: string[];
  error: string | null;
}

export interface PlatformBackgroundJobs {
  items: BackgroundJobRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface GitHubSourceConfig {
  repository_url: string;
  default_ref: string;
  include_paths: string[];
  exclude_paths: string[];
}

export interface ConfluenceSourceConfig {
  root_page_ids: string[];
  include_descendants: boolean;
  scrub_patterns: string[];
  body_format: 'storage';
  lexical_config: 'simple' | 'english';
}

interface KnowledgeSourceCommon {
  id: string;
  canonical_alias: string;
  display_name: string;
  serving_suspended_at: string | null;
  serving_suspension_reason: string | null;
  include_paths: string[];
  exclude_paths: string[];
  credential_ref: string | null;
  sync_policy: Record<string, unknown>;
  enabled: boolean;
  current_successful_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export type KnowledgeSource = KnowledgeSourceCommon &
  (
    | {
        source_kind: 'github';
        index_kind: 'code_graph';
        source_config: GitHubSourceConfig;
        repository_url: string;
        default_ref: string;
      }
    | {
        source_kind: 'confluence';
        index_kind: 'hybrid_vector';
        source_config: ConfluenceSourceConfig;
        repository_url: null;
        default_ref: null;
      }
  );

interface KnowledgeSourceWriteCommon {
  canonical_alias?: string;
  display_name?: string;
  credential_ref: string;
  sync_policy: Record<string, unknown>;
  enabled: boolean;
}

export type KnowledgeSourceWrite = KnowledgeSourceWriteCommon &
  (
    | {
        source_kind: 'github';
        index_kind: 'code_graph';
        repository: string;
        default_ref: string;
        include_paths: string[];
        exclude_paths: string[];
      }
    | {
        source_kind: 'confluence';
        index_kind: 'hybrid_vector';
        source_config: Omit<ConfluenceSourceConfig, 'root_page_ids'> &
          ({ root_page_ids: string[] } | { root_pages: string[] });
      }
  );

export function knowledgeSourcePayload(
  source: KnowledgeSource,
): KnowledgeSourceWrite {
  const common = {
    canonical_alias: source.canonical_alias,
    display_name: source.display_name,
    credential_ref: source.credential_ref || '',
    sync_policy: { ...source.sync_policy },
    enabled: source.enabled,
  };
  if (source.source_kind === 'confluence') {
    return {
      ...common,
      source_kind: 'confluence',
      index_kind: 'hybrid_vector',
      source_config: {
        ...source.source_config,
        root_page_ids: [...source.source_config.root_page_ids],
        scrub_patterns: [...(source.source_config.scrub_patterns || [])],
      },
    };
  }
  const config = source.source_config;
  const parts = new URL(config.repository_url).pathname
    .split('/')
    .filter(Boolean);
  const repository = parts
    .slice(-2)
    .join('/')
    .replace(/\.git$/, '');
  return {
    ...common,
    source_kind: 'github',
    index_kind: 'code_graph',
    repository,
    default_ref: config.default_ref,
    include_paths: [...config.include_paths],
    exclude_paths: [...config.exclude_paths],
  };
}

export interface GitHubConnection {
  name: string;
  web_base_url: string;
}

export interface ConfluenceConnection {
  name: string;
  base_url: string;
}

export interface KnowledgeSourceVersion {
  id: string;
  source_revision: string | null;
  index_kind: 'code_graph' | 'hybrid_vector';
  indexer_version: string | null;
  index_config_hash: string | null;
  stats: Record<string, unknown>;
  commit_sha: string | null;
  status: string;
  graphify_version: string | null;
  extraction_config_hash: string | null;
  artifact_keys: Record<string, unknown>;
  artifact_checksums: Record<string, unknown>;
  file_count: number;
  node_count: number;
  edge_count: number;
  warnings: unknown[];
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
}

export interface HindsightMemoryEntry {
  id: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
}

export interface HindsightGraphNode {
  id: string;
  label: string;
  node_type: string;
}

export interface HindsightGraphEdge {
  source: string;
  target: string;
  edge_type: string;
  weight: number | null;
}

export interface HindsightGraphPreview {
  nodes: HindsightGraphNode[];
  edges: HindsightGraphEdge[];
  table_rows: Array<Record<string, unknown>>;
  total_units: number;
}

export interface HindsightBankStats {
  total_nodes: number;
  total_links: number;
  total_documents: number;
  total_observations: number;
  pending_operations: number;
  failed_operations: number;
  nodes_by_fact_type: Record<string, number>;
  links_by_link_type: Record<string, number>;
}

export interface HindsightBankDetail {
  bank_id: string;
  listed_in_hindsight: boolean;
  warnings: string[];
  stats: HindsightBankStats;
  graph: HindsightGraphPreview | null;
  entries: HindsightMemoryEntry[];
}

export interface AgentMemoryFile {
  path: string;
  size_bytes: number;
  preview: string;
}

export interface AgentMemoryDetail {
  agent_name: string;
  archive_key: string | null;
  files: AgentMemoryFile[];
}
