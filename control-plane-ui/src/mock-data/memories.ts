import type {
  AgentMemoryDetail,
  HindsightBankDetail,
  PlatformMemories,
} from '@/lib/api';

export const MOCK_PLATFORM_MEMORIES: PlatformMemories = {
  hindsight_available: true,
  hindsight_banks: [
    {
      bank_id: 'incident-rca-production',
      label: 'Production Incident RCAs',
      kind: 'business',
      workflows: ['cloud-incident-investigator', 'daily-operations-digest'],
      listed_in_hindsight: true,
    },
    {
      bank_id: 'workflow-learning-ops',
      label: 'Ops Workflow Learning & Traces',
      kind: 'learning',
      workflows: [
        'cloud-incident-investigator',
        'weekly-reflection-and-learning',
      ],
      listed_in_hindsight: true,
    },
    {
      bank_id: 'customer-support-history',
      label: 'CRM & Customer Incident History',
      kind: 'business',
      workflows: ['enterprise-crm-investigator'],
      listed_in_hindsight: true,
    },
  ],
  agent_memories: [
    {
      agent_name: 'incident-coordinator',
      latest_key:
        'agent-memory/incident-coordinator/2026-09-05T08-15-13Z.tar.gz',
      latest_updated_at: '2026-09-05T08:15:13Z',
      version_count: 24,
    },
    {
      agent_name: 'crm-alerts-coordinator',
      latest_key:
        'agent-memory/crm-alerts-coordinator/2026-09-05T08-10-57Z.tar.gz',
      latest_updated_at: '2026-09-05T08:10:57Z',
      version_count: 18,
    },
    {
      agent_name: 'chat-intake-coordinator',
      latest_key:
        'agent-memory/chat-intake-coordinator/2026-09-05T08-24-14Z.tar.gz',
      latest_updated_at: '2026-09-05T08:24:14Z',
      version_count: 12,
    },
  ],
};

