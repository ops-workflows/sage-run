import type { McpServer, McpTool } from '@/lib/api';
import { MOCK_AGENTS } from './workflows';

function read(name: string, description: string): McpTool {
  return { name, description, read_only: true, open_world: false };
}

function write(name: string, description: string): McpTool {
  return { name, description, read_only: false, open_world: true };
}

function server(
  id: string,
  name: string,
  description: string,
  tools: McpTool[],
  group: McpServer['group'] = 'platform',
): McpServer {
  const used_by = MOCK_AGENTS.filter((workflow) => {
    const mcps = workflow.config?.mcps;
    return Array.isArray(mcps) && mcps.includes(id);
  })
    .map((workflow) => workflow.name)
    .sort();
  return {
    id,
    name,
    description,
    group,
    tools,
    usage_count: used_by.length,
    used_by,
  };
}

export const MOCK_MCP_SERVERS: McpServer[] = [
  server(
    'message',
    'Message Bus',
    'Post threaded results and visible workflow handoffs.',
    [
      write('post_message', 'Post a result in the current thread.'),
      write(
        'handoff_task',
        'Post an assignment and queue a separate workflow task.',
      ),
    ],
  ),
  server(
    'knowledge',
    'Controlled Knowledge',
    'Grant-bound access to promoted Confluence and GitHub snapshots.',
    [
      read('list_sources', 'List available source aliases and index types.'),
      read(
        'search_knowledge',
        'Find sections in the Checkout Operations Confluence snapshot.',
      ),
      read(
        'query_graph',
        'Trace code behavior in the immutable checkout-platform graph.',
      ),
    ],
  ),
  server(
    'memory',
    'Hindsight Memory',
    'Separate incident history from workflow-learning traces.',
    [
      read('recall_similar', 'Recall similar prior incidents as leads.'),
      write('retain_incident', 'Retain an RCA or a workflow-learning trace.'),
      read('reflect_patterns', 'Find repeated behavior in the learning bank.'),
    ],
  ),
  server(
    'platform',
    'Platform Self-Service',
    'Propose controlled changes to a workflow.',
    [write('propose_skill_update', 'Open a skill update PR for human review.')],
  ),
  server('cloudwatch', 'CloudWatch', 'Bounded evidence for checkout alerts.', [
    read(
      'search_api_gateway_5xx',
      'Check the alert window for a stable error signature.',
    ),
  ]),
  server(
    'github',
    'GitHub',
    'Read existing issues and file a grounded new issue.',
    [
      read(
        'list_pull_requests',
        'Review merged changes that can affect operator procedures.',
      ),
      read('search_issues', 'Search for an exact matching issue.'),
      read('get_issue', 'Read an issue and its current status.'),
      write(
        'create_issue',
        'Create an issue for a write-enabled repository alias.',
      ),
    ],
  ),
  server(
    'monitoring',
    'Operations Monitoring',
    'Read-only dashboard verification for the Ops assistant.',
    [read('lookup_dashboard', 'Check the current dashboard and metrics.')],
    'workflow',
  ),
  server(
    'salesforce',
    'Salesforce',
    'Read-only investigation of Flow metadata.',
    [read('query_tooling_records', 'Inspect the failing task-insert step.')],
  ),
  server('jira', 'Jira', 'Illustrative approval-gated escalation.', [
    write('create_bug_ticket', 'File the verified finding as a Jira Bug.'),
  ]),
  server(
    'servicenow-triage',
    'ServiceNow Triage',
    'Read the incident and demonstrate an illustrative approved route.',
    [
      read('get_ticket', 'Read the current incident and its eligibility.'),
      write(
        'update_ticket',
        'Apply the approved assignment and work note in the example.',
      ),
    ],
    'workflow',
  ),
];
