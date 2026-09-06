import {
  MOCK_AGENTS,
  MOCK_AGENT_FILES,
  MOCK_AGENT_SECRETS,
  MOCK_WORKFLOW_REPO_STATUS,
  MOCK_WORKFLOW_REPO_VERSIONS,
} from './workflows';
import { MOCK_TASKS, getMockTaskList } from './tasks';
import { MOCK_SESSIONS } from './sessions';
import { MOCK_APPROVALS, getMockPlatformApprovals } from './approvals';
import { MOCK_MCP_SERVERS } from './mcp-catalog';
import { MOCK_CONNECTORS } from './connectors';
import {
  MOCK_PLATFORM_MEMORIES,
  MOCK_HINDSIGHT_BANK_DETAILS,
  MOCK_AGENT_MEMORY_DETAILS,
} from './memories';
import {
  MOCK_KNOWLEDGE_SOURCES,
  MOCK_KNOWLEDGE_SOURCE_VERSIONS,
  MOCK_GITHUB_CONNECTIONS,
} from './knowledge-sources';
import { MOCK_SCHEDULES } from './schedules';
import { getMockBackgroundJobs, MOCK_BACKGROUND_JOBS } from './background-jobs';
import { getMockAnalytics, MOCK_ANALYTICS } from './analytics';

