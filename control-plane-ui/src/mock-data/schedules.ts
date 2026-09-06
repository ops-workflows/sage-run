import type { Schedule } from '@/lib/api';

export const MOCK_SCHEDULES: Schedule[] = [
  {
    id: 'sched-001',
    agent_name: 'daily-operations-digest',
    schedule_name: 'daily-morning-digest',
    cron_expression: '0 8 * * 1-5',
    prompt:
      'Generate the daily incident summary for the last 24 hours. Recall all verified RCAs and post an executive digest to #ops-digest.',
    enabled: true,
    last_run_at: '2026-09-05T08:00:00Z',
    next_run_at: '2026-09-08T08:00:00Z',
    created_at: '2026-08-01T12:00:00Z',
  },
  {
    id: 'sched-002',
    agent_name: 'weekly-reflection-and-learning',
    schedule_name: 'weekly-reflection-run',
    cron_expression: '0 9 * * 1',
    prompt:
      'Run the weekly workflow reflection across all operational workflows over the last 7 days. Identify bottlenecks and propose durable PRs.',
    enabled: true,
    last_run_at: '2026-09-01T09:00:00Z',
    next_run_at: '2026-09-08T09:00:00Z',
    created_at: '2026-08-01T12:00:00Z',
  },
  {
    id: 'sched-003',
    agent_name: 'cloud-incident-investigator',
    schedule_name: 'hourly-health-audit',
    cron_expression: '0 * * * *',
    prompt:
      'Run proactive health check on core payment and checkout services, verify connection pool depths and error budget burn.',
    enabled: true,
    last_run_at: '2026-09-05T08:00:00Z',
    next_run_at: '2026-09-05T09:00:00Z',
    created_at: '2026-08-15T10:00:00Z',
  },
  {
    id: 'sched-004',
    agent_name: 'weekly-reflection-and-learning',
    schedule_name: 'hindsight-memory-compaction',
    cron_expression: '0 3 * * 0',
    prompt:
      'Prune stale learning observations older than 90 days from Hindsight memory bank "workflow-learning-ops" and re-weight links.',
    enabled: true,
    last_run_at: '2026-08-31T03:00:00Z',
    next_run_at: '2026-09-07T03:00:00Z',
    created_at: '2026-08-10T11:00:00Z',
  },
];
