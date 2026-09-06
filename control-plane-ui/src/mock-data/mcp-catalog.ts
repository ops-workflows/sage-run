import type { McpServer } from '@/lib/api';

export const MOCK_MCP_SERVERS: McpServer[] = [
  {
    id: 'message',
    name: 'Message Bus Core',
    description:
      'Two-way operator messaging, clarification dialogs, and cross-workflow task handoff broker',
    usage_count: 1420,
    used_by: [
      'cloud-incident-investigator',
      'enterprise-crm-investigator',
      'online-platform-triage',
      'daily-operations-digest',
    ],
    tools: [
      {
        name: 'send_message',
        description:
          'Post structured progress updates and investigation findings to the designated channel or thread.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'handoff_task',
        description:
          'Delegate follow-up or secondary tasks to another specialized operational workflow asynchronously.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'request_user_clarification',
        description:
          'Prompt on-call operators for business or policy clarifications before proceeding.',
        read_only: false,
        open_world: false,
      },
    ],
  },
  {
    id: 'memory',
    name: 'Hindsight Episodic Memory',
    description:
      'Cross-session incident recall, episodic RCA retention, and weekly behavioral reflection',
    usage_count: 980,
    used_by: [
      'cloud-incident-investigator',
      'enterprise-crm-investigator',
      'weekly-reflection-and-learning',
      'daily-operations-digest',
    ],
    tools: [
      {
        name: 'recall_similar',
        description:
          'Semantic vector search across historical incident RCAs to find previous resolutions.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'retain_incident',
        description:
          'Persist verified incident root causes, evidence chains, and execution traces into Hindsight banks.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'reflect_patterns',
        description:
          'Aggregate execution bottlenecks, repeated tool failures, and query patterns across sessions.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'recall_for_digest',
        description:
          'Retrieve all incidents and anomalies logged within a specified temporal window.',
        read_only: true,
        open_world: false,
      },
    ],
  },
  {
    id: 'platform',
    name: 'Platform Self-Service & Ops',
    description:
      'Direct operational infrastructure controls, database queries, and deployment management',
    usage_count: 812,
    used_by: ['cloud-incident-investigator', 'online-platform-triage'],
    tools: [
      {
        name: 'execute_remediation_action',
        description:
          'Execute governed infrastructure remediations (e.g. pod rollout restarts, pool resets). Gated by approvals.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'query_pg_stat_activity',
        description:
          'Inspect active PostgreSQL transactions, wait events, query ages, and blocking lock chains.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'scale_deployment',
        description:
          'Dynamically scale Kubernetes pod replica counts during elevated incident load.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'query_tls_cert',
        description:
          'Verify SSL/TLS certificate validity, issuer, and days until expiration for any internal endpoint.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'flush_redis_cache',
        description:
          'Evict specific key namespaces or flush Redis cache nodes. Gated by approvals.',
        read_only: false,
        open_world: false,
      },
    ],
  },
  {
    id: 'knowledge',
    name: 'Knowledge Graph & Code Index',
    description:
      'AST-grounded code navigation and architectural service dependency graph',
    usage_count: 654,
    used_by: ['cloud-incident-investigator', 'enterprise-crm-investigator'],
    tools: [
      {
        name: 'lookup_symbol',
        description:
          'Find function, class, interface, and model definitions across indexed repositories.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'find_references',
        description:
          'Locate all call sites and usages of a given code symbol across microservices.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'get_service_dependencies',
        description:
          'Retrieve the architectural upstream and downstream dependency graph for a microservice.',
        read_only: true,
        open_world: false,
      },
    ],
  },
  {
    id: 'splunk',
    name: 'Splunk Log Search',
    description:
      'Enterprise search integration for distributed application logs and exception traces',
    usage_count: 1840,
    used_by: ['cloud-incident-investigator', 'online-platform-triage'],
    tools: [
      {
        name: 'search_logs',
        description:
          'Execute bounded Search Processing Language (SPL) queries against production log indexes.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'get_job_results',
        description:
          'Fetch paginated results for asynchronous or long-running Splunk search jobs.',
        read_only: true,
        open_world: false,
      },
    ],
  },
  {
    id: 'cloudwatch',
    name: 'AWS CloudWatch Metrics & Logs',
    description:
      'Amazon Web Services log group queries, metric alarms, and Container Insights telemetry',
    usage_count: 920,
    used_by: ['cloud-incident-investigator', 'online-platform-triage'],
    tools: [
      {
        name: 'filter_log_events',
        description:
          'Query CloudWatch log events with pattern-matching filters across Lambda and EKS log streams.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'get_metric_data',
        description:
          'Retrieve CloudWatch metric statistics (e.g. CPUUtilization, DatabaseConnections, HTTPCode_Target_5XX).',
        read_only: true,
        open_world: false,
      },
      {
        name: 'describe_alarms',
        description:
          'List active alarm state transitions and breach thresholds for cloud resources.',
        read_only: true,
        open_world: false,
      },
    ],
  },
  {
    id: 'salesforce',
    name: 'Salesforce & Enterprise CRM',
    description:
      'CRM object querying, Tooling API metadata inspection, and Flow version analysis',
    usage_count: 530,
    used_by: ['enterprise-crm-investigator'],
    tools: [
      {
        name: 'query_records',
        description:
          'Execute parameterized SOQL queries against allowed business entities (Account, Case, Order, etc.).',
        read_only: true,
        open_world: false,
      },
      {
        name: 'describe_object',
        description:
          'Inspect field definitions, validation rules, and relationship schemas for an sObject.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'get_metadata',
        description:
          'Retrieve Flow, ApexClass, and ValidationRule metadata via the CRM Tooling API.',
        read_only: true,
        open_world: false,
      },
    ],
  },
  {
    id: 'jira',
    name: 'Jira Software Tracking',
    description:
      'Automated engineering issue escalation, bug ticket creation, and incident linkage',
    usage_count: 310,
    used_by: ['cloud-incident-investigator', 'enterprise-crm-investigator'],
    tools: [
      {
        name: 'create_issue',
        description:
          'Create Jira Bug or Task tickets with markdown descriptions, reproduction steps, and priority.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'add_comment',
        description:
          'Append automated investigation findings or postmortem links to an existing Jira ticket.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'transition_issue',
        description:
          'Update Jira issue workflow status (e.g. In Progress, Closed, Escalate).',
        read_only: false,
        open_world: false,
      },
    ],
  },
  {
    id: 'github',
    name: 'GitHub Enterprise & Cloud',
    description:
      'Git repository inspection, blame analysis, and autonomous pull request creation',
    usage_count: 245,
    used_by: ['weekly-reflection-and-learning'],
    tools: [
      {
        name: 'create_pull_request',
        description:
          'Open a Git branch and create a Pull Request with proposed code or skill updates.',
        read_only: false,
        open_world: false,
      },
      {
        name: 'get_file_contents',
        description:
          'Read the latest or ref-pinned content of any repository file.',
        read_only: true,
        open_world: false,
      },
      {
        name: 'search_code',
        description:
          'Search repository source code for identifiers, config keys, and function signatures.',
        read_only: true,
        open_world: false,
      },
    ],
  },
];