export const MOCK_HINDSIGHT_BANK_DETAILS: Record<string, HindsightBankDetail> =
  {
    'incident-rca-production': {
      bank_id: 'incident-rca-production',
      listed_in_hindsight: true,
      warnings: [],
      stats: {
        total_nodes: 184,
        total_links: 412,
        total_documents: 64,
        total_observations: 128,
        pending_operations: 0,
        failed_operations: 0,
        nodes_by_fact_type: {
          Incident: 64,
          Service: 28,
          RootCause: 42,
          Mitigation: 50,
        },
        links_by_link_type: {
          CAUSED_BY: 88,
          RESOLVED_WITH: 124,
          AFFECTED_SERVICE: 200,
        },
      },
      graph: {
        nodes: [
          {
            id: 'doc-inc-0089201',
            label: 'INC-0089201 (Checkout Pool)',
            node_type: 'document',
          },
          {
            id: 'doc-inc-0081044',
            label: 'INC-0081044 (DB Starvation)',
            node_type: 'document',
          },
          {
            id: 'doc-inc-0076219',
            label: 'INC-0076219 (BankID Handshake)',
            node_type: 'document',
          },
          {
            id: 'kw-hikari',
            label: 'HikariPool-1 Saturation',
            node_type: 'keyword',
          },
          { id: 'kw-timeout', label: '502 Bad Gateway', node_type: 'keyword' },
          {
            id: 'kw-locks',
            label: 'pg_stat_activity Table Lock',
            node_type: 'keyword',
          },
          {
            id: 'kw-checkout',
            label: 'checkout-payment-gateway',
            node_type: 'keyword',
          },
          {
            id: 'kw-pgbouncer',
            label: 'PgBouncer Pool Exhaustion',
            node_type: 'keyword',
          },
          {
            id: 'kw-unindexed',
            label: 'merchant_ledger_entries',
            node_type: 'keyword',
          },
          {
            id: 'mem-restart',
            label: 'Rollout Restart Mitigation',
            node_type: 'memory',
          },
          {
            id: 'mem-index',
            label: 'Composite Index Addition',
            node_type: 'memory',
          },
        ],
        edges: [
          {
            source: 'doc-inc-0089201',
            target: 'kw-hikari',
            edge_type: 'MENTIONS',
            weight: 3,
          },
          {
            source: 'doc-inc-0089201',
            target: 'kw-timeout',
            edge_type: 'MENTIONS',
            weight: 2,
          },
          {
            source: 'doc-inc-0089201',
            target: 'kw-locks',
            edge_type: 'MENTIONS',
            weight: 3,
          },
          {
            source: 'doc-inc-0089201',
            target: 'kw-checkout',
            edge_type: 'MENTIONS',
            weight: 4,
          },
          {
            source: 'doc-inc-0081044',
            target: 'kw-hikari',
            edge_type: 'SIMILAR_TO',
            weight: 2,
          },
          {
            source: 'doc-inc-0081044',
            target: 'kw-unindexed',
            edge_type: 'MENTIONS',
            weight: 3,
          },
          {
            source: 'doc-inc-0081044',
            target: 'mem-index',
            edge_type: 'RESOLVED_BY',
            weight: 3,
          },
          {
            source: 'doc-inc-0076219',
            target: 'kw-timeout',
            edge_type: 'MENTIONS',
            weight: 2,
          },
          {
            source: 'doc-inc-0076219',
            target: 'kw-checkout',
            edge_type: 'MENTIONS',
            weight: 2,
          },
          {
            source: 'kw-hikari',
            target: 'kw-pgbouncer',
            edge_type: 'RELATED',
            weight: 2,
          },
          {
            source: 'kw-locks',
            target: 'kw-unindexed',
            edge_type: 'RELATED',
            weight: 3,
          },
          {
            source: 'doc-inc-0089201',
            target: 'mem-restart',
            edge_type: 'RESOLVED_BY',
            weight: 3,
          },
        ],
        table_rows: [
          {
            id: 'chunk-001',
            document_id: 'doc-inc-0089201',
            text: 'INC-0089201: HikariPool-1 connection pool exhausted on checkout-api pods due to long-running unindexed transaction on merchant_ledger_entries.',
            context: 'checkout-payment-gateway · PostgreSQL lock contention',
          },
          {
            id: 'chunk-002',
            document_id: 'doc-inc-0081044',
            text: 'INC-0081044: Previous DB starvation event resolved via composite index on merchant_id and statement_timeout adjustment.',
            context: 'checkout-payment-gateway · database tuning',
          },
        ],
        total_units: 64,
      },
      entries: [
        {
          id: 'mem-entry-001',
          content: `INC-0089201 (2026-09-05): checkout-payment-gateway HTTP 502/504 Spike.
Root Cause: Background settlement batch job (PID 4192) acquired an exclusive relation lock on merchant_ledger_entries. HikariPool-1 connections saturated (100/100).
Remediation: Terminated backend session 4192, rolled out restart of checkout-api pods. Configured statement_timeout to 30s.`,
          metadata: {
            incident_id: 'INC-0089201',
            severity: 'P1',
            service: 'checkout-payment-gateway',
            confidence: 0.94,
          },
          created_at: '2026-09-05T08:15:13Z',
        },
        {
          id: 'mem-entry-002',
          content: `INC-0081044 (2026-07-14): Checkout Gateway database connection pool starvation under flash sale traffic.
Root Cause: High-concurrency read queries missing composite index (merchant_id, created_at).
Remediation: Added PostgreSQL composite index CONCURRENTLY, increased PgBouncer client pool from 100 to 250.`,
          metadata: {
            incident_id: 'INC-0081044',
            severity: 'P1',
            service: 'checkout-payment-gateway',
            confidence: 0.91,
          },
          created_at: '2026-07-14T11:20:00Z',
        },
        {
          id: 'mem-entry-003',
          content: `INC-0076219 (2026-05-22): BankID and 3D-Secure payment authorization timeout cascade.
Root Cause: Upstream BankID TLS handshake timeout causing connection queueing on ingress pods.
Remediation: Decreased connect timeout to 2.5s and configured circuit breaker fallback.`,
          metadata: {
            incident_id: 'INC-0076219',
            severity: 'P2',
            service: 'auth-service-v2',
            confidence: 0.88,
          },
          created_at: '2026-05-22T14:45:00Z',
        },
      ],
    },
    'workflow-learning-ops': {
      bank_id: 'workflow-learning-ops',
      listed_in_hindsight: true,
      warnings: [],
      stats: {
        total_nodes: 92,
        total_links: 210,
        total_documents: 48,
        total_observations: 76,
        pending_operations: 0,
        failed_operations: 0,
        nodes_by_fact_type: {
          SessionTrace: 48,
          ToolPattern: 22,
          Bottleneck: 22,
        },
        links_by_link_type: {
          EXHIBITED: 120,
          PROPOSED_IMPROVEMENT: 90,
        },
      },
      graph: {
        nodes: [
          {
            id: 'sess-trace-01',
            label: 'Trace: CRM Triage Session',
            node_type: 'document',
          },
          {
            id: 'sess-trace-02',
            label: 'Trace: Splunk Query Loop',
            node_type: 'document',
          },
          {
            id: 'kw-depr-obj',
            label: 'LegacySubscriptionAudit__c',
            node_type: 'keyword',
          },
          {
            id: 'kw-lrg-skill',
            label: 'large-result-handling',
            node_type: 'keyword',
          },
          {
            id: 'kw-turns-waste',
            label: '56 Redundant Turns',
            node_type: 'keyword',
          },
          {
            id: 'pr-42',
            label: 'PR #42 (Query Optimization)',
            node_type: 'memory',
          },
        ],
        edges: [
          {
            source: 'sess-trace-01',
            target: 'kw-depr-obj',
            edge_type: 'OBSERVED',
            weight: 4,
          },
          {
            source: 'kw-depr-obj',
            target: 'kw-turns-waste',
            edge_type: 'CAUSED',
            weight: 3,
          },
          {
            source: 'kw-depr-obj',
            target: 'pr-42',
            edge_type: 'REMEDIED_BY',
            weight: 4,
          },
          {
            source: 'sess-trace-02',
            target: 'kw-lrg-skill',
            edge_type: 'OBSERVED',
            weight: 2,
          },
        ],
        table_rows: [
          {
            id: 'chunk-lrn-01',
            document_id: 'sess-trace-01',
            text: 'Repeated query loop on deprecated sObject LegacySubscriptionAudit__c discovered across 14 CRM investigations.',
            context: 'workflow-learning-ops · query efficiency',
          },
        ],
        total_units: 48,
      },
      entries: [
        {
          id: 'lrn-entry-001',
          content: `Observation: 14 out of 19 CRM triage runs attempted SOQL on deprecated LegacySubscriptionAudit__c.
Recommendation: Update skills/crm-query-strategy to inject filter rule prior to subagent invocation.
Action: Opened Pull Request #42 on repository cloud-ops/agentic-workflows.`,
          metadata: {
            confidence: 0.93,
            source: 'weekly-reflection-and-learning',
          },
          created_at: '2026-09-01T09:01:05Z',
        },
      ],
    },
    'customer-support-history': {
      bank_id: 'customer-support-history',
      listed_in_hindsight: true,
      warnings: [],
      stats: {
        total_nodes: 120,
        total_links: 260,
        total_documents: 42,
        total_observations: 84,
        pending_operations: 0,
        failed_operations: 0,
        nodes_by_fact_type: {
          CustomerCase: 42,
          BillingRule: 30,
          Resolution: 48,
        },
        links_by_link_type: {
          RELATION: 260,
        },
      },
      graph: null,
      entries: [
        {
          id: 'cust-entry-001',
          content: `Enterprise Account 0015g00000XyZ12AAQ (Global Logistics Corp): Custom digital invoicing terms with Net30 billing. Requires custom billing rule override.`,
          metadata: {
            account_id: '0015g00000XyZ12AAQ',
          },
          created_at: '2026-08-15T10:00:00Z',
        },
      ],
    },
  };

