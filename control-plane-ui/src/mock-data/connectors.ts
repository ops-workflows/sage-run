import type { Connector } from '@/lib/api';

export const MOCK_CONNECTORS: Connector[] = [
  {
    id: 'servicenow-incident-intake',
    name: 'ServiceNow Priority Incident Intake',
    summary:
      'Polls P1/P2 incidents from ServiceNow and queues automated investigation tasks',
    description:
      'Continuous polling adapter querying table "incident" every 30 seconds for state=1 (New) with priority <= 2. Coalesces alerts on incident_number with a 5-minute deduplication window.',
    source_type: 'polling',
    source_label: 'ServiceNow (table: incident)',
    target_workflow: 'cloud-incident-investigator',
    target_channel: 'servicenow',
    tags: ['ServiceNow', 'Incident Intake', 'Priority 1/2', 'Alert Coalescing'],
    type: 'servicenow',
    paused: false,
  },
  {
    id: 'gcp-pubsub-intake',
    name: 'GCP Cloud Pub/Sub Alerts Intake',
    summary:
      'Streams cloud storage object notifications and dead-letter queue alerts from Google Cloud',
    description:
      'Real-time streaming pull from subscription "projects/enterprise-ops-prod/subscriptions/ops-inbound-alerts-sub". Parses inbound alert emails and Cloud Storage payloads, extracting error types and affected records.',
    source_type: 'pubsub',
    source_label: 'GCP Pub/Sub (ops-inbound-alerts-sub)',
    target_workflow: 'enterprise-crm-investigator',
    target_channel: 'gcp-pubsub',
    tags: ['GCP', 'Pub/Sub', 'CRM Alerts', 'Cloud Storage'],
    type: 'gcp-pubsub',
    paused: false,
  },
  {
    id: 'mattermost-socket-ingress',
    name: 'Mattermost Real-Time Ingress',
    summary:
      'Listens to Mattermost WebSocket events for @agent trigger mentions and thread conversations',
    description:
      'Gateway-managed bidirectional WebSocket connection to Mattermost team "enterprise-ops". Hydrates the entire conversation thread as prompt context when triggered, and routes replies back to the origin thread.',
    source_type: 'websocket',
    source_label: 'Mattermost Gateway Listener',
    target_workflow: 'online-platform-triage',
    target_channel: 'mattermost',
    tags: ['ChatOps', 'Mattermost', 'Two-Way Messaging', 'Human-in-the-Loop'],
    type: 'mattermost',
    paused: false,
  },
  {
    id: 'slack-socket-ingress',
    name: 'Slack Socket Mode Ingress',
    summary:
      'Listens to Slack Socket Mode events for interactive incident war-room investigations',
    description:
      'Alternative real-time messaging connector connecting to Slack workspace over WebSocket without exposing incoming webhook ports. Supports interactive approval buttons and status cards.',
    source_type: 'socket_mode',
    source_label: 'Slack Socket Mode Listener',
    target_workflow: 'online-platform-triage',
    target_channel: 'slack',
    tags: ['ChatOps', 'Slack', 'Interactive', 'Approvals'],
    type: 'slack',
    paused: false,
  },
  {
    id: 'cloudwatch-alarm-intake',
    name: 'AWS CloudWatch Alarm Intake',
    summary: 'Receives CloudWatch alarm state changes via SNS HTTP webhook',
    description:
      'Subscribes to SNS topic "arn:aws:sns:eu-west-1:123456789012:production-cloudwatch-alarms". Translates ALARM state notifications into prioritized investigation tasks.',
    source_type: 'webhook',
    source_label: 'AWS CloudWatch / SNS Webhook',
    target_workflow: 'online-platform-triage',
    target_channel: 'api',
    tags: ['AWS', 'CloudWatch', 'SNS', 'Alarms'],
    type: 'webhook',
    paused: false,
  },
  {
    id: 'datadog-webhook-intake',
    name: 'Datadog Alert Intake',
    summary:
      'Receives APM anomaly and synthetic check alerts from Datadog webhooks',
    description:
      'Webhook receiver for Datadog monitor notifications. Automatically extracts metric tags, impacted cluster regions, and snapshot graph links.',
    source_type: 'webhook',
    source_label: 'Datadog Webhook Ingestion',
    target_workflow: 'cloud-incident-investigator',
    target_channel: 'api',
    tags: ['Datadog', 'APM', 'Synthetics', 'Webhook'],
    type: 'webhook',
    paused: false,
  },
];
