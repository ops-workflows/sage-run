import type {
  Agent,
  AgentFilesResult,
  SecretItem,
  WorkflowRepoStatus,
  WorkflowRepoVersion,
} from '@/lib/api';

export const MOCK_AGENTS: Agent[] = [
  {
    id: 'agent-001',
    name: 'cloud-incident-investigator',
    description:
      'High-severity cloud and infrastructure incident coordinator — investigates container, telemetry, database, and microservice failures',
    version: '2.4.0',
    provisioned: true,
    paused: false,
    provisioned_at: '2026-09-01T08:00:00Z',
    repo_path: 'workflows/cloud-incident-investigator',
    created: '2026-08-15T10:00:00Z',
    updated: '2026-09-05T06:00:00Z',
    config: {
      session: {
        max_turns: 60,
        model: 'sdc',
      },
      runtime: {
        parallel_workers: 4,
        priority: 'high',
        heartbeat_interval_sec: 30,
        lost_task_timeout_sec: 300,
        runtime_timeout_sec: 900,
        container_image: 'cloud-ops-agent-runtime:latest',
        memory_volumes: [
          'agent-memory-cloud-incident-investigator:/workspace/.claude/agent-memory',
        ],
      },
      messaging: {
        channels: ['#ops-incident-room', '#prod-alerts'],
        trigger_words: ['@agent', '@incident-bot'],
      },
      schedules: [
        {
          name: 'hourly-health-audit',
          cron: '0 * * * *',
          prompt:
            'Run proactive health check on core payment and checkout services.',
          enabled: true,
        },
      ],
    },
  },
  {
    id: 'agent-002',
    name: 'enterprise-crm-investigator',
    description:
      'Enterprise CRM, billing rules, and automation exception investigator — analyzes workflow rules, Apex stack traces, and data integrity',
    version: '2.3.1',
    provisioned: true,
    paused: false,
    provisioned_at: '2026-09-01T08:00:00Z',
    repo_path: 'workflows/enterprise-crm-investigator',
    created: '2026-08-18T14:30:00Z',
    updated: '2026-09-04T12:00:00Z',
    config: {
      session: {
        max_turns: 50,
        model: 'sdc',
      },
      runtime: {
        parallel_workers: 2,
        priority: 'medium',
        heartbeat_interval_sec: 30,
        lost_task_timeout_sec: 300,
        runtime_timeout_sec: 600,
        alert_coalesce_window_sec: 300,
        container_image: 'cloud-ops-agent-runtime:latest',
        memory_volumes: [
          'agent-memory-enterprise-crm-investigator:/workspace/.claude/agent-memory',
        ],
      },
      messaging: {
        channels: ['#crm-billing-alerts'],
        trigger_words: ['@agent'],
      },
      schedules: [],
    },
  },
  {
    id: 'agent-003',
    name: 'online-platform-triage',
    description:
      'Two-way interactive operations channel coordinator — triages latency spikes, 5xx errors, and executes governed infra remediations',
    version: '2.4.0',
    provisioned: true,
    paused: false,
    provisioned_at: '2026-09-01T08:00:00Z',
    repo_path: 'workflows/online-platform-triage',
    created: '2026-08-20T09:15:00Z',
    updated: '2026-09-05T07:20:00Z',
    config: {
      session: {
        max_turns: 100,
        model: 'sdc',
      },
      runtime: {
        parallel_workers: 3,
        priority: 'high',
        heartbeat_interval_sec: 30,
        lost_task_timeout_sec: 300,
        runtime_timeout_sec: 900,
        container_image: 'cloud-ops-agent-runtime:latest',
      },
      messaging: {
        channels: ['#ops-incident-room', '#platform-support'],
        trigger_words: ['@agent', '@sre-bot'],
      },
      schedules: [],
    },
  },
  {
    id: 'agent-004',
    name: 'weekly-reflection-and-learning',
    description:
      'Autonomous weekly meta-learning agent — mines Hindsight learning banks, evaluates investigation patterns, and opens improvement PRs',
    version: '2.1.0',
    provisioned: true,
    paused: false,
    provisioned_at: '2026-09-01T08:00:00Z',
    repo_path: 'workflows/weekly-reflection-and-learning',
    created: '2026-08-10T11:00:00Z',
    updated: '2026-09-01T08:00:00Z',
    config: {
      session: {
        max_turns: 30,
        model: 'sdc',
      },
      runtime: {
        parallel_workers: 1,
        priority: 'low',
        heartbeat_interval_sec: 30,
        lost_task_timeout_sec: 300,
        runtime_timeout_sec: 600,
      },
      schedules: [
        {
          name: 'weekly-reflection-run',
          cron: '0 9 * * 1',
          prompt:
            'Run the weekly workflow reflection across all operational workflows over the last 7 days. Identify bottlenecks and propose durable PRs.',
          enabled: true,
        },
      ],
      messaging: {
        channels: ['#ops-architecture'],
        trigger_words: ['@agent'],
      },
    },
  },
  {
    id: 'agent-005',
    name: 'daily-operations-digest',
    description:
      'Scheduled morning operational summary — recalls 24h incidents from long-term memory and publishes executive postmortems',
    version: '2.0.4',
    provisioned: true,
    paused: false,
    provisioned_at: '2026-09-01T08:00:00Z',
    repo_path: 'workflows/daily-operations-digest',
    created: '2026-08-12T16:00:00Z',
    updated: '2026-09-02T08:00:00Z',
    config: {
      session: {
        max_turns: 25,
        model: 'sdc',
      },
      runtime: {
        parallel_workers: 1,
        priority: 'low',
        heartbeat_interval_sec: 30,
        lost_task_timeout_sec: 300,
        runtime_timeout_sec: 300,
      },
      schedules: [
        {
          name: 'daily-morning-digest',
          cron: '0 8 * * 1-5',
          prompt:
            'Generate the daily incident summary for the last 24 hours. Recall all verified RCAs and post an executive digest to #ops-digest.',
          enabled: true,
        },
      ],
      messaging: {
        channels: ['#ops-digest'],
        trigger_words: [],
      },
    },
  },
];

