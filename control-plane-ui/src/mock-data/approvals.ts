import type { ApprovalItem, PlatformApprovals } from '@/lib/api';

export const MOCK_APPROVALS: ApprovalItem[] = [
  {
    id: 'appr-001',
    task_id: '5f597719-0a6d-4e68-abe0-eb0c8fa669b0',
    workflow: 'online-platform-triage',
    task_status: 'succeeded',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__platform__execute_remediation_action',
    status: 'approved',
    request_preview:
      'kubectl rollout restart deployment/auth-service-v2 -n production',
    reason: 'Restart hung replica pool pods to clear CLOSE_WAIT sockets.',
    resolved_by: 'Alex Morales',
    resolved_by_user_id: 'alex.morales@corp.internal',
    requested_at: '2026-09-05T08:23:26Z',
    resolved_at: '2026-09-05T08:23:38Z',
    archived_at: null,
  },
  {
    id: 'appr-002',
    task_id: '6a4132ca-1306-463e-8928-45b536fbd8be',
    workflow: 'cloud-incident-investigator',
    task_status: 'succeeded',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__platform__scale_deployment',
    status: 'approved',
    request_preview:
      'kubectl scale deployment/checkout-api --replicas=8 -n production',
    reason: 'Scale checkout pods during peak incident recovery window.',
    resolved_by: 'Sarah Chen',
    resolved_by_user_id: 'sarah.chen@corp.internal',
    requested_at: '2026-09-05T08:15:02Z',
    resolved_at: '2026-09-05T08:15:08Z',
    archived_at: null,
  },
  {
    id: 'appr-003',
    task_id: '4c71a920-1b20-4e89-8d12-99a01248bc10',
    workflow: 'cloud-incident-investigator',
    task_status: 'succeeded',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__platform__execute_sql_patch',
    status: 'rejected',
    request_preview:
      'ALTER TABLE merchant_ledger_entries DROP CONSTRAINT check_active_contracts;',
    reason: 'Emergency schema patch to bypass lock contention.',
    resolved_by: 'Marcus Lindholm (Data Governance Lead)',
    resolved_by_user_id: 'marcus.lindholm@corp.internal',
    requested_at: '2026-09-04T16:12:00Z',
    resolved_at: '2026-09-04T16:14:22Z',
    archived_at: null,
  },
  {
    id: 'appr-004',
    task_id: '7b8912c0-34ef-4011-89ab-12948c0192ea',
    workflow: 'online-platform-triage',
    task_status: 'waiting_approval',
    approval_kind: 'tool_execution',
    tool_name: 'mcp__platform__flush_redis_cache',
    status: 'pending',
    request_preview:
      'redis-cli -h cache-cluster-01.corp.internal -p 6379 FLUSHDB ASYNC',
    reason:
      'Evict corrupted session cache entries causing 401 redirect loop on mobile portal.',
    resolved_by: null,
    resolved_by_user_id: null,
    requested_at: '2026-09-05T08:20:00Z',
    resolved_at: null,
    archived_at: null,
  },
];

export function getMockPlatformApprovals(
  limit = 100,
  offset = 0,
): PlatformApprovals {
  const counts_by_status: Record<string, number> = {
    pending: 0,
    approved: 0,
    rejected: 0,
  };
  for (const item of MOCK_APPROVALS) {
    counts_by_status[item.status] = (counts_by_status[item.status] || 0) + 1;
  }
  return {
    counts_by_status,
    items: MOCK_APPROVALS.slice(offset, offset + limit),
    total: MOCK_APPROVALS.length,
    limit,
    offset,
  };
}
