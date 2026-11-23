import type { SessionDetail, TraceNode } from '@/lib/api';
import { MOCK_TASKS } from './tasks';

type Step = Pick<TraceNode, 'kind' | 'label' | 'body' | 'badge'> & {
  children?: Step[];
  offsetSec?: number;
};

function tool(label: string, body: string): Step {
  return {
    kind: 'tool_call',
    label,
    children: [{ kind: 'tool_result', label: 'Result', body }],
  };
}

function skill(label: string, body: string): Step {
  return {
    kind: 'tool_call',
    badge: 'SKILL',
    label,
    children: [{ kind: 'tool_result', label: 'Skill loaded', body }],
  };
}

const DEMO_TRACES: Record<
  string,
  { steps: Step[]; result: string; skills?: string[]; mcps: string[] }
> = {
  'run-1042': {
    mcps: ['cloudwatch', 'github', 'knowledge', 'memory', 'message'],
    skills: ['online-aws-investigation', 'online-code-grounding'],
    steps: [
      {
        kind: 'messaging',
        label: 'Mattermost · acknowledgement',
        body: 'Working on it. EVT-482 → RUN-1042.',
      },
      {
        kind: 'subagent',
        label: 'aws-cloudwatch-investigator',
        children: [
          skill(
            'online-aws-investigation',
            'Use the alert window and region, group the matching application errors, and cross-check payment-provider timeouts.',
          ),
          tool(
            'cloudwatch · search_api_gateway_5xx',
            '27 matching PAYMENT_SESSION_EXHAUSTED events in production, 09:09–09:14 UTC. No matching rise in payment-provider timeouts.',
          ),
          {
            kind: 'result',
            label: 'Branch findings · CloudWatch',
            body: 'The application error is consistent across the alert window. The payment-provider timeout metric does not show the same spike.',
          },
        ],
      },
      {
        kind: 'hook',
        label: 'SubagentStop · retain specialist trace',
        body: 'Saved the CloudWatch evidence-gathering trace to checkout-learning.',
        offsetSec: 60,
      },
      tool(
        'github · search_issues',
        'No exact open issue matched the provider fingerprint.',
      ),
      tool(
        'memory · recall_similar',
        'checkout-incidents: a prior retry incident suggests checking the session guard. The recalled case is a lead, not current proof.',
      ),
      {
        kind: 'subagent',
        label: 'online-code-grounder',
        children: [
          skill(
            'online-code-grounding',
            'Ground the unmatched error signature in an authorized snapshot. Record the pinned revision, file, and verified behavior before filing.',
          ),
          tool(
            'knowledge · query_graph',
            'checkout-platform → services/checkout/src/retry-handler.ts at 8f42c71. Retry keeps the session ID and hits the same guard.',
          ),
          {
            kind: 'result',
            label: 'Branch findings · Code grounding',
            body: 'The retry handler reuses the exhausted payment session. That explains the sampled error signature, not what triggered the spike.',
          },
        ],
      },
      {
        kind: 'hook',
        label: 'SubagentStop · retain specialist trace',
        body: 'Saved the grounding trace to checkout-learning, separate from the incident RCA.',
        offsetSec: 180,
      },
      tool(
        'github · create_issue',
        'Created open issue #217: Checkout retries exhaust guest payment sessions.',
      ),
      tool(
        'message · post_message',
        'Posted the assessment, code evidence, and issue #217 in #checkout-alerts.',
      ),
      {
        kind: 'hook',
        label: 'Stop · retain incident RCA',
        body: 'The final report matched the Online alert investigation heading. Retained the evidence and its limits in checkout-incidents.',
      },
    ],
    result: `## Online alert investigation

**Status:** Verified · **Provider:** CloudWatch · EVT-482

**Assessment:** A second checkout retry reuses an exhausted payment session. That explains the 5xx signature in the sampled guest requests.

### Provider evidence
- **Observed:** 27 matching \`PAYMENT_SESSION_EXHAUSTED\` events in production, 09:09–09:14 UTC.
- **Cross-check:** No matching rise in payment-provider timeouts.

### Code grounding
**Grounded:** \`services/checkout/src/retry-handler.ts\` at \`8f42c71\`. The retry keeps the session ID and hits the same guard.

### Tracking & evidence gaps
Created GitHub issue **#217** after checking for an exact match. The trigger for the spike remains unverified.`,
  },
  'run-1043': {
    mcps: ['cloudwatch', 'github', 'message'],
    steps: [
      {
        kind: 'user',
        label: 'Hydrated Mattermost context',
        body: 'Maya Chen asked about guest vs. signed-in impact. Leo Ortiz supplied the 09:19 rollback and mentioned the investigator.',
      },
      tool(
        'cloudwatch · search_api_gateway_5xx',
        'All matching samples were guest requests. The error rate fell after 09:19; this does not establish cause.',
      ),
      tool(
        'github · get_issue',
        '#217 remains open. This task did not modify the issue.',
      ),
      tool(
        'message · post_message',
        'Posted the follow-up in the original EVT-482 thread.',
      ),
    ],
    result:
      '**Confirmed impact:** The matching failures in the sample were guest checkouts. The signed-in sample did not show the same signature; total customer impact is unknown.\n\n**Rollback:** Errors fell after 09:19, but timing alone does not establish causality. Issue #217 remains open.',
  },
  'run-1050': {
    mcps: ['knowledge', 'monitoring', 'message'],
    skills: ['source-of-truth'],
    steps: [
      {
        kind: 'messaging',
        label: 'Clarification requested',
        body: 'Which environment is the worker in? 1. Production  2. Staging',
      },
      {
        kind: 'user',
        label: 'Jules Park · clarification reply',
        body: '1 — production.',
        offsetSec: 60,
      },
      skill(
        'source-of-truth',
        'Use the indexed runbook for procedure and monitoring for current state. When they disagree, cite both and flag the stale step.',
      ),
      tool(
        'knowledge · list_sources',
        'checkout-operations is authorized; hybrid_vector; promoted snapshot v12.',
      ),
      tool(
        'knowledge · search_knowledge',
        'Checkout Operations › Stalled worker recovery. Step 2 still names the retired dashboard.',
      ),
      tool(
        'monitoring · lookup_dashboard',
        'Checkout Worker Health contains queue depth and worker heartbeats. The old dashboard is retired.',
      ),
      tool(
        'message · post_message',
        'Posted the cited answer without waiting for documentation follow-up.',
      ),
      tool(
        'message · handoff_task',
        'Illustrative handoff: posted in #docs-review and queued documentation task RUN-1056.',
      ),
      {
        kind: 'hook',
        label: 'Stop · retain Ops learning trace',
        body: 'ops-learning: asking the environment first led directly to the production runbook and live evidence. No business-memory record was written.',
      },
    ],
    result:
      '## Production checkout worker\n\n**Answer:** Use **Stalled worker recovery**. Check queue depth and worker heartbeats before deciding whether to restart.\n\n**Verified live:** Both metrics are available in **Checkout Worker Health**; the old dashboard in step 2 is retired.\n\n**Source:** Confluence · Checkout Operations › Stalled worker recovery · snapshot **v12**.\n\n**Follow-up:** Documentation proposal requested in **RUN-1056**. No operational change was made.',
  },
  'run-1056': {
    mcps: ['message'],
    steps: [
      {
        kind: 'messaging',
        label: 'Cross-workflow assignment',
        body: 'Ops Assistant posted the stale-dashboard finding in #docs-review. Parent: RUN-1050.',
      },
      tool(
        'Read · project memory',
        'MEMORY.md identifies the checkout recovery runbook location. This is carried between documentation sessions.',
      ),
      tool(
        'Read · runbook draft context',
        'Verified the referenced step against the current text before preparing the proposed wording.',
      ),
      tool(
        'message · post_message',
        'Posted the proposal to #docs-review for its owner. No Confluence write.',
      ),
    ],
    result:
      '## Proposed text for step 2\n\nOpen **Checkout Worker Health**. Check queue depth and worker heartbeats before deciding whether a restart is necessary.\n\n**Ready for review.** No Confluence page was edited.',
  },
  'run-1055': {
    mcps: ['salesforce', 'jira', 'message'],
    skills: ['sf-alert-parsing'],
    steps: [
      {
        kind: 'lifecycle',
        label: 'GCP Pub/Sub · Salesforce email',
        body: 'A Cloud Storage notification supplied the Salesforce alert email. No incoming chat request or human initiator.',
      },
      skill(
        'sf-alert-parsing',
        'Extract the Flow, failing step, and observed event evidence from the email before routing to a specialist.',
      ),
      {
        kind: 'subagent',
        label: 'sf-flow-investigator',
        children: [
          tool(
            'salesforce · query_tooling_records',
            'Two deliveries used the same event key and the same failing task-insert step in Order Confirmation Flow.',
          ),
        ],
      },
      {
        kind: 'messaging',
        label: 'Approval requested · APR-55',
        body: 'Illustrative escalation policy: request approval for creating a Jira Bug, not for modifying Salesforce.',
        offsetSec: 240,
      },
      {
        kind: 'user',
        label: 'Maya Chen · approved APR-55',
        body: 'Approved the Jira Bug draft in #crm-ops.',
        offsetSec: 360,
      },
      tool(
        'jira · create_bug_ticket',
        'Created the illustrative Jira Bug CRM-431 after approval. No Salesforce changes.',
      ),
      tool(
        'message · post_message',
        'Posted the RCA and Jira reference in #crm-ops.',
      ),
    ],
    result:
      '## Salesforce alert investigation\n\n**Assessment:** The order-confirmation Flow attempts another follow-up insert when it receives the same event twice.\n\n### Evidence\nThe Flow specialist confirmed two deliveries with the same event key and the same failing insert step. The email received via Pub/Sub supplied the initial evidence.\n\n### Impact and next step\nThe retry failed for the sample order. Wider impact is unverified. Check whether the event key can be used to find the existing task before another insert.\n\n### Tracking\nFiled **CRM-431** after Maya approved **APR-55**. No Salesforce records were changed.',
  },
  'run-1060': {
    mcps: ['servicenow-triage', 'message'],
    skills: ['triage-decision-order'],
    steps: [
      {
        kind: 'lifecycle',
        label: 'ServiceNow polling · INC-308',
        body: 'Picked up an existing eligible incident from Support Intake. This was not a Mattermost request.',
      },
      skill(
        'triage-decision-order',
        'Read the ticket and ownership evidence before proposing a route. Keep the assignment and work note staged until approved.',
      ),
      {
        kind: 'subagent',
        label: 'Ticket reader',
        children: [
          tool(
            'servicenow-triage · get_ticket',
            'INC-308: checkout worker queue delayed, assignment group Support Intake.',
          ),
        ],
      },
      {
        kind: 'subagent',
        label: 'CMDB resolver',
        body: 'Checkout Operations owns the production checkout worker.',
      },
      {
        kind: 'subagent',
        label: 'Routing advisor',
        body: 'Proposed assignment group Checkout Operations, with a work note explaining the evidence.',
      },
      {
        kind: 'messaging',
        label: 'Approval requested · APR-60',
        body: 'Show the proposed group change and work note. No field was updated while pending.',
        offsetSec: 180,
      },
      {
        kind: 'user',
        label: 'Noor Vale · approved APR-60',
        body: 'Approved the staged update in #support-triage.',
        offsetSec: 240,
      },
      tool(
        'servicenow-triage · update_ticket',
        'Illustrative receipt: INC-308, assignment group Support Intake → Checkout Operations; work note added.',
      ),
      tool(
        'message · post_message',
        'Posted a two-line confirmation in #support-triage.',
      ),
    ],
    result:
      '**INC-308 updated:** Assigned to Checkout Operations after Noor’s approval.\n\nCMDB evidence and the routing reason are in the ticket’s work note.',
  },
  'run-1070': {
    mcps: ['memory', 'platform', 'message'],
    skills: ['reflect'],
    steps: [
      {
        kind: 'lifecycle',
        label: 'Cron · weekly-reflection',
        body: 'Scheduled Ops learning review. No human initiator.',
      },
      {
        kind: 'subagent',
        label: 'ops-workflow-reflector',
        children: [
          skill(
            'reflect',
            'Read only the Ops learning bank. Propose a reviewable skill change for a repeatable pattern; leave it unmerged.',
          ),
          tool(
            'memory · reflect_patterns',
            'ops-learning: across retained traces, asking about environment first avoided unnecessary lookups. RUN-1050 is one example.',
          ),
          tool(
            'platform · propose_skill_update',
            'Opened GitHub PR #34 with a small SKILL.md change. Awaiting human review.',
          ),
        ],
      },
      tool(
        'message · post_message',
        'Posted the weekly pattern and PR reference to #workflow-learning.',
      ),
    ],
    result:
      '## Weekly reflection · Ops Assistant\n\n**Pattern:** Asking about the environment first avoided unnecessary lookups. Read the Ops learning bank, not the incident RCA bank.\n\n**Proposal:** GitHub **PR #34** — ask whether the request is about production or staging before choosing a runbook when the environment is ambiguous. Awaiting review; no workflow instructions have changed.',
  },
};

