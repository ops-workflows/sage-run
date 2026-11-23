import type { Agent, AgentFilesResult, WorkflowRepoStatus, WorkflowRepoVersion } from '@/lib/api';
import { MOCK_SCHEDULES } from './schedules';

const created = '2026-11-12T10:00:00Z';
const commit = 'd3a90781be2cfd42031a68cb174fae2cc98d54a1';

function retain(scope: 'learning' | 'business', options: { matcher?: string; resultPrefix?: string } = {}) {
  const command = `RETAIN_MEMORY_SCOPE=${scope}${options.resultPrefix ? ` RETAIN_RESULT_PREFIX='${options.resultPrefix}'` : ''} ./hooks/retain_incident_hook.py`;
  return { ...(options.matcher && { matcher: options.matcher }), hooks: [{ type: 'command', command }] };
}

const workflows = [
  {
    name: 'online-alerts-investigator',
    description: 'Investigate checkout alerts, verify evidence, and file new issues when grounded.',
    channel: 'checkout-alerts',
    mcps: ['message', 'memory', 'cloudwatch', 'knowledge', 'github'],
    agents: ['aws-cloudwatch-investigator', 'online-code-grounder'],
    skills: {
      'online-aws-investigation': 'Use the alarm window and region for the CloudWatch lookup. Report matching event counts, then cross-check payment-provider timeouts in the same window.',
      'online-code-grounding': 'Check for an exact open issue first. For an unmatched actionable signature, query the authorized code graph and cite the pinned revision, file, and observed behavior before filing.',
    },
    hooks: {
      SubagentStop: [
        retain('learning', { matcher: 'aws-cloudwatch-investigator' }),
        retain('learning', { matcher: 'online-code-grounder' }),
      ],
      Stop: [retain('business', { resultPrefix: '## Online alert investigation' })],
    },
    sources: ['checkout-platform'],
  },
  {
    name: 'platform-ops-assistant',
    description: 'Answer operational questions from indexed runbooks and current monitoring.',
    channel: 'ask-ops',
    mcps: ['message', 'knowledge', 'monitoring', 'memory', 'platform'],
    agents: ['ops-workflow-reflector'],
    skills: {
      'source-of-truth': 'Use the indexed runbook for procedure and monitoring for current state. When the evidence disagrees, cite the runbook revision and current signal, then flag the stale step for review.',
      reflect: 'Review the past seven days of Ops workflow learning, not business incident records. Identify a repeatable pattern, cite retained examples, and propose the smallest skill change as a PR for review.',
    },
    hooks: { Stop: [retain('learning')] },
    sources: ['checkout-operations'],
  },
  {
    name: 'documentation',
    description: 'Pick up visible handoffs and propose small documentation improvements for review.',
    channel: 'docs-review',
    mcps: ['message', 'github'],
    agents: ['doc-agent'],
  },
  {
    name: 'sf-alerts-investigator',
    description: 'Investigate Salesforce Flow failures from Pub/Sub and report evidence and impact.',
    channel: 'crm-ops',
    mcps: ['message', 'salesforce', 'jira'],
    agents: ['sf-flow-investigator'],
    skills: {
      'sf-alert-parsing': 'Extract the Flow name, failing step, and observed event evidence from the email. Hand off to the Flow specialist when the alert identifies a Flow failure. Report the evidence separately from wider impact.',
    },
    approval: 'mcp__jira__create_bug_ticket',
  },
  {
    name: 'support-ticket-triage',
    description: 'Resolve routing from ServiceNow and CMDB evidence. Illustrative approved write path.',
    channel: 'support-triage',
    mcps: ['message', 'servicenow-triage'],
    agents: ['ticket-reader', 'cmdb-resolver', 'routing-advisor'],
    skills: {
      'triage-decision-order': 'Read the incident, confirm the affected service in the CMDB, and stage the assignment and work note. Apply the staged change only after approval.',
    },
    approval: 'mcp__servicenow-triage__update_ticket',
  },
];

