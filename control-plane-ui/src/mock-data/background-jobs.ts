import type { BackgroundJobRun, PlatformBackgroundJobs } from '@/lib/api';

export const MOCK_BACKGROUND_JOBS: BackgroundJobRun[] = [
  {
    id: 'job-001',
    job_type: 'knowledge_source_sync',
    scope: 'cloud-core/checkout-service',
    trigger: 'scheduled',
    knowledge_source_id: 'ks-001',
    knowledge_source_version_id: 'ksv-001-latest',
    status: 'succeeded',
    started_at: '2026-09-05T02:00:00Z',
    heartbeat_at: '2026-09-05T02:03:30Z',
    finished_at: '2026-09-05T02:03:45Z',
    duration_sec: 225.4,
    summary: {
      files_scanned: 184,
      nodes_indexed: 3420,
      edges_linked: 8912,
      symbols_extracted: 1420,
    },
    warnings: [],
    error: null,
  },
  {
    id: 'job-002',
    job_type: 'knowledge_source_sync',
    scope: 'cloud-infra/terraform-aws-production',
    trigger: 'scheduled',
    knowledge_source_id: 'ks-002',
    knowledge_source_version_id: 'ksv-002-latest',
    status: 'succeeded',
    started_at: '2026-09-05T02:15:00Z',
    heartbeat_at: '2026-09-05T02:17:00Z',
    finished_at: '2026-09-05T02:17:12Z',
    duration_sec: 132.0,
    summary: {
      files_scanned: 92,
      nodes_indexed: 1280,
      edges_linked: 3110,
    },
    warnings: [],
    error: null,
  },
  {
    id: 'job-003',
    job_type: 'memory_volume_backup',
    scope: 'agent-memory-cloud-incident-investigator',
    trigger: 'post_session',
    knowledge_source_id: null,
    knowledge_source_version_id: null,
    status: 'succeeded',
    started_at: '2026-09-05T08:15:15Z',
    heartbeat_at: '2026-09-05T08:15:18Z',
    finished_at: '2026-09-05T08:15:19Z',
    duration_sec: 4.2,
    summary: {
      bytes_uploaded: 412890,
      object_key:
        'agent-memory/incident-coordinator/2026-09-05T08-15-13Z.tar.gz',
    },
    warnings: [],
    error: null,
  },
  {
    id: 'job-004',
    job_type: 'hindsight_memory_compaction',
    scope: 'workflow-learning-ops',
    trigger: 'scheduled',
    knowledge_source_id: null,
    knowledge_source_version_id: null,
    status: 'succeeded',
    started_at: '2026-08-31T03:00:00Z',
    heartbeat_at: '2026-08-31T03:04:10Z',
    finished_at: '2026-08-31T03:04:42Z',
    duration_sec: 282.0,
    summary: {
      stale_observations_pruned: 38,
      nodes_reweighted: 92,
    },
    warnings: [],
    error: null,
  },
  {
    id: 'job-005',
    job_type: 'task_archival_pass',
    scope: 'task_queue.tasks',
    trigger: 'maintenance',
    knowledge_source_id: null,
    knowledge_source_version_id: null,
    status: 'succeeded',
    started_at: '2026-09-05T01:00:00Z',
    heartbeat_at: '2026-09-05T01:00:30Z',
    finished_at: '2026-09-05T01:00:45Z',
    duration_sec: 45.1,
    summary: {
      tasks_archived: 24,
      events_compressed: 480,
    },
    warnings: [],
    error: null,
  },
];

export function getMockBackgroundJobs(params: {
  job_type?: string;
  status?: string;
  trigger?: string;
  knowledge_source_id?: string;
  limit?: number;
  offset?: number;
}): PlatformBackgroundJobs {
  let filtered = MOCK_BACKGROUND_JOBS;
  if (params.job_type) {
    filtered = filtered.filter((j) => j.job_type === params.job_type);
  }
  if (params.status) {
    filtered = filtered.filter((j) => j.status === params.status);
  }
  if (params.trigger) {
    filtered = filtered.filter((j) => j.trigger === params.trigger);
  }
  if (params.knowledge_source_id) {
    filtered = filtered.filter(
      (j) => j.knowledge_source_id === params.knowledge_source_id,
    );
  }
  const limit = params.limit ?? 20;
  const offset = params.offset ?? 0;
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
  };
}