export const MOCK_WORKFLOW_REPO_STATUS: WorkflowRepoStatus = {
  source_url: 'https://github.corp.internal/cloud-ops/agentic-workflows.git',
  source_path: '/repos/cloud-ops-workflows',
  source_mode: 'remote',
  default_ref: 'main',
  pinned_ref: 'v2.4.0-prod',
  last_synced_ref: 'v2.4.0-prod',
  last_synced_commit: '7f8a92c4b12e89d1a3c0042',
  last_synced_at: '2026-09-05T06:00:00Z',
  last_sync_status: 'succeeded',
  last_sync_error: null,
  discovered_workflows: [
    'cloud-incident-investigator',
    'enterprise-crm-investigator',
    'online-platform-triage',
    'weekly-reflection-and-learning',
    'daily-operations-digest',
  ],
  bundle_errors: {},
};

export const MOCK_WORKFLOW_REPO_VERSIONS: WorkflowRepoVersion[] = [
  { name: 'v2.4.0-prod', commit_sha: '7f8a92c4b12e89d1a3c0042' },
  { name: 'v2.3.9', commit_sha: 'e912ab08f23101c4b789120' },
  { name: 'v2.3.8', commit_sha: '30dfa912bb8912c01192e84' },
  { name: 'main', commit_sha: '1a4bc8992c3d11e8f203819' },
];

export const MOCK_AGENT_SECRETS: Record<string, SecretItem[]> = {
  'cloud-incident-investigator': [
    {
      name: 'SPLUNK_PASSWORD',
      description: 'Splunk search credentials for telemetry investigations',
      has_value: true,
    },
    {
      name: 'POSTGRES_READ_PASSWORD',
      description:
        'Read-only production database credentials for lock inspection',
      has_value: true,
    },
    {
      name: 'PAGERDUTY_TOKEN',
      description: 'PagerDuty integration token for incident sync',
      has_value: true,
    },
  ],
  'enterprise-crm-investigator': [
    {
      name: 'CRM_API_TOKEN',
      description: 'OAuth Bearer token for enterprise CRM API queries',
      has_value: true,
    },
    {
      name: 'JIRA_TOKEN',
      description: 'Jira API token for bug escalation and ticket filing',
      has_value: true,
    },
  ],
  'online-platform-triage': [
    {
      name: 'AWS_ACCESS_KEY_ID',
      description: 'AWS access key for CloudWatch logs and metrics',
      has_value: true,
    },
    {
      name: 'AWS_SECRET_ACCESS_KEY',
      description: 'AWS secret key for CloudWatch logs and metrics',
      has_value: true,
    },
    {
      name: 'SPLUNK_PASSWORD',
      description: 'Splunk query password',
      has_value: true,
    },
  ],
  'weekly-reflection-and-learning': [
    {
      name: 'GITHUB_APP_PRIVATE_KEY',
      description: 'GitHub App private key for automated PR creation',
      has_value: true,
    },
  ],
  'daily-operations-digest': [],
};

