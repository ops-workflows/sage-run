import type { ApprovalItem, PlatformApprovals } from '@/lib/api';
import { MOCK_TASKS } from './tasks';

export const MOCK_APPROVALS: ApprovalItem[] = [
  {
    id: 'APR-60',
    task_id: 'run-1060',
    workflow: 'support-ticket-triage',
    task_status: 'succeeded',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__servicenow-triage__update_ticket',
    status: 'approved',
    request_preview:
      'Update INC-308: Support Intake → Checkout Operations; add CMDB evidence to the work note. Illustrative approval-gated update.',
    reason: null,
    resolved_by: 'Noor Vale',
    resolved_by_user_id: 'noor.vale',
    requested_at: '2026-11-16T12:26:00Z',
    resolved_at: '2026-11-16T12:27:00Z',
    archived_at: null,
  },
  {
    id: 'APR-55',
    task_id: 'run-1055',
    workflow: 'sf-alerts-investigator',
    task_status: 'succeeded',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__jira__create_bug_ticket',
    status: 'approved',
    request_preview:
      'File a Jira Bug for duplicate order-confirmation Flow inserts. Illustrative Jira escalation.',
    reason: null,
    resolved_by: 'Maya Chen',
    resolved_by_user_id: 'maya.chen',
    requested_at: '2026-11-16T11:06:00Z',
    resolved_at: '2026-11-16T11:08:00Z',
    archived_at: null,
  },
  {
    id: 'APR-52',
    task_id: 'run-1038',
    workflow: 'support-ticket-triage',
    task_status: null,
    approval_kind: 'tool_execution',
    tool_name: 'mcp__servicenow-triage__update_ticket',
    status: 'pending',
    request_preview:
      'Route INC-302 from Support Intake to Customer Accounts. No change has been made.',
    reason: null,
    resolved_by: null,
    resolved_by_user_id: null,
    requested_at: '2026-11-15T08:18:00Z',
    resolved_at: null,
    archived_at: null,
  },
  {
    id: 'APR-49',
    task_id: 'run-1035',
    workflow: 'sf-alerts-investigator',
    task_status: null,
    approval_kind: 'tool_execution',
    tool_name: 'mcp__jira__create_bug_ticket',
    status: 'rejected',
    request_preview:
      'File a bug for duplicate renewal reminders. Rejected: existing CRM-425 already tracks the same failure.',
    reason: 'Existing CRM-425 already tracks the same failure.',
    resolved_by: 'Maya Chen',
    resolved_by_user_id: 'maya.chen',
    requested_at: '2026-11-13T10:13:00Z',
    resolved_at: '2026-11-13T10:16:00Z',
    archived_at: null,
  },
];

export function getMockPlatformApprovals(
  limit = 100,
  offset = 0,
): PlatformApprovals {
  const items = MOCK_APPROVALS.map((approval) => ({
    ...approval,
    task_status:
      MOCK_TASKS.find((task) => task.id === approval.task_id)?.status ?? null,
  }));
  return {
    items: items.slice(offset, offset + limit),
    total: items.length,
    counts_by_status: {
      pending: items.filter((item) => item.status === 'pending').length,
      approved: items.filter((item) => item.status === 'approved').length,
      rejected: items.filter((item) => item.status === 'rejected').length,
    },
    limit,
    offset,
  };
}
