import type { SessionDetail } from '@/lib/api';
import { MOCK_TASKS } from './tasks';

export const MOCK_SESSIONS: Record<string, SessionDetail> = {
  '6a4132ca-1306-463e-8928-45b536fbd8be': {
    id: 'sess-6a4132ca-1306-463e-8928-45b536fbd8be',
    task_id: '6a4132ca-1306-463e-8928-45b536fbd8be',
    agent_id: 'agent-001',
    status: 'succeeded',
    started: '2026-09-05T08:14:31Z',
    ended: '2026-09-05T08:15:13Z',
    duration_sec: 42.4,
    tokens_input: 13200,
    tokens_output: 5250,
    turns: 18,
    task: MOCK_TASKS[2],
    tools_used: [
      { name: 'mcp__splunk__search_logs', count: 2, total_duration: 3.4 },
      {
        name: 'mcp__platform__query_pg_stat_activity',
        count: 1,
        total_duration: 1.2,
      },
      { name: 'Write', count: 1, total_duration: 0.1 },
      { name: 'Grep', count: 2, total_duration: 0.2 },
      { name: 'Read', count: 1, total_duration: 0.1 },
      { name: 'TodoWrite', count: 1, total_duration: 0.1 },
    ],
    subagents_used: [
      { name: 'telemetry-investigator', turns: 9, tokens: 9400 },
      { name: 'database-investigator', turns: 5, tokens: 4800 },
    ],
    error: null,
    trace: {
      root: {
        id: 'node-root',
        kind: 'session',
        timestamp: '2026-09-05T08:14:31Z',
        label: 'incident-coordinator',
        isError: false,
        children: [
          {
            id: 'node-req',
            kind: 'lifecycle',
            timestamp: '2026-09-05T08:14:31Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[2].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-hook-recall',
            kind: 'hook',
            timestamp: '2026-09-05T08:14:32Z',
            label: 'auto_recall · success',
            badge: 'HOOK',
            detail: 'SessionStart',
            body: `[Long-term memory — similar past incidents recalled from Hindsight: incident-rca-production]

1. INC-0081044 (2026-07-14) — Checkout Gateway DB connection starvation:
   - Root Cause: Unindexed JOIN query on merchant_ledger_entries held table-level exclusive lock during transaction batching.
   - Resolution: Killed blocking PID, increased PgBouncer max client connections to 250, added composite index (merchant_id, created_at).

2. INC-0076219 (2026-05-22) — BankID Authorization Spike:
   - Root Cause: Upstream BankID TLS handshake timeout causing connection pool queueing on checkout-api pods.
   - Resolution: Decreased HTTP connect timeout to 2.5s and enabled circuit breaker fallback.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-think-1',
            kind: 'thinking',
            timestamp: '2026-09-05T08:14:33Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Evaluating incoming ServiceNow P1 incident INC-0089201.
Symptoms: 502/504 errors on /api/v2/payments/checkout, 48.2% failure rate, BankID/3DS timeout.
Historical match: Recall hook returned INC-0081044 which matches database connection pool starvation under high checkout load.
Investigation strategy:
1. Create a structured TODO plan.
2. Delegate log inspection to 'telemetry-investigator' to pull Splunk error clusters and inspect thread dump.
3. If logs indicate DB pool starvation, delegate immediately to 'database-investigator' to query pg_stat_activity for blocking queries.
4. Synthesize findings and invoke retain hook before completion.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-todo-1',
            kind: 'tool_call',
            timestamp: '2026-09-05T08:14:34Z',
            label: 'TodoWrite',
            badge: 'TOOL',
            body: JSON.stringify(
              {
                todos: [
                  {
                    id: '1',
                    task: 'Query Splunk logs for checkout-api 502/504 error clusters and thread dumps',
                    status: 'completed',
                  },
                  {
                    id: '2',
                    task: 'Inspect large error payload using Grep and Read around connection pool exceptions',
                    status: 'completed',
                  },
                  {
                    id: '3',
                    task: 'Check PostgreSQL primary for active table locks and long-running queries',
                    status: 'completed',
                  },
                  {
                    id: '4',
                    task: 'Synthesize Root Cause Analysis with confidence score and remediation plan',
                    status: 'completed',
                  },
                ],
              },
              null,
              2,
            ),
            isError: false,
            children: [
              {
                id: 'node-todo-res',
                kind: 'tool_result',
                timestamp: '2026-09-05T08:14:34Z',
                label: 'Todo status updated',
                badge: 'RESULT',
                body: 'Todo list updated: 4 items planned.',
                isError: false,
                children: [],
              },
            ],
          },
          {
            id: 'node-sub-telemetry',
            kind: 'subagent',
            timestamp: '2026-09-05T08:14:35Z',
            label: 'telemetry-investigator',
            detail:
              'Investigate Splunk APM error logs and thread pool exhaustion',
            badge: 'SUBAGENT',
            isError: false,
            children: [
              {
                id: 'node-tel-skill-splunk',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:36Z',
                label: 'splunk-queries',
                badge: 'SKILL',
                isError: false,
                children: [
                  {
                    id: 'node-tel-skill-splunk-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:36Z',
                    label: 'Skill Loaded',
                    badge: 'RESULT',
                    body: 'Loaded splunk-queries skill: Best practices for narrow microservice exception search.',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-mcp-splunk',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:37Z',
                label: 'splunk · search_logs',
                badge: 'MCP',
                body: JSON.stringify(
                  {
                    query:
                      'index=payment_prod host=checkout-api-* (status>=500 OR "Exception") earliest=-15m',
                    max_results: 150,
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-tel-mcp-splunk-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:40Z',
                    label: 'Splunk Results',
                    badge: 'RESULT',
                    body: 'Search complete: 150 events matched (payload size: 384,192 bytes). Response truncated for display.',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-think',
                kind: 'thinking',
                timestamp: '2026-09-05T08:14:40Z',
                label: 'Reasoning',
                badge: 'THINKING',
                body: `Splunk query returned 150 events totaling 384KB of logs across checkout-api pods.
Initial lines indicate HikariPool-1 connection acquisition timeout exceptions.
To prevent context overflow, I will invoke large-result-handling: Write the full payload to /tmp/checkout-errors.json, Grep for exact Connection pool / TimeoutException anchors, and Read a narrow line window around the stack trace.`,
                isError: false,
                children: [],
              },
              {
                id: 'node-tel-skill-lrg',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:41Z',
                label: 'large-result-handling',
                badge: 'SKILL',
                isError: false,
                children: [
                  {
                    id: 'node-tel-skill-lrg-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:41Z',
                    label: 'Skill Loaded',
                    badge: 'RESULT',
                    body: 'Loaded large-result-handling skill: Saving payload to tempfile, narrowing via Grep and sed/Read.',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-tool-write',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:42Z',
                label: 'Write',
                badge: 'TOOL',
                body: JSON.stringify(
                  {
                    filePath: '/tmp/checkout-errors.json',
                    content: '... [384KB Splunk log payload saved to disk] ...',
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-tel-tool-write-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:42Z',
                    label: 'File Written',
                    badge: 'RESULT',
                    body: 'File successfully written to /tmp/checkout-errors.json (384,192 bytes)',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-tool-grep',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:43Z',
                label: 'Grep',
                badge: 'TOOL',
                body: JSON.stringify(
                  {
                    filePath: '/tmp/checkout-errors.json',
                    pattern: 'Connection pool exhausted|TimeoutException',
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-tel-tool-grep-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:43Z',
                    label: 'Matches Found',
                    badge: 'RESULT',
                    body: 'Matches found:\nLine 138: org.postgresql.util.PSQLException: Connection pool exhausted (active=100/100, max=100, waitQueue=248)\nLine 142: com.enterprise.checkout.repository.PaymentRepository: Timeout waiting for idle connection from pool after 10000ms',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-tool-read',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:44Z',
                label: 'Read',
                badge: 'TOOL',
                body: JSON.stringify(
                  {
                    filePath: '/tmp/checkout-errors.json',
                    startLine: 135,
                    endLine: 150,
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-tel-tool-read-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:44Z',
                    label: 'Extracted Lines',
                    badge: 'RESULT',
                    body: `135: 2026-09-05 08:13:58.201 ERROR [checkout-api-8d99f] [http-nio-8080-exec-42] c.e.c.s.PaymentProcessingService: Failed to acquire DB connection for payment transaction tx-998124
136:   Caused by: com.zaxxer.hikari.pool.HikariPool$PoolKeyException: HikariPool-1 - Connection is not available, request timed out after 10002ms.
137:   Pool stats: (total=100, active=100, idle=0, waiting=248)
138:   org.postgresql.util.PSQLException: Connection pool exhausted (active=100/100, max=100, waitQueue=248)
139:     at com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:217)
140:     at com.enterprise.checkout.repository.PaymentRepository.recordTransactionAttempt(PaymentRepository.java:184)`,
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-tel-result',
                kind: 'result',
                timestamp: '2026-09-05T08:14:46Z',
                label: 'Branch findings',
                badge: 'RESULT',
                body: `### Telemetry Findings
- **Error Anchor**: \`HikariPool-1\` is fully saturated (\`active=100/100, idle=0, waiting=248\`).
- **Impact**: All incoming HTTP threads attempting to write or read payment state are timing out after 10,000ms, triggering upstream HTTP 504 timeouts to BankID and payment gateways.
- **Root Trigger**: Underlying database reader connections are held open by long-running transactions.`,
                isError: false,
                meta: { result_role: 'subagent_return' },
                children: [],
              },
            ],
          },
          {
            id: 'node-sub-db',
            kind: 'subagent',
            timestamp: '2026-09-05T08:14:47Z',
            label: 'database-investigator',
            detail: 'Inspect PostgreSQL primary locks and pg_stat_activity',
            badge: 'SUBAGENT',
            isError: false,
            children: [
              {
                id: 'node-db-think',
                kind: 'thinking',
                timestamp: '2026-09-05T08:14:47Z',
                label: 'Reasoning',
                badge: 'THINKING',
                body: `Telemetry findings isolated a saturated connection pool on the PostgreSQL primary (100/100 active connections).
I will query pg_stat_activity to inspect non-idle sessions, filtering for long-running transactions and table-level locks on merchant_ledger_entries to identify the root blocker.`,
                isError: false,
                children: [],
              },
              {
                id: 'node-db-mcp-query',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:14:48Z',
                label: 'platform · query_pg_stat_activity',
                badge: 'MCP',
                body: JSON.stringify(
                  {
                    query:
                      "SELECT pid, age(clock_timestamp(), query_start), state, wait_event_type, wait_event, query FROM pg_stat_activity WHERE state != 'idle' AND query ILIKE '%merchant_ledger%' ORDER BY age DESC LIMIT 5;",
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-db-mcp-query-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:14:50Z',
                    label: 'Query Result',
                    badge: 'RESULT',
                    body: JSON.stringify(
                      [
                        {
                          pid: 4192,
                          age: '00:18:42.189',
                          state: 'active',
                          wait_event_type: 'Lock',
                          wait_event: 'relation',
                          query:
                            'UPDATE merchant_ledger_entries SET settlement_status = $1 WHERE account_id = $2 AND settlement_period = $3',
                        },
                        {
                          pid: 4210,
                          age: '00:15:11.021',
                          state: 'active',
                          wait_event_type: 'Lock',
                          wait_event: 'tuple',
                          query:
                            'SELECT * FROM merchant_ledger_entries WHERE account_id = $1 FOR UPDATE',
                        },
                      ],
                      null,
                      2,
                    ),
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-db-result',
                kind: 'result',
                timestamp: '2026-09-05T08:14:52Z',
                label: 'Branch findings',
                badge: 'RESULT',
                body: `### Database Lock Contention Findings
- **Offending Session**: PID \`4192\` has been holding an exclusive \`relation\` lock on \`merchant_ledger_entries\` for **18 minutes and 42 seconds**.
- **Contention Effect**: Over 98 checkout worker transactions are stacked behind PID 4192 waiting on tuple/relation locks, preventing connection release back to HikariPool.
- **Origin**: Automated settlement batch job triggered concurrently with peak checkout traffic.`,
                isError: false,
                meta: { result_role: 'subagent_return' },
                children: [],
              },
            ],
          },
          {
            id: 'node-hook-retain',
            kind: 'hook',
            timestamp: '2026-09-05T08:14:54Z',
            label: 'retain_incident · success',
            badge: 'HOOK',
            detail: 'SubagentStop',
            body: `[Long-term memory — incident retained to Hindsight]
- Business RCA Bank: incident-rca-production
  - Key: inc-0089201-checkout-db-starvation
  - Entities: [checkout-payment-gateway, merchant_ledger_entries, HikariPool-1, PID-4192]
- Learning Bank: workflow-learning-ops
  - Logged trace: 18 turns, 2 subagents, 1 tool-narrowing cycle, 0 errors.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-final-rca',
            kind: 'result',
            timestamp: '2026-09-05T08:15:10Z',
            label: 'Final',
            badge: 'RESULT',
            body: `## Root Cause Analysis (RCA) — INC-0089201

**Incident Summary**
- **Service**: \`checkout-payment-gateway\` (Production EU-West-1)
- **Severity**: P1 - Critical
- **Impact Duration**: 08:10:00Z – 08:15:00Z (5 minutes)
- **Customer Impact**: 1,420 checkout transactions failed with HTTP 502/504 errors; BankID authentication timed out.
- **Confidence Score**: **94%** (Verified via Splunk stack trace and PostgreSQL lock inspection)

---

### Root Cause
An un-indexed background batch settlement transaction (\`PID 4192\`) executed an exclusive table lock on \`merchant_ledger_entries\`. Because the query took over 18 minutes to complete without a query timeout, 100 out of 100 database connections in the \`HikariPool-1\` pool were exhausted. Incoming customer checkout transactions were unable to acquire an idle connection within the 10,000ms threshold and were dropped.

---

### Evidence Chain
1. **Splunk APM Logs**: \`PSQLException: Connection pool exhausted (active=100/100, waitQueue=248)\` observed across all 6 checkout-api pods.
2. **PostgreSQL pg_stat_activity**: Session PID \`4192\` holding relation lock on \`merchant_ledger_entries\` for \`00:18:42\`.
3. **Historical Precedent**: Aligns with \`INC-0081044\` recalled from Hindsight memory where similar ledger lock contention starved the checkout pool.

---

### Immediate Remediation Steps
1. **Terminate Blocking Session**:
   \`\`\`sql
   SELECT pg_terminate_backend(4192);
   \`\`\`
2. **Restart Saturated Pods** to reset connection pools:
   \`\`\`bash
   kubectl rollout restart deployment/checkout-api -n production
   \`\`\`

---

### Preventive Actions
- [ ] Configure \`statement_timeout = '30s'\` on background settlement database roles to prevent un-bounded table locks.
- [ ] Increase PgBouncer max client pool size from 100 to 250 connections.
- [ ] Schedule settlement reconciliation batches outside of peak shopping hours (08:00–22:00 CET).`,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 7,
        toolErrors: 0,
        assistantMessages: 6,
        subagentSpawns: 2,
        totalTurns: 18,
        tokensIn: 13200,
        tokensOut: 5250,
      },
      skillsUsed: ['splunk-queries', 'large-result-handling', 'incident-rca'],
      mcpsUsed: ['splunk', 'platform', 'memory', 'message'],
      heartbeats: [
        { timestamp: '2026-09-05T08:14:40Z' },
        { timestamp: '2026-09-05T08:14:55Z' },
        { timestamp: '2026-09-05T08:15:10Z' },
      ],
      eventCount: 28,
    },
  },

  '5f597719-0a6d-4e68-abe0-eb0c8fa669b0': {
    id: 'sess-5f597719-0a6d-4e68-abe0-eb0c8fa669b0',
    task_id: '5f597719-0a6d-4e68-abe0-eb0c8fa669b0',
    agent_id: 'agent-003',
    status: 'succeeded',
    started: '2026-09-05T08:23:16Z',
    ended: '2026-09-05T08:24:14Z',
    duration_sec: 58.6,
    tokens_input: 15800,
    tokens_output: 6300,
    turns: 22,
    task: MOCK_TASKS[3],
    tools_used: [
      {
        name: 'mcp__cloudwatch__filter_log_events',
        count: 2,
        total_duration: 2.1,
      },
      {
        name: 'mcp__platform__execute_remediation_action',
        count: 1,
        total_duration: 8.5,
      },
      { name: 'mcp__message__send_message', count: 2, total_duration: 0.4 },
    ],
    subagents_used: [
      { name: 'api-gateway-investigator', turns: 8, tokens: 7200 },
      { name: 'infra-remediation-agent', turns: 6, tokens: 6100 },
    ],
    error: null,
    trace: {
      root: {
        id: 'node-root-chat',
        kind: 'session',
        timestamp: '2026-09-05T08:23:16Z',
        label: 'chat-intake-coordinator',
        isError: false,
        children: [
          {
            id: 'node-chat-req',
            kind: 'lifecycle',
            timestamp: '2026-09-05T08:23:16Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[3].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-chat-think',
            kind: 'thinking',
            timestamp: '2026-09-05T08:23:17Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Analyzing Mattermost thread from #ops-incident-room.
Engineers @sarah.chen and @alex.morales are discussing a 504 spike on auth-service-v2 following release 4.12.0.
Alex explicitly asked the agent to:
1. Investigate the 504 spike.
2. Verify if the database replica pool is stuck.
3. If safe, restart the hung pool pods.

Action plan:
- Delegate log verification to api-gateway-investigator via CloudWatch.
- If verified, construct remediation payload 'kubectl rollout restart deployment/auth-service-v2'.
- Note: Production remediation requires operator approval. Trigger approval broker.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-sub-gw',
            kind: 'subagent',
            timestamp: '2026-09-05T08:23:18Z',
            label: 'api-gateway-investigator',
            detail: 'Filter CloudWatch logs for auth-service-v2 504 errors',
            badge: 'SUBAGENT',
            isError: false,
            children: [
              {
                id: 'node-gw-think',
                kind: 'thinking',
                timestamp: '2026-09-05T08:23:19Z',
                label: 'Reasoning',
                badge: 'THINKING',
                body: 'Filtering CloudWatch log group /aws/eks/production/auth-service-v2 over the last 15 minutes for 504 HTTP status patterns to verify error rates and extract exact timeout messages.',
                isError: false,
                children: [],
              },
              {
                id: 'node-gw-cw',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:23:20Z',
                label: 'cloudwatch · filter_log_events',
                badge: 'MCP',
                body: JSON.stringify(
                  {
                    logGroupName: '/aws/eks/production/auth-service-v2',
                    filterPattern: '[time, status=504, ...]',
                    limit: 50,
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-gw-cw-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:23:22Z',
                    label: 'CloudWatch Logs',
                    badge: 'RESULT',
                    body: 'Confirmed: 38 instances of "504 Gateway Timeout: DB replica read pool handshake timeout after 5000ms" in the last 10 minutes.',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-gw-res',
                kind: 'result',
                timestamp: '2026-09-05T08:23:24Z',
                label: 'Branch findings',
                badge: 'RESULT',
                body: 'Auth replica read pool has 98/100 active connections in CLOSE_WAIT state following release 4.12.0 pod rollout.',
                isError: false,
                meta: { result_role: 'subagent_return' },
                children: [],
              },
            ],
          },
          {
            id: 'node-chat-approval-req',
            kind: 'hook',
            timestamp: '2026-09-05T08:23:26Z',
            label: 'approval_requested · pending',
            badge: 'HOOK',
            detail: 'mcp__platform__execute_remediation_action',
            body: `[Operator Approval Gate]
Command: kubectl rollout restart deployment/auth-service-v2 -n production
Target Cluster: production-eu-west-1
Risk Level: High (Production Deployment Rollout)
Approver: Alex Morales (@alex.morales)
Reason: Restart hung replica pool pods to clear CLOSE_WAIT sockets.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-chat-approval-res',
            kind: 'hook',
            timestamp: '2026-09-05T08:23:38Z',
            label: 'permission_callback · approved',
            badge: 'HOOK',
            detail: 'mcp__platform__execute_remediation_action',
            body: `Decision: APPROVED by Alex Morales (alex.morales@corp.internal)
Resolution Note: "Verified replica pool starvation caused by pipeline #8812 release. Rolling restart approved."`,
            isError: false,
            children: [],
          },
          {
            id: 'node-sub-remediation',
            kind: 'subagent',
            timestamp: '2026-09-05T08:23:40Z',
            label: 'infra-remediation-agent',
            detail: 'Execute governed kubectl rollout restart',
            badge: 'SUBAGENT',
            isError: false,
            children: [
              {
                id: 'node-rem-think',
                kind: 'thinking',
                timestamp: '2026-09-05T08:23:41Z',
                label: 'Reasoning',
                badge: 'THINKING',
                body: 'Approval verified from SRE Lead Alex Morales. Executing rolling restart of deployment auth-service-v2 in production namespace with 120s timeout and verifying pod availability.',
                isError: false,
                children: [],
              },
              {
                id: 'node-rem-exec',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:23:42Z',
                label: 'platform · execute_remediation_action',
                badge: 'MCP',
                body: JSON.stringify(
                  {
                    action: 'kubectl_rollout_restart',
                    deployment: 'auth-service-v2',
                    namespace: 'production',
                    timeout_sec: 120,
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-rem-exec-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:23:55Z',
                    label: 'Command Output',
                    badge: 'RESULT',
                    body: `deployment.apps/auth-service-v2 restarted
Waiting for deployment "auth-service-v2" rollout to finish: 4 of 4 updated replicas are available...
deployment "auth-service-v2" successfully rolled out.`,
                    isError: false,
                    children: [],
                  },
                ],
              },
            ],
          },
          {
            id: 'node-chat-final',
            kind: 'result',
            timestamp: '2026-09-05T08:24:12Z',
            label: 'Final',
            badge: 'RESULT',
            body: `### Incident Triage & Remediation Complete

@alex.morales @sarah.chen 

1. **Investigation**: Confirmed 504 Gateway Timeouts were caused by 98 stale connection sockets stuck in \`CLOSE_WAIT\` on \`auth-service-v2\` DB replica pool following pipeline #8812 deployment.
2. **Approval**: Gated remediation was approved by Alex Morales.
3. **Action Executed**: \`kubectl rollout restart deployment/auth-service-v2 -n production\` completed successfully.
4. **Health Check**:
   - All 4 pods healthy and in \`Running\` state.
   - P99 API latency returned to **42ms** (down from 5,200ms).
   - HTTP 504 error count in the last 2 minutes: **0**.
5. **Thread notification posted** to Mattermost \`#ops-incident-room\`.`,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 5,
        toolErrors: 0,
        assistantMessages: 5,
        subagentSpawns: 2,
        totalTurns: 22,
        tokensIn: 15800,
        tokensOut: 6300,
      },
      skillsUsed: ['api-failure-analysis', 'cloudwatch-metrics'],
      mcpsUsed: ['cloudwatch', 'platform', 'message'],
      heartbeats: [
        { timestamp: '2026-09-05T08:23:30Z' },
        { timestamp: '2026-09-05T08:23:50Z' },
        { timestamp: '2026-09-05T08:24:10Z' },
      ],
      eventCount: 22,
    },
  },

  'abeceee9-aa1b-455b-b778-68aa10c88450': {
    id: 'sess-abeceee9-aa1b-455b-b778-68aa10c88450',
    task_id: 'abeceee9-aa1b-455b-b778-68aa10c88450',
    agent_id: 'agent-002',
    status: 'succeeded',
    started: '2026-09-05T08:10:21Z',
    ended: '2026-09-05T08:10:57Z',
    duration_sec: 36.2,
    tokens_input: 10400,
    tokens_output: 4420,
    turns: 14,
    task: MOCK_TASKS[4],
    tools_used: [
      { name: 'Glob', count: 1, total_duration: 0.1 },
      { name: 'Grep', count: 2, total_duration: 0.2 },
      { name: 'Read', count: 1, total_duration: 0.1 },
      { name: 'mcp__jira__create_issue', count: 1, total_duration: 0.8 },
    ],
    subagents_used: [
      { name: 'backend-code-investigator', turns: 7, tokens: 6800 },
    ],
    error: null,
    trace: {
      root: {
        id: 'node-root-crm',
        kind: 'session',
        timestamp: '2026-09-05T08:10:21Z',
        label: 'crm-alerts-coordinator',
        isError: false,
        children: [
          {
            id: 'node-crm-req',
            kind: 'lifecycle',
            timestamp: '2026-09-05T08:10:21Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[4].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-crm-think-coord',
            kind: 'thinking',
            timestamp: '2026-09-05T08:10:22Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Analyzing GCP Pub/Sub notification regarding a FIELD_CUSTOM_VALIDATION_EXCEPTION in transaction 0038910-AA.
The error originates from BillingRollupDispatcher.cls:184 inside SubscriptionMasterTrigger:42 on accounts [0015g00000XyZ12AAQ, 0015g00000AbC34AAQ].
Delegating to backend-code-investigator to locate the source file using Glob, inspect lines 175-195 using Grep/Read, and correlate against validation rule VR_Subscription_Billing_Match.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-sub-code',
            kind: 'subagent',
            timestamp: '2026-09-05T08:10:23Z',
            label: 'backend-code-investigator',
            detail:
              'Inspect BillingRollupDispatcher.cls and validation rule logic',
            badge: 'SUBAGENT',
            isError: false,
            children: [
              {
                id: 'node-code-think',
                kind: 'thinking',
                timestamp: '2026-09-05T08:10:23Z',
                label: 'Reasoning',
                badge: 'THINKING',
                body: 'Using Glob to locate BillingRollupDispatcher.cls in the workspace, then extracting the method surrounding line 184 to identify the exact validation rule collision.',
                isError: false,
                children: [],
              },
              {
                id: 'node-code-glob',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:10:24Z',
                label: 'Glob',
                badge: 'TOOL',
                body: JSON.stringify(
                  { pattern: '**/BillingRollupDispatcher.cls' },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-code-glob-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:10:24Z',
                    label: 'Found 1 file',
                    badge: 'RESULT',
                    body: 'Matched: src/classes/BillingRollupDispatcher.cls',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-code-grep',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:10:25Z',
                label: 'Grep',
                badge: 'TOOL',
                body: JSON.stringify(
                  {
                    filePath: 'src/classes/BillingRollupDispatcher.cls',
                    pattern: 'BillingTerms__c|applyInvoicingTerms',
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-code-grep-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:10:25Z',
                    label: 'Matches',
                    badge: 'RESULT',
                    body: 'Line 184: targetSubscription.BillingTerms__c = masterContract.DefaultInvoicingOption__c;',
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-code-read',
                kind: 'tool_call',
                timestamp: '2026-09-05T08:10:26Z',
                label: 'Read',
                badge: 'TOOL',
                body: JSON.stringify(
                  {
                    filePath: 'src/classes/BillingRollupDispatcher.cls',
                    startLine: 175,
                    endLine: 195,
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [
                  {
                    id: 'node-code-read-res',
                    kind: 'tool_result',
                    timestamp: '2026-09-05T08:10:26Z',
                    label: 'Code Context',
                    badge: 'RESULT',
                    body: `180: // Sync invoicing options to child subscriptions
181: for (Subscription__c sub : childSubscriptions) {
182:     if (masterContract.HasDualContractTerms__c) {
183:         // BUG: Fails validation rule VR_Subscription_Billing_Match when account has enterprise override
184:         sub.BillingTerms__c = masterContract.DefaultInvoicingOption__c;
185:     }
186: }
187: insert childSubscriptions;`,
                    isError: false,
                    children: [],
                  },
                ],
              },
              {
                id: 'node-code-res',
                kind: 'result',
                timestamp: '2026-09-05T08:10:30Z',
                label: 'Branch findings',
                badge: 'RESULT',
                body: 'Identified root cause: Line 184 attempts to overwrite BillingTerms__c without checking whether account has Enterprise Custom Billing enabled, violating Validation Rule VR_Subscription_Billing_Match.',
                isError: false,
                meta: { result_role: 'subagent_return' },
                children: [],
              },
            ],
          },
          {
            id: 'node-crm-jira',
            kind: 'tool_call',
            timestamp: '2026-09-05T08:10:35Z',
            label: 'jira · create_issue',
            badge: 'MCP',
            body: JSON.stringify(
              {
                project: 'CORE',
                issueType: 'Bug',
                summary:
                  'BillingRollupDispatcher line 184 fails VR_Subscription_Billing_Match on dual-contract accounts',
                description:
                  'Validation exception thrown when processing enterprise accounts 0015g00000XyZ12AAQ. Fix requires conditional check for custom terms.',
                priority: 'High',
              },
              null,
              2,
            ),
            isError: false,
            children: [
              {
                id: 'node-crm-jira-res',
                kind: 'tool_result',
                timestamp: '2026-09-05T08:10:38Z',
                label: 'Jira Issue Created',
                badge: 'RESULT',
                body: JSON.stringify(
                  {
                    key: 'CORE-4921',
                    url: 'https://jira.corp.internal/browse/CORE-4921',
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [],
              },
            ],
          },
          {
            id: 'node-crm-final',
            kind: 'result',
            timestamp: '2026-09-05T08:10:55Z',
            label: 'Final',
            badge: 'RESULT',
            body: `### Billing Exception Investigation Complete

- **Bug Root Cause**: \`BillingRollupDispatcher.cls:184\` attempts to apply default billing terms to child subscriptions without evaluating whether the enterprise account has \`HasDualContractTerms__c\` enabled. This triggers database validation exception \`FIELD_CUSTOM_VALIDATION_EXCEPTION: Invoicing terms mismatch\`.
- **Affected Records**: Account \`0015g00000XyZ12AAQ\` and \`0015g00000AbC34AAQ\`.
- **Engineering Escalation**: Created Jira bug ticket **[CORE-4921](https://jira.corp.internal/browse/CORE-4921)**.
- **Recommended Code Fix**:
  \`\`\`java
  if (masterContract.HasDualContractTerms__c && !account.HasCustomBillingOverride__c) {
      sub.BillingTerms__c = masterContract.DefaultInvoicingOption__c;
  }
  \`\`\``,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 4,
        toolErrors: 0,
        assistantMessages: 4,
        subagentSpawns: 1,
        totalTurns: 14,
        tokensIn: 10400,
        tokensOut: 4420,
      },
      skillsUsed: ['large-result-handling', 'crm-query-strategy'],
      mcpsUsed: ['jira', 'salesforce', 'memory'],
      heartbeats: [{ timestamp: '2026-09-05T08:10:40Z' }],
      eventCount: 16,
    },
  },

  '57f62e31-ee6d-4cb5-b128-a748b8aede70': {
    id: 'sess-57f62e31-ee6d-4cb5-b128-a748b8aede70',
    task_id: '57f62e31-ee6d-4cb5-b128-a748b8aede70',
    agent_id: 'agent-004',
    status: 'succeeded',
    started: '2026-09-01T09:00:01Z',
    ended: '2026-09-01T09:01:05Z',
    duration_sec: 64.1,
    tokens_input: 18200,
    tokens_output: 8200,
    turns: 16,
    task: MOCK_TASKS[5],
    tools_used: [
      { name: 'mcp__memory__reflect_patterns', count: 1, total_duration: 3.2 },
      {
        name: 'mcp__github__create_pull_request',
        count: 1,
        total_duration: 1.8,
      },
    ],
    subagents_used: [],
    error: null,
    trace: {
      root: {
        id: 'node-root-ref',
        kind: 'session',
        timestamp: '2026-09-01T09:00:01Z',
        label: 'self-reflection-agent',
        isError: false,
        children: [
          {
            id: 'node-ref-req',
            kind: 'lifecycle',
            timestamp: '2026-09-01T09:00:01Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[5].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-ref-think',
            kind: 'thinking',
            timestamp: '2026-09-01T09:00:03Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Initiating scheduled weekly reflection across all agent runs in the last 7 days.
I will query the Hindsight workflow-learning-ops bank to detect repeated query patterns and evaluate if automated skill updates can eliminate wasted turns.
Targeting patterns with frequency >= 3 across sessions to ensure statistical significance.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-ref-skill',
            kind: 'tool_call',
            timestamp: '2026-09-01T09:00:05Z',
            label: 'reflect',
            badge: 'SKILL',
            isError: false,
            children: [
              {
                id: 'node-ref-skill-res',
                kind: 'tool_result',
                timestamp: '2026-09-01T09:00:05Z',
                label: 'Skill Loaded',
                badge: 'RESULT',
                body: 'Loaded reflect skill for multi-session pattern reflection and PR proposal.',
                isError: false,
                children: [],
              },
            ],
          },
          {
            id: 'node-ref-mcp-mem',
            kind: 'tool_call',
            timestamp: '2026-09-01T09:00:10Z',
            label: 'memory · reflect_patterns',
            badge: 'MCP',
            body: JSON.stringify(
              {
                bank: 'workflow-learning-ops',
                window_days: 7,
                min_pattern_frequency: 3,
              },
              null,
              2,
            ),
            isError: false,
            children: [
              {
                id: 'node-ref-mcp-mem-res',
                kind: 'tool_result',
                timestamp: '2026-09-01T09:00:18Z',
                label: 'Patterns Found',
                badge: 'RESULT',
                body: `Reflection synthesis across 48 sessions:
Pattern 1 (Confidence 91%): In 14 of 19 Flow triage runs, subagents spent redundant turns querying deprecated table 'LegacySubscriptionAudit__c'.
Pattern 2 (Confidence 88%): Subagents investigating 502 Bad Gateway timeouts frequently attempt full Splunk payload parsing before invoking large-result-handling, adding an average of 4.2 redundant turns.`,
                isError: false,
                children: [],
              },
            ],
          },
          {
            id: 'node-ref-mcp-gh',
            kind: 'tool_call',
            timestamp: '2026-09-01T09:00:35Z',
            label: 'github · create_pull_request',
            badge: 'MCP',
            body: JSON.stringify(
              {
                repository: 'cloud-ops/agentic-workflows',
                branch: 'bot/optimize-crm-query-skill',
                title:
                  'perf(skills): filter deprecated LegacySubscriptionAudit from default SOQL patterns',
                body: 'Autonomous optimization proposed by Weekly Reflection Agent based on 14 observed redundant queries in Hindsight learning memory.',
              },
              null,
              2,
            ),
            isError: false,
            children: [
              {
                id: 'node-ref-mcp-gh-res',
                kind: 'tool_result',
                timestamp: '2026-09-01T09:00:40Z',
                label: 'PR Opened',
                badge: 'RESULT',
                body: JSON.stringify(
                  {
                    pr_number: 42,
                    html_url:
                      'https://github.corp.internal/cloud-ops/agentic-workflows/pull/42',
                  },
                  null,
                  2,
                ),
                isError: false,
                children: [],
              },
            ],
          },
          {
            id: 'node-ref-final',
            kind: 'result',
            timestamp: '2026-09-01T09:01:04Z',
            label: 'Final',
            badge: 'RESULT',
            body: `### Weekly Autonomous Reflection Summary

Analyzed **48 investigation traces** over the past 7 days from Hindsight \`workflow-learning-ops\` memory bank.

#### Key Inefficiency Identified
- In **14 out of 19 CRM triage sessions**, subagents repeatedly queried the deprecated \`LegacySubscriptionAudit__c\` object before falling back to \`SubscriptionChangeRequest__c\`.
- This accumulated **56 wasted turns** and ~140,000 superfluous tokens over the week.

#### Autonomous Remediation
Opened Pull Request **[PR #42](https://github.corp.internal/cloud-ops/agentic-workflows/pull/42)** on \`cloud-ops/agentic-workflows\`:
- Updates \`skills/crm-query-strategy/SKILL.md\` to explicitly deprecate the legacy object.
- Injects early filter heuristics into the \`crm-alerts-coordinator\` instructions.`,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 3,
        toolErrors: 0,
        assistantMessages: 4,
        subagentSpawns: 0,
        totalTurns: 16,
        tokensIn: 18200,
        tokensOut: 8200,
      },
      skillsUsed: ['reflect'],
      mcpsUsed: ['memory', 'github'],
      heartbeats: [{ timestamp: '2026-09-01T09:00:30Z' }],
      eventCount: 12,
    },
  },

  'ac5541b7-8115-4fe0-8963-fb2f515fac51': {
    id: 'sess-ac5541b7-8115-4fe0-8963-fb2f515fac51',
    task_id: 'ac5541b7-8115-4fe0-8963-fb2f515fac51',
    agent_id: 'agent-005',
    status: 'succeeded',
    started: '2026-09-05T08:00:01Z',
    ended: '2026-09-05T08:00:20Z',
    duration_sec: 19.3,
    tokens_input: 5800,
    tokens_output: 2440,
    turns: 6,
    task: MOCK_TASKS[6],
    tools_used: [
      { name: 'mcp__memory__recall_similar', count: 1, total_duration: 1.1 },
      { name: 'mcp__message__send_message', count: 1, total_duration: 0.3 },
    ],
    subagents_used: [],
    error: null,
    trace: {
      root: {
        id: 'node-root-digest',
        kind: 'session',
        timestamp: '2026-09-05T08:00:01Z',
        label: 'digest-reporter',
        isError: false,
        children: [
          {
            id: 'node-digest-req',
            kind: 'lifecycle',
            timestamp: '2026-09-05T08:00:01Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[6].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-digest-think',
            kind: 'thinking',
            timestamp: '2026-09-05T08:00:02Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Querying Hindsight incident-rca bank for all incidents resolved in the last 24 hours.
I will cluster by affected service (checkout-payment-gateway, auth-service-v2, crm-billing), compute MTTR, and format an executive morning brief for #ops-digest.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-digest-final',
            kind: 'result',
            timestamp: '2026-09-05T08:00:19Z',
            label: 'Final',
            badge: 'RESULT',
            body: `### Daily Operations Digest (Past 24 Hours)

**Executive Highlights**:
- **Total Incidents Triaged**: 6
- **Mean Time to Detection (MTTD)**: 1.8 minutes
- **Mean Time to Resolution (MTTR)**: 14.2 minutes
- **Automated Root Cause Confidence**: 92.4% avg across incidents

**Incidents Categorization**:
1. \`INC-0089201\` (P1) — Checkout DB connection starvation (Mitigated in 4.2m)
2. \`INC-0089182\` (P2) — Ingress TLS cert renewal verification (Automated)
3. \`INC-0089140\` (P3) — B2B Billing validation rule exception (Jira CORE-4921 filed)
4. 3 minor P4 warnings triaged and marked benign.

Digest posted to \`#ops-digest\` at 08:00 UTC.`,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 2,
        toolErrors: 0,
        assistantMessages: 2,
        subagentSpawns: 0,
        totalTurns: 6,
        tokensIn: 5800,
        tokensOut: 2440,
      },
      skillsUsed: ['incident-digest'],
      mcpsUsed: ['memory', 'message'],
      heartbeats: [{ timestamp: '2026-09-05T08:00:10Z' }],
      eventCount: 8,
    },
  },

  '9d28e714-38ab-40fc-8092-23c4a17951bc': {
    id: 'sess-9d28e714-38ab-40fc-8092-23c4a17951bc',
    task_id: '9d28e714-38ab-40fc-8092-23c4a17951bc',
    agent_id: 'agent-001',
    status: 'succeeded',
    started: '2026-09-04T22:00:01Z',
    ended: '2026-09-04T22:00:15Z',
    duration_sec: 14.8,
    tokens_input: 4200,
    tokens_output: 1920,
    turns: 5,
    task: MOCK_TASKS[7],
    tools_used: [
      { name: 'mcp__platform__query_tls_cert', count: 2, total_duration: 1.1 },
    ],
    subagents_used: [],
    error: null,
    trace: {
      root: {
        id: 'node-root-api',
        kind: 'session',
        timestamp: '2026-09-04T22:00:01Z',
        label: 'incident-coordinator',
        isError: false,
        children: [
          {
            id: 'node-api-req',
            kind: 'lifecycle',
            timestamp: '2026-09-04T22:00:01Z',
            label: 'REQUEST',
            badge: 'REQUEST',
            body: MOCK_TASKS[7].prompt,
            isError: false,
            children: [],
          },
          {
            id: 'node-api-think',
            kind: 'thinking',
            timestamp: '2026-09-04T22:00:02Z',
            label: 'Reasoning',
            badge: 'THINKING',
            body: `Received TLS certification verification webhook for payments.checkout.corp.internal and api.gateway.corp.internal.
I will call mcp__platform__query_tls_cert on both endpoints to verify expiration timestamps, SAN chains, and automated renewal secrets in Vault.`,
            isError: false,
            children: [],
          },
          {
            id: 'node-api-final',
            kind: 'result',
            timestamp: '2026-09-04T22:00:14Z',
            label: 'Final',
            badge: 'RESULT',
            body: `### Ingress TLS Certificate Verification

- \`https://payments.checkout.corp.internal\`: Valid until **2026-11-12** (68 days remaining). Issuer: Let's Encrypt E6.
- \`https://api.gateway.corp.internal/v2/auth\`: Valid until **2026-11-20** (76 days remaining). Issuer: DigiCert Global Root G2.
- **Auto-Renewal Check**: Cert-manager ClusterIssuer \`letsencrypt-prod\` operational; Vault renewal role active.`,
            isError: false,
            meta: { result_role: 'session_result' },
            children: [],
          },
        ],
      },
      stats: {
        toolCalls: 2,
        toolErrors: 0,
        assistantMessages: 2,
        subagentSpawns: 0,
        totalTurns: 5,
        tokensIn: 4200,
        tokensOut: 1920,
      },
      skillsUsed: [],
      mcpsUsed: ['platform'],
      heartbeats: [{ timestamp: '2026-09-04T22:00:10Z' }],
      eventCount: 6,
    },
  },
};