export const MOCK_AGENT_FILES: Record<string, AgentFilesResult> = {
  'cloud-incident-investigator': {
    agent_yaml: `name: cloud-incident-investigator
description: High-severity cloud and infrastructure incident coordinator — investigates container, telemetry, database, and microservice failures
version: 2.4.0

session:
  max_turns: 60
  model: sdc

env:
  SPLUNK_BASE_URL: https://splunk.corp.internal:8089
  K8S_CLUSTER: production-eu-west-1
  DATABASE_HOST: pg-primary.corp.internal

secrets:
  SPLUNK_PASSWORD:
    encrypted: "ENC[age,YWdlLWVuY3J5cHRpb24ub3JnL3YxCi0+...]"
    description: "Splunk credentials for telemetry investigator"
  POSTGRES_READ_PASSWORD:
    encrypted: "ENC[age,YWdlLWVuY3J5cHRpb24ub3JnL3YxCi0+...]"
    description: "Read-only DB credentials for lock investigation"

runtime:
  parallel_workers: 4
  priority: high
  heartbeat_interval_sec: 30
  lost_task_timeout_sec: 300
  runtime_timeout_sec: 900
  container_image: cloud-ops-agent-runtime:latest
  memory_volumes:
    - agent-memory-cloud-incident-investigator:/workspace/.claude/agent-memory

schedules:
  - name: hourly-health-audit
    cron: "0 * * * *"
    prompt: "Run proactive health check on core payment and checkout services."
    enabled: true

messaging:
  channels:
    - "#ops-incident-room"
    - "#prod-alerts"
  trigger_words:
    - "@agent"
`,
    files: {
      'agents/incident-coordinator.md': `---
name: incident-coordinator
description: Primary coordinator for production cloud outages and customer-impacting incidents.
memory: project
tools:
  - AskUserQuestion
  - Read
  - Write
  - Grep
  - Glob
  - Skill
  - TodoWrite
  - Agent(telemetry-investigator, database-investigator, k8s-service-investigator)
  - mcp__memory__recall_similar
  - mcp__memory__reflect_patterns
  - mcp__message__send_message
mcpServers:
  - memory
  - message
  - platform
---

You are the Lead Incident Coordinator for production infrastructure and microservice incidents.

## Strategy
1. **Analyze Incident Payload**: Extract service, error codes, customer tier, and affected pods.
2. **Review Long-Term Memory**: Identify prior incidents with matching signatures.
3. **Plan Investigation**: Use \`TodoWrite\` to structure targeted branches.
4. **Delegate Branches**:
   - Delegate log and telemetry analysis to \`telemetry-investigator\`.
   - Delegate database locks and query contention to \`database-investigator\`.
   - Delegate pod crashes and deployment changes to \`k8s-service-investigator\`.
5. **Synthesize Findings**: Compile a structured Root Cause Analysis with confidence scores.
`,
      'agents/telemetry-investigator.md': `---
name: telemetry-investigator
description: Specialist in log analysis, APM traces, and telemetry error spike inspection.
memory: project
tools:
  - Read
  - Write
  - Grep
  - Bash
  - Skill
  - mcp__splunk__search_logs
  - mcp__cloudwatch__filter_log_events
mcpServers:
  - splunk
  - cloudwatch
---

You are a Telemetry Specialist. Query Splunk and CloudWatch for service exceptions.
When results exceed 50KB, invoke \`large-result-handling\` and use \`Write\` + \`Grep\` + \`Read\` to inspect exact stack traces without token exhaustion.
`,
      'agents/database-investigator.md': `---
name: database-investigator
description: Specialist in PostgreSQL contention, lock trees, connection pool starvation, and slow queries.
memory: project
tools:
  - Read
  - Skill
  - mcp__platform__query_pg_stat_activity
  - mcp__platform__get_pg_locks
mcpServers:
  - platform
---

You investigate relational database performance, deadlocks, and connection pool saturation.
`,
      'skills/splunk-queries/SKILL.md': `---
name: splunk-queries
description: Optimized SPL search patterns for microservice exceptions and HTTP 5xx spikes
---

# Splunk Queries Skill

Use focused SPL queries with narrow time windows.
Example:
\`index=payment_prod host=checkout-* (status>=500 OR "Exception") | stats count by exception_class, host\`
`,
      'skills/large-result-handling/SKILL.md': `---
name: large-result-handling
description: Best practices for handling large tool responses and log dumps without context overflow
---

# Large Result Handling Skill

1. Save large tool outputs to \`/tmp/<file>.json\` using \`Write\`.
2. Locate exact error anchors using \`Grep\`.
3. Read narrow windows (15–30 lines) with \`Read\` or \`sed\`.
4. Do NOT dump the entire file into the conversation context.
`,
      'skills/incident-rca/SKILL.md': `---
name: incident-rca
description: Enterprise Root Cause Analysis format and confidence scoring rubric
---

# Incident RCA Standard

Every final RCA must contain:
- Problem Summary & Impact Window
- Root Cause Hypothesis with Supporting Evidence
- Verified Timeline of Key Events
- Immediate Remediation & Long-Term Preventive Actions
- Confidence Score (0–100%)
`,
      'hooks/hooks.json': `{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/auto_recall_hook.py",
            "timeout": 30
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/retain_incident_hook.py"
          }
        ]
      }
    ]
  }
}`,
      'hooks/auto_recall_hook.py': `#!/usr/bin/env python3
"""SessionStart hook — auto-recall from Hindsight for coordinator task.
Queries Hindsight for memories relevant to prompt and injects as additionalContext.
"""
import sys
print("[auto_recall_hook] auto-recalled 2 similar incidents from incident-rca-production", file=sys.stderr)
`,
      'hooks/retain_incident_hook.py': `#!/usr/bin/env python3
"""SubagentStop hook — auto-retain findings into Hindsight.
Writes business RCA to incident-rca and execution trace to workflow-learning.
"""
import sys
print("[retain_incident_hook] retained RCA to incident-rca-production and trace to workflow-learning-ops", file=sys.stderr)
`,
      'settings.json': `{
  "permissions": {
    "deny": [
      "Bash(rm -rf *)",
      "Bash(DROP DATABASE *)"
    ]
  },
  "sandbox": {
    "filesystem": {
      "allowWrite": ["/tmp", "/workspace"]
    }
  }
}`,
      '.mcp.json': `{
  "mcpServers": {
    "splunk": {
      "type": "http",
      "url": "http://mcp-splunk:8100/mcp"
    },
    "platform": {
      "type": "http",
      "url": "http://mcp-platform:8100/mcp"
    },
    "memory": {
      "type": "http",
      "url": "http://mcp-memory:8100/mcp"
    },
    "message": {
      "type": "http",
      "url": "http://mcp-message:8100/mcp"
    }
  }
}`,
      'README.md': `# Cloud Incident Investigator Workflow
Automates P1/P2 microservice and infrastructure triage using Claude Code Agent SDK.
`,
    },
  },
  'enterprise-crm-investigator': {
    agent_yaml: `name: enterprise-crm-investigator
description: Enterprise CRM, billing rules, and automation exception investigator
version: 2.3.1
session:
  max_turns: 50
  model: sdc
runtime:
  parallel_workers: 2
  priority: medium
`,
    files: {
      'agents/crm-alerts-coordinator.md': `---
name: crm-alerts-coordinator
description: Coordinator for CRM automation exceptions and billing calculation failures.
memory: project
tools:
  - Read
  - Write
  - Grep
  - Glob
  - Skill
  - Agent(backend-code-investigator, flow-automation-investigator)
  - mcp__jira__create_issue
---
Coordinates CRM and billing alert investigations.
`,
      'agents/backend-code-investigator.md': `---
name: backend-code-investigator
description: Inspects code stack traces and Apex/Java class bodies.
tools:
  - Read
  - Grep
  - Glob
---
Locates failing methods and line anchors.
`,
      'skills/large-result-handling/SKILL.md': `---
name: large-result-handling
description: Techniques to isolate failing code blocks quickly
---
Narrow oversized results with Grep and Read.
`,
      'skills/crm-query-strategy/SKILL.md': `---
name: crm-query-strategy
description: Best practices for SOQL and sObject querying without hitting governor limits
---
Avoid deprecated tables and use indexed ID fields.
`,
      'hooks/hooks.json': `{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/auto_recall_hook.py",
            "timeout": 30
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/retain_incident_hook.py"
          }
        ]
      }
    ]
  }
}`,
      'hooks/auto_recall_hook.py': `#!/usr/bin/env python3
"""SessionStart hook — auto-recall CRM patterns from Hindsight."""
import sys
print("[auto_recall_hook] recall completed", file=sys.stderr)
`,
      'hooks/retain_incident_hook.py': `#!/usr/bin/env python3
"""SubagentStop hook — auto-retain CRM triage findings into Hindsight."""
import sys
print("[retain_incident_hook] retain completed", file=sys.stderr)
`,
    },
  },
  'online-platform-triage': {
    agent_yaml: `name: online-platform-triage
description: Two-way interactive operations channel coordinator
version: 2.4.0
session:
  max_turns: 100
  model: sdc
`,
    files: {
      'agents/chat-intake-coordinator.md': `---
name: chat-intake-coordinator
description: Listens to Mattermost/Slack threads, analyzes ongoing operator discussions, and coordinates live remediations.
tools:
  - AskUserQuestion
  - Agent(api-gateway-investigator, infra-remediation-agent)
  - mcp__platform__execute_remediation_action
---
Handles chat intake and proposes governed remediations.
`,
      'agents/api-gateway-investigator.md': `---
name: api-gateway-investigator
description: Inspects CloudWatch APM logs and 5xx latency trends.
tools:
  - mcp__cloudwatch__filter_log_events
---
Analyzes Gateway HTTP responses.
`,
      'skills/api-failure-analysis/SKILL.md': `---
name: api-failure-analysis
description: Triage guide for 502/504 Gateway errors and connection pool exhaustion
---
Isolate connection status and CLOSE_WAIT socket counts.
`,
      'hooks/hooks.json': `{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/auto_recall_hook.py",
            "timeout": 30
          }
        ]
      }
    ],
    "SubagentStop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/retain_incident_hook.py"
          }
        ]
      }
    ]
  }
}`,
      'hooks/auto_recall_hook.py': `#!/usr/bin/env python3
import sys
print("[auto_recall_hook] recall completed", file=sys.stderr)
`,
      'hooks/retain_incident_hook.py': `#!/usr/bin/env python3
import sys
print("[retain_incident_hook] retain completed", file=sys.stderr)
`,
    },
  },
  'weekly-reflection-and-learning': {
    agent_yaml: `name: weekly-reflection-and-learning
description: Autonomous weekly meta-learning agent
version: 2.1.0
schedules:
  - name: weekly-reflection-run
    cron: "0 9 * * 1"
`,
    files: {
      'agents/self-reflection-agent.md': `---
name: self-reflection-agent
description: Analyzes past 7 days of investigations and opens PRs for durable skill improvements.
tools:
  - Skill
  - mcp__memory__reflect_patterns
  - mcp__github__create_pull_request
---
Self-improving agent.
`,
      'skills/reflect/SKILL.md': `---
name: reflect
description: Behavioral meta-learning across multi-session traces in Hindsight
---
Identify tool loops and query bottlenecks.
`,
      'hooks/hooks.json': `{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/auto_recall_hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}`,
      'hooks/auto_recall_hook.py': `#!/usr/bin/env python3
import sys
print("[auto_recall_hook] recall completed", file=sys.stderr)
`,
    },
  },
  'daily-operations-digest': {
    agent_yaml: `name: daily-operations-digest
description: Scheduled morning operational summary
version: 2.0.4
schedules:
  - name: daily-morning-digest
    cron: "0 8 * * 1-5"
`,
    files: {
      'agents/digest-reporter.md': `---
name: digest-reporter
description: Compiles 24-hour incident digest from Hindsight memory.
tools:
  - mcp__memory__recall_similar
  - mcp__message__send_message
---
Publishes daily digest.
`,
      'skills/incident-digest/SKILL.md': `---
name: incident-digest
description: Standards for executive operational summaries and MTTR rollups
---
Format incident highlights and resolution timeline.
`,
      'hooks/hooks.json': `{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup",
        "hooks": [
          {
            "type": "command",
            "command": "./hooks/auto_recall_hook.py",
            "timeout": 30
          }
        ]
      }
    ]
  }
}`,
      'hooks/auto_recall_hook.py': `#!/usr/bin/env python3
import sys
print("[auto_recall_hook] recall completed", file=sys.stderr)
`,
    },
  },
};
