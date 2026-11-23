import type { Schedule } from '@/lib/api';

export const MOCK_SCHEDULES: Schedule[] = [
  {
    id: 'schedule-weekly-reflection',
    agent_name: 'platform-ops-assistant',
    schedule_name: 'weekly-reflection',
    cron_expression: '0 16 * * 5',
    prompt:
      'Review the past week of Ops Assistant learning traces. Propose a small skill update if the pattern is repeatable.',
    enabled: true,
    last_run_at: '2026-11-20T16:00:00Z',
    next_run_at: '2026-11-27T16:00:00Z',
    created_at: '2026-11-12T10:00:00Z',
  },
  {
    id: 'schedule-nightly-docs-review',
    agent_name: 'documentation',
    schedule_name: 'nightly-docs-review',
    cron_expression: '0 2 * * *',
    prompt:
      'Review PRs merged into checkout-platform since the last nightly run. Draft a runbook update only if a merge changes an operator procedure. Post for review; do not publish.',
    enabled: true,
    last_run_at: '2026-11-20T02:00:00Z',
    next_run_at: '2026-11-21T02:00:00Z',
    created_at: '2026-11-12T10:00:00Z',
  },
  {
    id: 'schedule-support-handover',
    agent_name: 'support-ticket-triage',
    schedule_name: 'weekday-support-handover',
    cron_expression: '30 7 * * 1-5',
    prompt:
      'Summarize unassigned checkout incidents and outstanding routing approvals for the incoming support shift. Do not edit records.',
    enabled: true,
    last_run_at: '2026-11-20T07:30:00Z',
    next_run_at: '2026-11-23T07:30:00Z',
    created_at: '2026-11-12T10:00:00Z',
  },
  {
    id: 'schedule-crm-reliability-digest',
    agent_name: 'sf-alerts-investigator',
    schedule_name: 'weekly-crm-reliability-digest',
    cron_expression: '0 9 * * 1',
    prompt:
      'Group the last seven days of recorded Flow failures by signature and summarize open Jira follow-ups for the CRM owner. Do not file tickets.',
    enabled: false,
    last_run_at: null,
    next_run_at: null,
    created_at: '2026-11-12T10:00:00Z',
  },
];
