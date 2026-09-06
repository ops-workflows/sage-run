import type { Task, TaskListResult } from '@/lib/api';

export const MOCK_TASKS: Task[] = [
  // ── Queued tasks (displayed at the top of the board) ──
  {
    id: 'e4a1b023-5c89-4b11-9a28-68dd2f019a82',
    workflow: 'cloud-incident-investigator',
    prompt: `ServiceNow Incident INC-0089240:
Cluster Alert: Elasticsearch Data Node 04 High Memory Utilization (94.2% heap occupancy).
Investigate garbage collection pause times, active search scroll contexts, and identify unindexed wildcard queries.
Waiting for available worker slot in task queue.`,
    status: 'queued',
    channel: 'servicenow',
    metadata: {
      source: 'servicenow-incident-intake',
      incident_number: 'INC-0089240',
      priority: 'P2',
      service: 'logging-infra-elasticsearch',
      queued_at: '2026-09-06T08:24:00Z',
    },
    message_channel: '#ops-incident-room',
    message_thread: null,
    tokens_used: 0,
    duration_sec: null,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-06T08:24:00Z',
    updated: '2026-09-06T08:24:00Z',
  },
  {
    id: '3f89c10a-7e12-45d0-b914-18c72a819b50',
    workflow: 'weekly-reflection-and-learning',
    prompt: `Scheduled Maintenance Run:
Prune stale learning observation vectors older than 90 days from Hindsight memory bank 'workflow-learning-ops'.
Rebuild Hindsight index and optimize semantic graph cluster weights.
Waiting for available worker slot in task queue.`,
    status: 'queued',
    channel: 'schedule',
    metadata: {
      triggered_by: 'scheduler',
      schedule_name: 'hindsight-memory-compaction',
      cron: '0 3 * * 0',
      queued_at: '2026-09-06T08:24:10Z',
    },
    message_channel: null,
    message_thread: null,
    tokens_used: 0,
    duration_sec: null,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-06T08:24:10Z',
    updated: '2026-09-06T08:24:10Z',
  },

  // ── Succeeded processed tasks ──
  {
    id: '6a4132ca-1306-463e-8928-45b536fbd8be',
    workflow: 'cloud-incident-investigator',
    prompt: `Investigate ServiceNow incident INC-0089201.

Incident ID: 9f81a702c3104e1b8b2091ea2803b891
Incident Number: INC-0089201
Priority: P1 - Critical
Severity: 1 - High
Service: checkout-payment-gateway
CMDB CI: k8s-pod:checkout-api-prod-8d99f
Customer: Nordic Retail Hub (Tier 1 Enterprise)
Opened At: 2026-09-05T08:14:22Z
Portal URL: https://servicedesk.corp.internal/nav_to.do?uri=incident.do?sys_id=9f81a702c3104e1b8b2091ea2803b891

Description:
Sudden spike in HTTP 502 Bad Gateway and 504 Gateway Timeouts across European payment gateways.
Payment auth error rate reached 48.2% on /api/v2/payments/checkout. Over 1,420 transactions impacted in the last 10 minutes.
Customer operations reports BankID and 3D-Secure timeouts. Initial alarms indicate database reader thread starvation.

Please triage across telemetry logs, inspect connection pool metrics, check for concurrent database locks, recall similar past incidents, and generate an evidence-backed Incident RCA with actionable remediation steps.`,
    status: 'succeeded',
    channel: 'servicenow',
    metadata: {
      source: 'servicenow-incident-intake',
      incident_number: 'INC-0089201',
      priority: 'P1',
      service: 'checkout-payment-gateway',
      cmdb_ci: 'checkout-api-prod-cluster',
      opened_at: '2026-09-05T08:14:22Z',
      customer_tier: 'Enterprise Platinum',
    },
    message_channel: '#ops-incident-room',
    message_thread: 'th-inc-89201',
    tokens_used: 18450,
    duration_sec: 42.4,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-05T08:14:30Z',
    updated: '2026-09-05T08:15:13Z',
  },
  {
    id: '5f597719-0a6d-4e68-abe0-eb0c8fa669b0',
    workflow: 'online-platform-triage',
    prompt: `[Mattermost Channel #ops-incident-room | Thread th-889104 | Ingested at 2026-09-05T08:23:15Z]

[08:21:04] @sarah.chen: Seeing elevated 504 Gateway Timeouts on auth-service-v2 in eu-west-1. Error budget burn rate is 14x over threshold.
[08:22:15] @alex.morales: DB connection pool on the replica looks saturated (active: 98/100 connections). Did someone deploy a migration recently?
[08:22:50] @sarah.chen: Release 4.12.0 was rolled out 20 mins ago by deployment pipeline #8812. The replica seems to have hung threads.
[08:23:10] @alex.morales: @agent please investigate auth-service 504 spike, verify whether replica pool is stuck, and if safe, restart the hung pool pods.`,
    status: 'succeeded',
    channel: 'mattermost',
    metadata: {
      source: 'mattermost-socket-ingress',
      channel_id: 'channel-ops-room-01',
      thread_id: 'th-889104',
      invoker: 'alex.morales',
      participants: ['sarah.chen', 'alex.morales'],
      approval_id: 'appr-001',
    },
    message_channel: '#ops-incident-room',
    message_thread: 'th-889104',
    tokens_used: 22100,
    duration_sec: 58.6,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-05T08:23:15Z',
    updated: '2026-09-05T08:24:14Z',
  },
  {
    id: 'abeceee9-aa1b-455b-b778-68aa10c88450',
    workflow: 'enterprise-crm-investigator',
    prompt: `Investigate automated alert email received via GCP Cloud Pub/Sub.

Bucket: enterprise-ops-prod-inbound-alerts
Object: dev-crm-alerts/2026-09-05/msg-881921.eml
Message-ID: <alert-crm-20260905081014@gcp.enterprise.internal>
Date: 2026-09-05T08:10:14Z
Sender: alerts-engine@gcp.enterprise.internal
Subject: Developer script exception from CRM-Billing-Queue: System.DmlException

Email Body:
Apex script exception thrown in transaction 0038910-AA:
System.DmlException: Insert failed. First exception on row 0; first error: FIELD_CUSTOM_VALIDATION_EXCEPTION, Invoicing terms mismatch for dual-contract account: [BillingTerms__c]
Apex Class: BillingRollupDispatcher.cls:184
Trigger: SubscriptionMasterTrigger:42
Affected Account Records: [0015g00000XyZ12AAQ, 0015g00000AbC34AAQ]

Please inspect the codebase for BillingRollupDispatcher.cls around line 184, identify the validation rule constraints, and file an engineering bug ticket in Jira.`,
    status: 'succeeded',
    channel: 'gcp-pubsub',
    metadata: {
      source: 'gcp-pubsub-intake',
      gcs_bucket: 'enterprise-ops-prod-inbound-alerts',
      gcs_object: 'dev-crm-alerts/2026-09-05/msg-881921.eml',
      error_type: 'FIELD_CUSTOM_VALIDATION_EXCEPTION',
      apex_class: 'BillingRollupDispatcher.cls',
      jira_ticket: 'CORE-4921',
    },
    message_channel: '#crm-billing-alerts',
    message_thread: 'th-crm-881921',
    tokens_used: 14820,
    duration_sec: 36.2,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-05T08:10:20Z',
    updated: '2026-09-05T08:10:57Z',
  },
  {
    id: '57f62e31-ee6d-4cb5-b128-a748b8aede70',
    workflow: 'weekly-reflection-and-learning',
    prompt: `Run scheduled weekly workflow reflection across all operational workflows over the last 7 days.
Analyze Hindsight workflow-learning memory banks for recurring inefficiencies, tool loop patterns, and parameter misconfigurations.
If a durable improvement is warranted, autonomously author and open a GitHub Pull Request with the proposed skill or prompt optimization.`,
    status: 'succeeded',
    channel: 'schedule',
    metadata: {
      triggered_by: 'scheduler',
      schedule_name: 'weekly-reflection-run',
      cron: '0 9 * * 1',
      analyzed_sessions: 48,
      pr_created:
        'https://github.corp.internal/cloud-ops/agentic-workflows/pull/42',
    },
    message_channel: '#ops-architecture',
    message_thread: null,
    tokens_used: 26400,
    duration_sec: 64.1,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-01T09:00:00Z',
    updated: '2026-09-01T09:01:05Z',
  },
  {
    id: 'ac5541b7-8115-4fe0-8963-fb2f515fac51',
    workflow: 'daily-operations-digest',
    prompt: `Generate the daily incident summary for the last 24 hours.
Query the Hindsight incident-rca bank, cluster incidents by affected subsystem, calculate mean-time-to-resolve (MTTR), and post an executive summary to #ops-digest.`,
    status: 'succeeded',
    channel: 'schedule',
    metadata: {
      triggered_by: 'scheduler',
      schedule_name: 'daily-morning-digest',
      cron: '0 8 * * 1-5',
      incidents_processed: 6,
      mttr_minutes: 14.2,
    },
    message_channel: '#ops-digest',
    message_thread: null,
    tokens_used: 8240,
    duration_sec: 19.3,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-05T08:00:00Z',
    updated: '2026-09-05T08:00:20Z',
  },
  {
    id: '9d28e714-38ab-40fc-8092-23c4a17951bc',
    workflow: 'cloud-incident-investigator',
    prompt: `API Webhook trigger from Certificate Manager Daemon:
Verify ingress TLS certificate expiry and SAN validity for payment gateway endpoints:
- https://payments.checkout.corp.internal
- https://api.gateway.corp.internal/v2/auth

Confirm expiration window is > 60 days and automated renewal secrets are present in Vault.`,
    status: 'succeeded',
    channel: 'api',
    metadata: {
      source: 'api',
      initiator: 'cert-manager-daemon',
      endpoint_checked: 'payments.checkout.corp.internal',
      status_result: 'valid_68_days_remaining',
    },
    message_channel: null,
    message_thread: null,
    tokens_used: 6120,
    duration_sec: 14.8,
    error: null,
    wait_reason: null,
    wait_deadline: null,
    archived_at: null,
    created: '2026-09-04T22:00:00Z',
    updated: '2026-09-04T22:00:15Z',
  },
];

export function getMockTaskList(params: {
  status?: string;
  limit?: number;
  offset?: number;
}): TaskListResult {
  let filtered = MOCK_TASKS;
  if (params.status && params.status !== 'all') {
    filtered = filtered.filter((t) => t.status === params.status);
  }
  const limit = params.limit ?? 50;
  const offset = params.offset ?? 0;
  return {
    items: filtered.slice(offset, offset + limit),
    total: filtered.length,
    limit,
    offset,
  };
}