export const MOCK_AGENT_MEMORY_DETAILS: Record<string, AgentMemoryDetail> = {
  'incident-coordinator': {
    agent_name: 'incident-coordinator',
    archive_key:
      'agent-memory/incident-coordinator/2026-09-05T08-15-13Z.tar.gz',
    files: [
      {
        path: 'MEMORY.md',
        size_bytes: 2840,
        preview: `# Incident Coordinator Project Memory

## Verified Architecture Patterns
- \`checkout-payment-gateway\` connects to PostgreSQL primary \`pg-primary.corp.internal\` through PgBouncer pooler (port 6432).
- Maximum client connection ceiling: 250 connections.
- When pool saturation occurs, check \`pg_stat_activity\` for queries with state != 'idle' and age > 60s.

## Known Triage Playbooks
1. **502/504 Payment Outages**: Pull Splunk logs first, extract HikariPool metrics, then check pg_stat_activity locks.
2. **K8s CrashLoopBackOff**: Inspect pod exit codes; exit 137 indicates OOMKilled requiring memory limit increase.`,
      },
      {
        path: 'playbooks/p1_triage_checklist.md',
        size_bytes: 1420,
        preview: `# P1 Critical Triage Checklist

1. Verify customer impact & error rate threshold (> 5% triggers P1).
2. Query long-term memory for matching error patterns.
3. Establish 2 independent specialist branches (Logs + Database/Infra).
4. Do NOT attempt direct production writes without approval gate.
5. Record verified RCA in final turn before completion.`,
      },
      {
        path: 'notes/connection_pool_tuning.md',
        size_bytes: 980,
        preview: `# HikariCP & PgBouncer Tuning Reference
- \`checkout-api\`: maximumPoolSize=100, connectionTimeout=10000ms.
- \`auth-service-v2\`: maximumPoolSize=50, connectionTimeout=5000ms.`,
      },
    ],
  },
  'crm-alerts-coordinator': {
    agent_name: 'crm-alerts-coordinator',
    archive_key:
      'agent-memory/crm-alerts-coordinator/2026-09-05T08-10-57Z.tar.gz',
    files: [
      {
        path: 'MEMORY.md',
        size_bytes: 1980,
        preview: `# CRM Alerts Coordinator Project Memory

- Use \`SubscriptionChangeRequest__c\` for all contract updates (do not use legacy table).
- Validation Rule \`VR_Subscription_Billing_Match\` is active on enterprise contract renewals.`,
      },
    ],
  },
};
