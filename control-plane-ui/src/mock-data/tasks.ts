import type { Task, TaskListResult } from '@/lib/api';

type Run = Pick<Task, 'id' | 'workflow' | 'prompt' | 'channel' | 'created' | 'updated'> &
  Partial<Omit<Task, 'id' | 'workflow' | 'prompt' | 'channel' | 'created' | 'updated'>>;

function run(input: Run): Task {
  return {
    status: 'succeeded',
    initiator: null,
    message_channel: null,
    message_thread: null,
    tokens_used: 0,
    duration_sec: (Date.parse(input.updated) - Date.parse(input.created)) / 1000,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    ...input,
    metadata: {
      demo: true,
      run: input.id.toUpperCase(),
      ...input.metadata,
    },
  };
}

export const MOCK_TASKS: Task[] = [
  run({
    id: 'run-1070', workflow: 'platform-ops-assistant', channel: 'schedule',
    prompt: 'Review the past week of Ops Assistant learning traces. Propose a small skill update if the pattern is repeatable.',
    message_channel: 'workflow-learning', message_thread: 'reflection-1070',
    tokens_used: 5180, created: '2026-11-20T16:00:00Z', updated: '2026-11-20T16:05:00Z',
    metadata: { triggered_by: 'scheduler', schedule: 'weekly-reflection', learning_bank: 'ops-learning', pull_request: '#34' },
  }),
  run({
    id: 'run-1060', workflow: 'support-ticket-triage', channel: 'servicenow',
    prompt: 'Triage INC-308: checkout worker queue delayed in production. Review the record and CMDB ownership before proposing a route.',
    message_channel: 'support-triage', message_thread: 'support-308',
    tokens_used: 3880, created: '2026-11-16T12:23:00Z', updated: '2026-11-16T12:28:00Z',
    metadata: { source: 'servicenow', incident: 'INC-308', approval: 'APR-60', policy: 'Illustrative approval-gated update' },
  }),
  run({
    id: 'run-1055', workflow: 'sf-alerts-investigator', channel: 'gcp-pubsub',
    prompt: 'Investigate the Salesforce order confirmation Flow alert received via GCP Pub/Sub. A retry failed on a duplicate follow-up task insert.',
    message_channel: 'crm-ops', message_thread: 'crm-431',
    tokens_used: 9720, created: '2026-11-16T11:02:00Z', updated: '2026-11-16T11:09:00Z',
    metadata: { source: 'gcp-pubsub', input: 'Salesforce email via Cloud Storage', approval: 'APR-55', jira_issue: 'CRM-431', policy: 'Illustrative Jira escalation' },
  }),
  run({
    id: 'run-1056', workflow: 'documentation', channel: 'message',
    prompt: 'Propose a replacement for step 2 of Stalled worker recovery. The dashboard named in the runbook has been retired.',
    message_channel: 'docs-review', message_thread: 'docs-1056',
    tokens_used: 2450, created: '2026-11-16T10:08:00Z', updated: '2026-11-16T10:11:00Z',
    metadata: { source: 'agent-handoff', source_task_id: 'run-1050', policy: 'Illustrative Ops-to-Docs handoff' },
  }),
  run({
    id: 'run-1050', workflow: 'platform-ops-assistant', channel: 'mattermost',
    prompt: 'Which runbook should I use for a stuck checkout worker?',
    initiator: 'jules.park', message_channel: 'ask-ops', message_thread: 'ops-1050',
    tokens_used: 4640, created: '2026-11-16T10:03:00Z', updated: '2026-11-16T10:08:00Z',
    metadata: { source: 'mattermost', knowledge_source: 'checkout-operations', source_revision: 'v12', handoff_task: 'run-1056' },
  }),
  run({
    id: 'run-1043', workflow: 'online-alerts-investigator', channel: 'mattermost',
    prompt: 'Thread follow-up: Maya asks whether signed-in customers were affected. Leo reports a 09:19 rollback and asks whether the drop lines up.',
    initiator: 'leo.ortiz', message_channel: 'checkout-alerts', message_thread: 'evt-482',
    tokens_used: 3670, created: '2026-11-16T09:24:00Z', updated: '2026-11-16T09:29:00Z',
    metadata: { source: 'mattermost', source_task_id: 'run-1042', issue: '#217', thread_context_count: 5 },
  }),
  run({
    id: 'run-1042', workflow: 'online-alerts-investigator', channel: 'mattermost',
    prompt: 'CloudWatch ALARM EVT-482: checkout API 5xx exceeded 3% for 5 minutes in production (us-east-1).',
    message_channel: 'checkout-alerts', message_thread: 'evt-482',
    tokens_used: 13150, created: '2026-11-16T09:14:00Z', updated: '2026-11-16T09:20:00Z',
    metadata: { source: 'mattermost', provider: 'CloudWatch', is_bot: true, alert: 'EVT-482', issue: '#217', knowledge_source: 'checkout-platform' },
  }),
  run({
    id: 'run-1039', workflow: 'documentation', channel: 'schedule', status: 'queued',
    prompt: 'Check the latest merged checkout PRs for changes to recovery procedures. Draft a runbook update for review if needed.',
    created: '2026-11-15T02:00:00Z', updated: '2026-11-15T02:00:00Z', duration_sec: null,
    metadata: { triggered_by: 'scheduler', schedule: 'nightly-docs-review' },
  }),
  run({
    id: 'run-1037', workflow: 'platform-ops-assistant', channel: 'mattermost', status: 'queued',
    prompt: 'Find the production checklist for the holiday checkout readiness review.',
    initiator: 'jules.park', message_channel: 'ask-ops', message_thread: 'ops-1037',
    created: '2026-11-14T14:10:00Z', updated: '2026-11-14T14:10:00Z', duration_sec: null,
  }),
];

export function getMockTaskList(params: {
  status?: string;
  workflows?: string[];
  channels?: string[];
  includeArchived?: boolean;
  limit?: number;
  offset?: number;
}): TaskListResult {
  const options = MOCK_TASKS.filter(
    (task) =>
      (params.includeArchived || !task.archived_at) &&
      (!params.status || params.status === 'all' || task.status === params.status),
  );
  const filtered = options.filter(
    (task) =>
      (!params.workflows?.length || params.workflows.includes(task.workflow)) &&
      (!params.channels?.length ||
        (task.channel && params.channels.includes(task.channel))),
  );
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
    workflows: Array.from(new Set(options.map((task) => task.workflow))).sort(),
    channels: Array.from(
      new Set(options.flatMap((task) => (task.channel ? [task.channel] : []))),
    ).sort(),
  };
}
