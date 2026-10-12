import type {
  ConfluenceConnection,
  GitHubConnection,
  KnowledgeSource,
  KnowledgeSourceVersion,
  KnowledgeSourceWrite,
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

export const MOCK_CONFLUENCE_CONNECTIONS: ConfluenceConnection[] = [
  { name: 'corporate-wiki', base_url: 'https://company.atlassian.net/wiki' },
];

export const MOCK_KNOWLEDGE_SOURCES: KnowledgeSource[] = [
  {
    id: 'ks-001',
    canonical_alias: 'checkout-service',
    display_name: 'Checkout service',
    source_kind: 'github',
    index_kind: 'code_graph',
    source_config: {
      repository_url:
        'https://github.corp.internal/cloud-core/checkout-service.git',
      default_ref: 'main',
      include_paths: ['src/**', 'config/**', 'docs/architecture/**'],
      exclude_paths: ['tests/**', 'node_modules/**'],
    },
    serving_suspended_at: null,
    serving_suspension_reason: null,
    repository_url:
      'https://github.corp.internal/cloud-core/checkout-service.git',
    default_ref: 'main',
    include_paths: ['src/**', 'config/**', 'docs/architecture/**'],
    exclude_paths: ['tests/**', 'node_modules/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      interval_sec: 86400,
    },
    enabled: true,
    current_successful_version_id: 'ksv-001-latest',
    created_at: '2026-08-01T10:00:00Z',
    updated_at: '2026-09-05T02:00:00Z',
  },
  {
    id: 'ks-002',
    canonical_alias: 'terraform-aws-production',
    display_name: 'Terraform AWS production',
    source_kind: 'github',
    index_kind: 'code_graph',
    source_config: {
      repository_url:
        'https://github.corp.internal/cloud-infra/terraform-aws-production.git',
      default_ref: 'main',
      include_paths: ['modules/**', 'environments/production/**'],
      exclude_paths: ['environments/dev/**', '.terraform/**'],
    },
    serving_suspended_at: null,
    serving_suspension_reason: null,
    repository_url:
      'https://github.corp.internal/cloud-infra/terraform-aws-production.git',
    default_ref: 'main',
    include_paths: ['modules/**', 'environments/production/**'],
    exclude_paths: ['environments/dev/**', '.terraform/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      interval_sec: 86400,
    },
    enabled: true,
    current_successful_version_id: 'ksv-002-latest',
    created_at: '2026-08-10T14:00:00Z',
    updated_at: '2026-09-05T02:15:00Z',
  },
  {
    id: 'ks-003',
    canonical_alias: 'billing-engine',
    display_name: 'Billing engine',
    source_kind: 'github',
    index_kind: 'code_graph',
    source_config: {
      repository_url:
        'https://github.corp.internal/enterprise/billing-engine.git',
      default_ref: 'main',
      include_paths: ['src/classes/**', 'src/triggers/**', 'docs/**'],
      exclude_paths: ['test-data/**'],
    },
    serving_suspended_at: null,
    serving_suspension_reason: null,
    repository_url:
      'https://github.corp.internal/enterprise/billing-engine.git',
    default_ref: 'main',
    include_paths: ['src/classes/**', 'src/triggers/**', 'docs/**'],
    exclude_paths: ['test-data/**'],
    credential_ref: 'github-enterprise',
    sync_policy: {
      interval_sec: 604800,
    },
    enabled: true,
    current_successful_version_id: 'ksv-003-latest',
    created_at: '2026-08-15T09:30:00Z',
    updated_at: '2026-09-01T04:00:00Z',
  },
  {
    id: 'ks-004',
    canonical_alias: 'platform-runbooks',
    display_name: 'Platform runbooks',
    source_kind: 'confluence',
    index_kind: 'hybrid_vector',
    source_config: {
      root_page_ids: ['123456', '789012'],
      include_descendants: true,
      scrub_patterns: [],
      body_format: 'storage',
      lexical_config: 'simple',
    },
    repository_url: null,
    default_ref: null,
    include_paths: [],
    exclude_paths: [],
    credential_ref: 'corporate-wiki',
    sync_policy: { interval_sec: 3600 },
    enabled: true,
    serving_suspended_at: null,
    serving_suspension_reason: null,
    current_successful_version_id: 'ksv-004-latest',
    created_at: '2026-09-01T10:00:00Z',
    updated_at: '2026-10-02T08:00:00Z',
  },
];

export const MOCK_KNOWLEDGE_SOURCE_VERSIONS: Record<
  string,
  KnowledgeSourceVersion[]
> = {
  'ks-001': [
    {
      id: 'ksv-001-latest',
      source_revision: '4d89a2b8e104f992a01948bc',
      index_kind: 'code_graph',
      indexer_version: '1.4.2',
      index_config_hash: 'a9b8c7d6e5f4',
      stats: {},
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
      source_revision: '2c7104ba90812efd9810423a',
      index_kind: 'code_graph',
      indexer_version: '1.4.2',
      index_config_hash: 'a9b8c7d6e5f4',
      stats: {},
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
      source_revision: '8e12c9a0149bc28f110a421e',
      index_kind: 'code_graph',
      indexer_version: '1.4.2',
      index_config_hash: 'b1c2d3e4f5a6',
      stats: {},
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
      source_revision: '1a7f3b49081bc24d89a0123e',
      index_kind: 'code_graph',
      indexer_version: '1.4.2',
      index_config_hash: 'c3d4e5f6a1b2',
      stats: {},
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
  'ks-004': [
    {
      id: 'ksv-004-latest',
      source_revision: 'snapshot-20261002-8f41922e',
      index_kind: 'hybrid_vector',
      indexer_version: 'hybrid-1',
      index_config_hash: 'hybrid-config-1',
      stats: {
        discovered_pages: 42,
        indexed_pages: 40,
        reused_pages: 38,
        removed_pages: 2,
        chunks_embedded: 18,
        chunks_reused: 312,
      },
      commit_sha: null,
      graphify_version: null,
      extraction_config_hash: null,
      status: 'succeeded',
      artifact_keys: {},
      artifact_checksums: {},
      file_count: 0,
      node_count: 0,
      edge_count: 0,
      warnings: [],
      error: null,
      started_at: '2026-10-02T08:00:00Z',
      finished_at: '2026-10-02T08:01:00Z',
      created_at: '2026-10-02T08:00:00Z',
    },
  ],
};

export function mockKnowledgeSourceWrite(
  body: unknown,
  previous?: KnowledgeSource,
): { status: number; data: unknown } {
  try {
    if (!body || typeof body !== 'object' || Array.isArray(body))
      throw new Error('Expected a source request');
    const raw = body as Record<string, unknown>;
    const kind = raw.source_kind ?? 'github';
    const allowed = [
      'canonical_alias',
      'display_name',
      'source_kind',
      'index_kind',
      'credential_ref',
      'sync_policy',
      'enabled',
      ...(kind === 'github'
        ? ['repository', 'default_ref', 'include_paths', 'exclude_paths']
        : ['source_config']),
    ];
    if (Object.keys(raw).some((key) => !allowed.includes(key)))
      throw new Error('Unknown source fields');
    if (kind !== 'github' && kind !== 'confluence')
      throw new Error('Unsupported source_kind');
    if (
      raw.index_kind !== undefined &&
      raw.index_kind !== (kind === 'github' ? 'code_graph' : 'hybrid_vector')
    )
      throw new Error('Unsupported index_kind');
    if (kind === 'confluence' && raw.index_kind !== 'hybrid_vector')
      throw new Error('Confluence requires hybrid_vector');
    if (previous && previous.source_kind !== kind)
      throw new Error('Source kind is immutable; create a new source');
    if (
      previous &&
      raw.canonical_alias !== undefined &&
      raw.canonical_alias !== previous.canonical_alias
    )
      throw new Error('canonical_alias is immutable; create a new source');
    if (
      raw.canonical_alias !== undefined &&
      (typeof raw.canonical_alias !== 'string' ||
        !/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(raw.canonical_alias))
    )
      throw new Error('Invalid canonical_alias');
    if (
      raw.display_name !== undefined &&
      (typeof raw.display_name !== 'string' ||
        !raw.display_name.trim() ||
        raw.display_name.length > 200)
    )
      throw new Error('Invalid display_name');
    if (raw.enabled !== undefined && typeof raw.enabled !== 'boolean')
      throw new Error('enabled must be boolean');
    if (typeof raw.credential_ref !== 'string')
      throw new Error('Select a configured connection');
    const policy = raw.sync_policy ?? {};
    if (!policy || typeof policy !== 'object' || Array.isArray(policy))
      throw new Error('Invalid sync_policy');
    const interval = (policy as Record<string, unknown>).interval_sec;
    if (
      Object.keys(policy).length &&
      (Object.keys(policy).join() !== 'interval_sec' ||
        typeof interval !== 'number' ||
        !Number.isInteger(interval) ||
        interval <= 0)
    )
      throw new Error(
        'sync_policy supports only a positive integer interval_sec',
      );
    const request = raw as unknown as KnowledgeSourceWrite;
    const timestamp = new Date().toISOString();
    const common = {
      id: previous?.id || crypto.randomUUID(),
      canonical_alias:
        previous?.canonical_alias || request.canonical_alias || '',
      display_name:
        request.display_name?.trim() ||
        previous?.display_name ||
        request.canonical_alias ||
        '',
      credential_ref: request.credential_ref.trim(),
      sync_policy: { ...policy },
      enabled: request.enabled ?? true,
      current_successful_version_id:
        previous?.current_successful_version_id || null,
      serving_suspended_at: previous?.serving_suspended_at || null,
      serving_suspension_reason: previous?.serving_suspension_reason || null,
      created_at: previous?.created_at || timestamp,
      updated_at: timestamp,
    };
    let source: KnowledgeSource;
    if (kind === 'confluence') {
      const connection = MOCK_CONFLUENCE_CONNECTIONS.find(
        (item) => item.name === common.credential_ref,
      );
      if (!connection)
        throw new Error(
          'credential_ref must name a configured Confluence connection',
        );
      const config = raw.source_config as Record<string, unknown>;
      if (
        !config ||
        typeof config !== 'object' ||
        Array.isArray(config) ||
        Object.keys(config).some(
          (key) =>
            ![
              'root_pages',
              'root_page_ids',
              'include_descendants',
              'body_format',
              'lexical_config',
              'scrub_patterns',
            ].includes(key),
        )
      )
        throw new Error('Invalid source_config');
      if (
        (config.root_pages === undefined) ===
        (config.root_page_ids === undefined)
      )
        throw new Error('Provide exactly one of root_pages or root_page_ids');
      const roots = config.root_pages ?? config.root_page_ids;
      if (
        !Array.isArray(roots) ||
        !roots.length ||
        roots.length > 100 ||
        roots.some((root) => typeof root !== 'string')
      )
        throw new Error('Provide root page URLs or numeric IDs');
      if (
        config.include_descendants !== undefined &&
        typeof config.include_descendants !== 'boolean'
      )
        throw new Error('include_descendants must be boolean');
      const patterns = config.scrub_patterns ?? [];
      if (
        !Array.isArray(patterns) ||
        patterns.length > 100 ||
        patterns.some(
          (pattern) =>
            typeof pattern !== 'string' ||
            pattern.length > 2000 ||
            /[\r\n]/.test(pattern),
        )
      )
        throw new Error('Invalid scrub_patterns');
      if (config.body_format !== undefined && config.body_format !== 'storage')
        throw new Error('body_format must be storage');
      if (
        config.lexical_config !== undefined &&
        !['simple', 'english'].includes(String(config.lexical_config))
      )
        throw new Error('Unsupported lexical_config');
      const ids = roots.map((root: string) => {
        const value = root.trim();
        if (/^[0-9]+$/.test(value)) return value;
        if (config.root_page_ids !== undefined)
          throw new Error('root_page_ids must be numeric');
        const url = new URL(value);
        const base = new URL(connection.base_url);
        const relative = url.pathname.slice(base.pathname.length);
        if (
          url.origin !== base.origin ||
          url.username ||
          url.password ||
          url.hash ||
          !url.pathname.startsWith(`${base.pathname}/`) ||
          value.includes('\\') ||
          Array.from(value).some((character) => character.charCodeAt(0) < 32)
        )
          throw new Error(
            'Root URL must match the selected connection origin and base path',
          );
        const match = relative.match(
          /^\/spaces\/[^/]+\/pages\/([0-9]+)(?:\/[^/]*)?$/,
        );
        if (match && !url.search) return match[1];
        const pageIds = url.searchParams.getAll('pageId');
        if (
          relative === '/pages/viewpage.action' &&
          Array.from(url.searchParams.keys()).every(
            (key) => key === 'pageId',
          ) &&
          pageIds.length === 1 &&
          /^[0-9]+$/.test(pageIds[0])
        )
          return pageIds[0];
        throw new Error('Use a supported Confluence page URL or numeric ID');
      });
      source = {
        ...common,
        source_kind: 'confluence',
        index_kind: 'hybrid_vector',
        repository_url: null,
        default_ref: null,
        include_paths: [],
        exclude_paths: [],
        source_config: {
          root_page_ids: [...new Set(ids)].sort(),
          include_descendants:
            config.include_descendants === undefined
              ? true
              : (config.include_descendants as boolean),
          scrub_patterns: (patterns as string[]).filter((pattern) =>
            pattern.trim(),
          ),
          body_format: 'storage',
          lexical_config:
            config.lexical_config === 'english' ? 'english' : 'simple',
        },
      };
    } else {
      const connection = MOCK_GITHUB_CONNECTIONS.find(
        (item) => item.name === common.credential_ref,
      );
      if (!connection)
        throw new Error(
          'credential_ref must name a configured GitHub connection',
        );
      if (
        typeof raw.repository !== 'string' ||
        !/^[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+$/.test(raw.repository)
      )
        throw new Error('repository must use organization/repository');
      const ref = raw.default_ref ?? 'main';
      if (typeof ref !== 'string' || !ref.trim())
        throw new Error('default_ref is required');
      const scopes = ['include_paths', 'exclude_paths'].map((key) => {
        const patterns = raw[key] ?? [];
        if (
          !Array.isArray(patterns) ||
          patterns.some(
            (item) =>
              typeof item !== 'string' ||
              !item ||
              item.startsWith('/') ||
              item.includes('\\') ||
              item.split('/').includes('..'),
          )
        )
          throw new Error('Path scopes must be safe repository-relative globs');
        return patterns as string[];
      });
      common.canonical_alias ||= raw.repository.split('/')[1];
      common.display_name ||= common.canonical_alias;
      const config = {
        repository_url: `${connection.web_base_url}/${raw.repository}.git`,
        default_ref: ref.trim(),
        include_paths: [...scopes[0]],
        exclude_paths: [...scopes[1]],
      };
      source = {
        ...common,
        source_kind: 'github',
        index_kind: 'code_graph',
        source_config: config,
        ...config,
      };
    }
    if (!source.canonical_alias)
      throw new Error(
        'canonical_alias is required for a new Confluence source',
      );
    if (
      MOCK_KNOWLEDGE_SOURCES.some(
        (item) =>
          item.id !== source.id &&
          item.canonical_alias === source.canonical_alias,
      )
    )
      return {
        status: 409,
        data: { detail: 'Knowledge Source alias already exists' },
      };
    const sensitive =
      previous &&
      (previous.credential_ref !== source.credential_ref ||
        (previous.source_kind === 'confluence' &&
        source.source_kind === 'confluence'
          ? JSON.stringify(previous.source_config.root_page_ids) !==
            JSON.stringify(source.source_config.root_page_ids)
          : JSON.stringify(previous.source_config) !==
            JSON.stringify(source.source_config)));
    if (sensitive) {
      source.serving_suspended_at = timestamp;
      source.serving_suspension_reason =
        'Source roots, scope, or connection changed; queue a successful sync to resume serving';
    }
    return { status: previous ? 200 : 201, data: source };
  } catch (error) {
    return {
      status: 422,
      data: {
        detail:
          error instanceof Error ? error.message : 'Invalid source request',
      },
    };
  }
}