function workflowSchedules(name: string) {
  return MOCK_SCHEDULES.filter((schedule) => schedule.agent_name === name).map((schedule) => ({
    name: schedule.schedule_name,
    cron: schedule.cron_expression,
    enabled: schedule.enabled,
    prompt: schedule.prompt,
  }));
}

export const MOCK_AGENTS: Agent[] = workflows.map((workflow) => ({
  id: workflow.name,
  name: workflow.name,
  description: workflow.description,
  version: '1.0.0',
  provisioned: true,
  paused: false,
  provisioned_at: created,
  repo_path: `workflows/${workflow.name}`,
  config: {
    messaging: { channels: [workflow.channel] },
    mcps: workflow.mcps,
    ...(workflow.sources && { knowledge: { sources: workflow.sources } }),
    schedules: workflowSchedules(workflow.name),
  },
  created,
  updated: created,
}));

export const MOCK_WORKFLOW_REPO_STATUS: WorkflowRepoStatus & {
  deployment_enabled: boolean;
  platform_version: string;
} = {
  source_url: 'https://github.example/northstar-retail/sage-workflows',
  source_path: null,
  source_mode: 'remote',
  default_ref: 'main',
  pinned_ref: null,
  last_synced_ref: 'main',
  last_synced_commit: commit,
  last_synced_at: created,
  last_sync_status: 'succeeded',
  last_sync_error: null,
  discovered_workflows: workflows.map(({ name }) => name),
  bundle_errors: {},
  deployment_enabled: false,
  platform_version: '1.0.7',
};

export const MOCK_WORKFLOW_REPO_VERSIONS: WorkflowRepoVersion[] = [{ name: 'main', commit_sha: commit }];

export const MOCK_AGENT_FILES: Record<string, AgentFilesResult> = Object.fromEntries(
  workflows.map((workflow) => {
    const schedules = workflowSchedules(workflow.name);
    return [workflow.name, {
      agent_yaml: `name: ${workflow.name}\nversion: 1.0.0\nmessaging:\n  channels: [${workflow.channel}]\n${workflow.sources ? `knowledge:\n  sources: [${workflow.sources.join(', ')}]\n` : ''}${
        schedules.length ? `schedules:\n${schedules.map((schedule) =>
          `  - name: ${schedule.name}\n    cron: "${schedule.cron}"\n    enabled: ${schedule.enabled}\n    prompt: ${JSON.stringify(schedule.prompt)}\n`,
        ).join('')}` : ''}`,
      files: {
        'CLAUDE.md': `# ${workflow.name}\n\n${workflow.description}\n\nUse current evidence, report gaps, and separate recommendations from completed actions.`,
        'settings.json': JSON.stringify({ permissions: { ask: workflow.approval ? [workflow.approval] : [] } }, null, 2),
        '.mcp.json': JSON.stringify({ mcpServers: Object.fromEntries(workflow.mcps.map((id) => [id, { type: 'http', url: `http://mcp-${id}/mcp` }])) }, null, 2),
        ...Object.fromEntries(workflow.agents.map((name) => [`agents/${name}.md`, `---\nname: ${name}\n---\n\nReturn the evidence, its source, and any remaining gap to the coordinator.`])),
        ...Object.fromEntries(Object.entries(workflow.skills ?? {}).map(([name, text]) => [
          `skills/${name}/SKILL.md`, `---\nname: ${name}\n---\n\n${text}`,
        ])),
        ...(workflow.hooks && {
          'hooks/hooks.json': JSON.stringify({ hooks: workflow.hooks }, null, 2),
          'hooks/retain_incident_hook.py': '# Presentation fixture; never executed.\n# SubagentStop retains specialist traces. Stop retains the final result\n# in the configured bank only when the optional result prefix matches.\n',
        }),
      },
    }];
  }),
);
