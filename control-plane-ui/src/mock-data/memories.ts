import type {
  AgentMemoryDetail,
  HindsightBankDetail,
  HindsightMemoryEntry,
  PlatformMemories,
} from '@/lib/api';

const archive = 'agent-memory/documentation/latest.tar.gz';
const projectNote = `# Documentation project memory

The checkout worker recovery runbook lives under the Checkout Operations documentation.
Use this location as a starting point; verify the current text before proposing a change.`;

export const MOCK_PLATFORM_MEMORIES: PlatformMemories = {
  hindsight_available: true,
  hindsight_banks: [
    {
      bank_id: 'checkout-incidents',
      label: 'Checkout incident history',
      kind: 'business',
      workflows: ['online-alerts-investigator'],
      listed_in_hindsight: true,
    },
    {
      bank_id: 'checkout-learning',
      label: 'Checkout investigator learning',
      kind: 'learning',
      workflows: ['online-alerts-investigator'],
      listed_in_hindsight: true,
    },
    {
      bank_id: 'ops-learning',
      label: 'Ops workflow learning',
      kind: 'learning',
      workflows: ['platform-ops-assistant'],
      listed_in_hindsight: true,
    },
  ],
  agent_memories: [
    {
      agent_name: 'documentation',
      latest_key: archive,
      latest_updated_at: '2026-11-16T10:11:00Z',
      version_count: 2,
    },
  ],
};

function bank(
  bankId: string,
  entries: HindsightMemoryEntry[],
  relationship: string,
): HindsightBankDetail {
  return {
    bank_id: bankId,
    listed_in_hindsight: true,
    warnings: [],
    stats: {
      total_nodes: entries.length + 1,
      total_links: entries.length,
      total_documents: entries.length,
      total_observations: entries.length,
      pending_operations: 0,
      failed_operations: 0,
      nodes_by_fact_type: { observation: entries.length },
      links_by_link_type: { context: entries.length },
    },
    graph: {
      nodes: [
        { id: 'pattern', label: relationship, node_type: 'entity' },
        ...entries.map((entry) => ({
          id: entry.id,
          label: String(entry.metadata.title),
          node_type: 'document',
        })),
      ],
      edges: entries.map((entry) => ({
        source: entry.id,
        target: 'pattern',
        edge_type: 'context',
        weight: 1,
      })),
      table_rows: entries.map((entry) => ({
        label: entry.metadata.title,
        context: entry.content,
        date: entry.created_at,
      })),
      total_units: entries.length,
    },
    entries,
  };
}

export const MOCK_HINDSIGHT_BANK_DETAILS: Record<string, HindsightBankDetail> =
  {
    'checkout-incidents': bank(
      'checkout-incidents',
      [
        {
          id: 'prior-retry',
          content:
            'A prior guest retry reached the session guard. Investigate with current CloudWatch logs rather than reusing the past conclusion.',
          metadata: { title: 'Prior guest retry incident' },
          created_at: '2026-11-12T10:10:00Z',
        },
        {
          id: 'evt-482',
          content:
            'RUN-1042 verified 27 PAYMENT_SESSION_EXHAUSTED events and grounded the retry behavior in checkout-platform. Filed GitHub #217; the trigger for the spike was not verified.',
          metadata: { title: 'EVT-482 · retained RCA', task_id: 'run-1042' },
          created_at: '2026-11-16T09:20:00Z',
        },
      ],
      'Checkout retry and session guard',
    ),
    'checkout-learning': bank(
      'checkout-learning',
      [
        {
          id: 'evt-482-provider',
          content:
            'RUN-1042: checking the same time window for gateway errors and provider timeouts distinguished two possible signatures.',
          metadata: {
            title: 'EVT-482 · CloudWatch evidence-gathering trace',
            task_id: 'run-1042',
          },
          created_at: '2026-11-16T09:15:00Z',
        },
        {
          id: 'evt-482-grounding',
          content:
            'RUN-1042: querying the authorized graph before opening an issue yielded a concrete handler path and pinned revision.',
          metadata: {
            title: 'EVT-482 · Code-grounding trace',
            task_id: 'run-1042',
          },
          created_at: '2026-11-16T09:17:00Z',
        },
      ],
      'Ground a fingerprint before filing',
    ),
    'ops-learning': bank(
      'ops-learning',
      [
        {
          id: 'late-environment',
          content:
            'Broad dashboard lookups took extra steps when the request did not identify an environment.',
          metadata: { title: 'Previous investigation pattern' },
          created_at: '2026-11-15T10:10:00Z',
        },
        {
          id: 'ops-1050',
          content:
            'One clarification in RUN-1050 led directly to the production runbook and live evidence. The stale instruction was handed off separately.',
          metadata: { title: 'RUN-1050 · clarify early', task_id: 'run-1050' },
          created_at: '2026-11-16T10:08:00Z',
        },
      ],
      'Ask the environment before selecting a runbook',
    ),
  };

export const MOCK_AGENT_MEMORY_DETAILS: Record<string, AgentMemoryDetail> = {
  documentation: {
    agent_name: 'documentation',
    archive_key: archive,
    files: [
      {
        path: 'MEMORY.md',
        size_bytes: projectNote.length,
        preview: projectNote,
      },
    ],
  },
};
