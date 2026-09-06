import type {
  GitHubConnection,
  KnowledgeSource,
  KnowledgeSourceVersion,
} from '@/lib/api';

export const MOCK_GITHUB_CONNECTIONS: GitHubConnection[] = [
  {
    name: 'github-enterprise',
    web_base_url: 'https://github.corp.internal',
  },
  {
    name: 'github-public',
    web_base_url: 'https://github.com',
  },
];

export const MOCK_KNOWLEDGE_SOURCES: KnowledgeSource[] = [
  {
    id: 'ks-001',
    canonical_alias: 'cloud-core/checkout-service',
    repository_url:
      'https://github.corp.internal/cloud-core/checkout-service.git',
    default_ref: 'main',
    include_paths: ['src/**', 'config/**', 'docs/architecture/**'],
    exclude_paths: ['tests/**', 'node_modules/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      schedule: 'daily',
      interval_sec: 86400,
    },
    enabled: true,
    current_successful_version_id: 'ksv-001-latest',
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-09-05T02:00:00Z',
  },
  {
    id: 'ks-002',
    canonical_alias: 'cloud-infra/terraform-aws-production',
    repository_url:
      'https://github.corp.internal/cloud-infra/terraform-aws-production.git',
    default_ref: 'main',
    include_paths: ['modules/**', 'environments/production/**'],
    exclude_paths: ['environments/dev/**', '.terraform/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      schedule: 'daily',
      interval_sec: 86400,
    },
    enabled: true,
    current_successful_version_id: 'ksv-002-latest',
    created_at: '2026-08-10T14:00:00Z',
    updated_at: '2026-09-05T02:15:00Z',
  },
  {
    id: 'ks-003',
    canonical_alias: 'enterprise/billing-engine',
    repository_url:
      'https://github.corp.internal/enterprise/billing-engine.git',
    default_ref: 'main',
    include_paths: ['src/classes/**', 'src/triggers/**', 'docs/**'],
    exclude_paths: ['test-data/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      schedule: 'weekly',
      interval_sec: 604800,
    },
    enabled: true,
    current_successful_version_id: 'ksv-003-latest',
    created_at: '2026-08-15T09:30:00Z',
    updated_at: '2026-09-01T04:00:00Z',
  },
];

export const MOCK_KNOWLEDGE_SOURCE_VERSIONS: Record<
  string,
  KnowledgeSourceVersion[]
> = {
  'ks-001': [
    {
      id: 'ksv-001-latest',
      commit_sha: '4d89a2b8e104f992a01948bc',
      status: 'succeeded',
      graphify_version: '1.4.2',
      extraction_config_hash: 'a9b8c7d6e5f4',
      artifact_keys: {
        graph: 'knowledge/ks-001/ksv-001-latest/graph.json',
        index: 'knowledge/ks-001/ksv-001-latest/index.bin',
      },
      artifact_checksums: {
        graph: 'sha256:7f81a9bc4210e...',
      },
      file_count: 184,
      node_count: 3420,
      edge_count: 8912,
      warnings: [],
      error: null,
      started_at: '2026-09-05T02:00:00Z',
      finished_at: '2026-09-05T02:03:45Z',
      created_at: '2026-09-05T02:00:00Z',
    },
    {
      id: 'ksv-001-prev',
      commit_sha: '2c7104ba90812efd9810423a',
      status: 'succeeded',
      graphify_version: '1.4.2',
      extraction_config_hash: 'a9b8c7d6e5f4',
      artifact_keys: {
        graph: 'knowledge/ks-001/ksv-001-prev/graph.json',
      },
      artifact_checksums: {
        graph: 'sha256:3a19dc8102...',
      },
      file_count: 182,
      node_count: 3380,
      edge_count: 8790,
      warnings: [],
      error: null,
      started_at: '2026-09-04T02:00:00Z',
      finished_at: '2026-09-04T02:03:30Z',
      created_at: '2026-09-04T02:00:00Z',
    },
  ],
  'ks-002': [
    {
      id: 'ksv-002-latest',
      commit_sha: '8e12c9a0149bc28f110a421e',
      status: 'succeeded',
      graphify_version: '1.4.2',
      extraction_config_hash: 'b1c2d3e4f5a6',
      artifact_keys: {
        graph: 'knowledge/ks-002/ksv-002-latest/graph.json',
      },
      artifact_checksums: {
        graph: 'sha256:990142bc81...',
      },
      file_count: 92,
      node_count: 1280,
      edge_count: 3110,
      warnings: [],
      error: null,
      started_at: '2026-09-05T02:15:00Z',
      finished_at: '2026-09-05T02:17:12Z',
      created_at: '2026-09-05T02:15:00Z',
    },
  ],
  'ks-003': [
    {
      id: 'ksv-003-latest',
      commit_sha: '1a7f3b49081bc24d89a0123e',
      status: 'succeeded',
      graphify_version: '1.4.2',
      extraction_config_hash: 'c3d4e5f6a1b2',
      artifact_keys: {
        graph: 'knowledge/ks-003/ksv-003-latest/graph.json',
      },
      artifact_checksums: {
        graph: 'sha256:889102ca14...',
      },
      file_count: 145,
      node_count: 2890,
      edge_count: 6420,
      warnings: [],
      error: null,
      started_at: '2026-09-01T04:00:00Z',
      finished_at: '2026-09-01T04:04:10Z',
      created_at: '2026-09-01T04:00:00Z',
    },
  ],
};