export async function handleMockApiRequest(
  method: string,
  pathSegments: string[],
  searchParams: URLSearchParams,
  body?: unknown,
): Promise<{ status: number; data: unknown }> {
  const path = pathSegments.join('/');

  // ── Workflows & Agents ──
  if (path === 'agents' && method === 'GET') {
    return { status: 200, data: MOCK_AGENTS };
  }

  const agentMatch = path.match(/^agents\/([^/]+)$/);
  if (agentMatch && method === 'GET') {
    const agent = MOCK_AGENTS.find((a) => a.name === agentMatch[1]);
    if (agent) return { status: 200, data: agent };
    return { status: 404, data: { detail: 'Agent not found' } };
  }

  const agentFilesMatch = path.match(/^agents\/([^/]+)\/files$/);
  if (agentFilesMatch && method === 'GET') {
    const files = MOCK_AGENT_FILES[agentFilesMatch[1]];
    if (files) return { status: 200, data: files };
    return {
      status: 200,
      data: {
        agent_yaml: `name: ${agentFilesMatch[1]}\nversion: 1.0.0\n`,
        files: {},
      },
    };
  }

  const agentSecretsMatch = path.match(/^agents\/([^/]+)\/secrets$/);
  if (agentSecretsMatch && method === 'GET') {
    const secrets = MOCK_AGENT_SECRETS[agentSecretsMatch[1]] || [];
    return { status: 200, data: secrets };
  }

  const agentPauseResume = path.match(/^agents\/([^/]+)\/(pause|resume)$/);
  if (agentPauseResume && method === 'POST') {
    const agent = MOCK_AGENTS.find((a) => a.name === agentPauseResume[1]);
    if (agent) {
      agent.paused = agentPauseResume[2] === 'pause';
      return { status: 200, data: agent };
    }
    return { status: 404, data: { detail: 'Agent not found' } };
  }

  // ── Workflow Repo ──
  if (path === 'platform/workflow-repo' && method === 'GET') {
    return { status: 200, data: MOCK_WORKFLOW_REPO_STATUS };
  }
  if (path === 'platform/workflow-repo/versions' && method === 'GET') {
    return { status: 200, data: MOCK_WORKFLOW_REPO_VERSIONS };
  }
  if (path === 'platform/workflow-repo/sync' && method === 'POST') {
    return {
      status: 200,
      data: {
        ...MOCK_WORKFLOW_REPO_STATUS,
        last_synced_at: new Date().toISOString(),
      },
    };
  }
  if (path === 'platform/workflow-repo/pin' && method === 'POST') {
    const ref = (body as { ref?: string })?.ref || 'main';
    MOCK_WORKFLOW_REPO_STATUS.pinned_ref = ref;
    return { status: 200, data: MOCK_WORKFLOW_REPO_STATUS };
  }

  // ── Tasks ──
  if (path === 'tasks' && method === 'GET') {
    const statusParam = searchParams.get('status') || undefined;
    const limit = parseInt(searchParams.get('limit') || '50', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);
    return {
      status: 200,
      data: getMockTaskList({ status: statusParam, limit, offset }),
    };
  }

  const taskMatch = path.match(/^tasks\/([^/]+)$/);
  if (taskMatch && method === 'GET') {
    const task = MOCK_TASKS.find((t) => t.id === taskMatch[1]);
    if (task) return { status: 200, data: task };
    return { status: 404, data: { detail: 'Task not found' } };
  }

  const taskReplyMatch = path.match(/^tasks\/([^/]+)\/message-reply$/);
  if (taskReplyMatch && method === 'GET') {
    return {
      status: 200,
      data: {
        message: 'Proceed with rolling restart of auth replica pool.',
        user_id: 'alex.morales',
        username: 'Alex Morales',
      },
    };
  }

  const taskRerunMatch = path.match(/^tasks\/([^/]+)\/rerun$/);
  if (taskRerunMatch && method === 'POST') {
    const task = MOCK_TASKS.find((t) => t.id === taskRerunMatch[1]);
    if (task) {
      task.status = 'queued';
      return { status: 200, data: { status: 'requeued', task } };
    }
    return { status: 404, data: { detail: 'Task not found' } };
  }

  // ── Sessions ──
  const sessionMatch = path.match(/^sessions\/([^/]+)$/);
  if (sessionMatch && method === 'GET') {
    const taskId = sessionMatch[1];
    const session = MOCK_SESSIONS[taskId];
    if (session) return { status: 200, data: session };
    // fallback minimal session if task exists
    const task = MOCK_TASKS.find((t) => t.id === taskId);
    if (task) {
      return {
        status: 200,
        data: {
          id: `sess-${taskId}`,
          task_id: taskId,
          agent_id: 'agent-001',
          status: task.status,
          started: task.created,
          ended: task.updated,
          duration_sec: task.duration_sec,
          tokens_input: Math.round(task.tokens_used * 0.7),
          tokens_output: Math.round(task.tokens_used * 0.3),
          turns: 10,
          task,
          tools_used: [],
          subagents_used: [],
          error: null,
          trace: {
            root: {
              id: 'root',
              kind: 'session',
              timestamp: task.created,
              label: 'coordinator',
              children: [
                {
                  id: 'req',
                  kind: 'lifecycle',
                  timestamp: task.created,
                  label: 'REQUEST',
                  badge: 'REQUEST',
                  body: task.prompt,
                  children: [],
                },
                {
                  id: 'res',
                  kind: 'result',
                  timestamp: task.updated,
                  label: 'Final',
                  badge: 'RESULT',
                  body: 'Task executed successfully.',
                  children: [],
                },
              ],
            },
            stats: {
              toolCalls: 0,
              toolErrors: 0,
              assistantMessages: 1,
              subagentSpawns: 0,
              totalTurns: 10,
              tokensIn: Math.round(task.tokens_used * 0.7),
              tokensOut: Math.round(task.tokens_used * 0.3),
            },
            heartbeats: [],
            skillsUsed: [],
            mcpsUsed: [],
            eventCount: 4,
          },
        },
      };
    }
    return { status: 404, data: { detail: 'Session not found' } };
  }

  // ── Schedules ──
  if (path === 'schedules' && method === 'GET') {
    return { status: 200, data: MOCK_SCHEDULES };
  }

  const scheduleToggleMatch = path.match(/^schedules\/([^/]+)$/);
  if (scheduleToggleMatch && method === 'PUT') {
    const sched = MOCK_SCHEDULES.find((s) => s.id === scheduleToggleMatch[1]);
    if (sched) {
      const payload = body as { enabled?: boolean };
      if (typeof payload?.enabled === 'boolean') {
        sched.enabled = payload.enabled;
      } else {
        sched.enabled = !sched.enabled;
      }
      return { status: 200, data: sched };
    }
    return { status: 404, data: { detail: 'Schedule not found' } };
  }

  // ── Approvals ──
  if (path === 'platform/approvals' && method === 'GET') {
    const limit = parseInt(searchParams.get('limit') || '100', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);
    return { status: 200, data: getMockPlatformApprovals(limit, offset) };
  }

  // ── MCP Catalog ──
  if (path === 'platform/mcp' && method === 'GET') {
    return { status: 200, data: MOCK_MCP_SERVERS };
  }

  // ── Connectors ──
  if (path === 'platform/connectors' && method === 'GET') {
    return { status: 200, data: MOCK_CONNECTORS };
  }

  const connectorToggleMatch = path.match(
    /^platform\/connectors\/([^/]+)\/(pause|resume)$/,
  );
  if (connectorToggleMatch && method === 'POST') {
    const connector = MOCK_CONNECTORS.find(
      (c) => c.id === connectorToggleMatch[1],
    );
    if (connector) {
      connector.paused = connectorToggleMatch[2] === 'pause';
      return { status: 200, data: connector };
    }
    return { status: 404, data: { detail: 'Connector not found' } };
  }

  // ── Memories ──
  if (path === 'platform/memories' && method === 'GET') {
    return { status: 200, data: MOCK_PLATFORM_MEMORIES };
  }

  const hindsightBankMatch = path.match(
    /^platform\/memories\/hindsight\/([^/]+)$/,
  );
  if (hindsightBankMatch && method === 'GET') {
    const bank = MOCK_HINDSIGHT_BANK_DETAILS[hindsightBankMatch[1]];
    if (bank) return { status: 200, data: bank };
    return {
      status: 200,
      data: {
        bank_id: hindsightBankMatch[1],
        listed_in_hindsight: true,
        warnings: [],
        stats: {
          total_nodes: 10,
          total_links: 15,
          total_documents: 5,
          total_observations: 10,
          pending_operations: 0,
          failed_operations: 0,
          nodes_by_fact_type: {},
          links_by_link_type: {},
        },
        graph: null,
        entries: [],
      },
    };
  }

  const agentMemoryMatch = path.match(/^platform\/memories\/agents\/([^/]+)$/);
  if (agentMemoryMatch && method === 'GET') {
    const memory = MOCK_AGENT_MEMORY_DETAILS[agentMemoryMatch[1]];
    if (memory) return { status: 200, data: memory };
    return {
      status: 200,
      data: {
        agent_name: agentMemoryMatch[1],
        archive_key: null,
        files: [
          {
            path: 'MEMORY.md',
            size_bytes: 420,
            preview: `# Project Memory\n\nVerified operational notes.`,
          },
        ],
      },
    };
  }

  // ── Knowledge Sources ──
  if (path === 'platform/knowledge-sources' && method === 'GET') {
    return { status: 200, data: MOCK_KNOWLEDGE_SOURCES };
  }
  if (
    path === 'platform/knowledge-sources/github-connections' &&
    method === 'GET'
  ) {
    return { status: 200, data: MOCK_GITHUB_CONNECTIONS };
  }

  const knowledgeSourceMatch = path.match(
    /^platform\/knowledge-sources\/([^/]+)$/,
  );
  if (knowledgeSourceMatch && method === 'GET') {
    const ks = MOCK_KNOWLEDGE_SOURCES.find(
      (k) => k.id === knowledgeSourceMatch[1],
    );
    if (ks) return { status: 200, data: ks };
    return { status: 404, data: { detail: 'Knowledge source not found' } };
  }

  const knowledgeSourceVersionsMatch = path.match(
    /^platform\/knowledge-sources\/([^/]+)\/versions$/,
  );
  if (knowledgeSourceVersionsMatch && method === 'GET') {
    const versions =
      MOCK_KNOWLEDGE_SOURCE_VERSIONS[knowledgeSourceVersionsMatch[1]] || [];
    return { status: 200, data: versions };
  }

  // ── Background Jobs ──
  if (path === 'platform/background-jobs' && method === 'GET') {
    const job_type = searchParams.get('job_type') || undefined;
    const status = searchParams.get('status') || undefined;
    const trigger = searchParams.get('trigger') || undefined;
    const knowledge_source_id =
      searchParams.get('knowledge_source_id') || undefined;
    const limit = parseInt(searchParams.get('limit') || '20', 10);
    const offset = parseInt(searchParams.get('offset') || '0', 10);
    return {
      status: 200,
      data: getMockBackgroundJobs({
        job_type,
        status,
        trigger,
        knowledge_source_id,
        limit,
        offset,
      }),
    };
  }

  const backgroundJobMatch = path.match(/^platform\/background-jobs\/([^/]+)$/);
  if (backgroundJobMatch && method === 'GET') {
    const job = MOCK_BACKGROUND_JOBS.find(
      (j) => j.id === backgroundJobMatch[1],
    );
    if (job) return { status: 200, data: job };
    return { status: 404, data: { detail: 'Job not found' } };
  }

  // ── Analytics ──
  if (path === 'analytics' && method === 'GET') {
    const startDate = searchParams.get('start_date') || undefined;
    const endDate = searchParams.get('end_date') || undefined;
    return { status: 200, data: getMockAnalytics(startDate, endDate) };
  }

  return {
    status: 404,
    data: { detail: `Mock route not found: ${method} /api/${path}` },
  };
}