function nodes(steps: Step[], time: number, prefix: string): TraceNode[] {
  let timestamp = time;
  return steps.map(({ children, offsetSec, ...step }, index) => {
    const id = `${prefix}-${index}`;
    if (offsetSec !== undefined) timestamp = time + offsetSec * 1000;
    const node: TraceNode = {
      ...step,
      id,
      timestamp: new Date(timestamp).toISOString(),
      children: nodes(children ?? [], timestamp + 100, id),
    };
    timestamp += 1000;
    return node;
  });
}

export const MOCK_SESSIONS: Record<string, SessionDetail> = Object.fromEntries(
  MOCK_TASKS.filter((task) => Object.hasOwn(DEMO_TRACES, task.id)).map(
    (task) => {
      const demo = DEMO_TRACES[task.id];
      const children = nodes(
        [
          { kind: 'lifecycle', label: 'REQUEST', body: task.prompt },
          ...demo.steps,
        ],
        Date.parse(task.created),
        task.id,
      );
      children.push({
        id: `${task.id}-final`,
        kind: 'result',
        timestamp: task.updated,
        label: 'Final',
        badge: 'RESULT',
        body: demo.result,
        meta: { result_role: 'session_result' },
        children: [],
      });
      const flatten = (events: TraceNode[]): TraceNode[] =>
        events.flatMap((node) => [node, ...flatten(node.children)]);
      const events = flatten(children);
      const tools = events.filter((node) => node.kind === 'tool_call');
      const subagents = events.filter((node) => node.kind === 'subagent');
      const tokensIn = Math.round(task.tokens_used * 0.72);
      const tokensOut = task.tokens_used - tokensIn;
      const session: SessionDetail = {
        id: `session-${task.id}`,
        task_id: task.id,
        agent_id: task.workflow,
        status: task.status,
        started: task.created,
        ended: task.updated,
        duration_sec: task.duration_sec,
        tokens_input: tokensIn,
        tokens_output: tokensOut,
        turns: events.length,
        task,
        error: task.error,
        tools_used: tools.map((node) => ({
          name: node.label,
          count: 1,
          total_duration: 0,
        })),
        subagents_used: subagents.map((node) => ({
          name: node.label,
          turns: node.children.length + 1,
          tokens: 0,
        })),
        trace: {
          root: {
            id: `${task.id}-root`,
            kind: 'session',
            timestamp: task.created,
            label: task.workflow,
            children,
          },
          stats: {
            toolCalls: tools.length,
            toolErrors: 0,
            assistantMessages: 1,
            subagentSpawns: subagents.length,
            totalTurns: events.length,
            tokensIn,
            tokensOut,
          },
          heartbeats: [],
          skillsUsed: demo.skills ?? [],
          mcpsUsed: demo.mcps,
          eventCount: events.length,
        },
      };
      return [task.id, session];
    },
  ),
);
