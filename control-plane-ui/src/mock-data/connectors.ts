import type { Connector } from '@/lib/api';

export const MOCK_CONNECTORS: Connector[] = [
  {
    id: 'message-ingress',
    name: 'Mattermost Ingress',
    type: 'mattermost',
    source_type: 'websocket',
    source_label: 'Northstar Retail · WebSocket',
    summary: 'Trusted monitoring posts and human mentions start tasks.',
    description:
      'Checkout alert EVT-482 and the Ops question arrived in Mattermost. The platform also posts connector-originated findings back to chat.',
    target_workflow: null,
    target_channel: null,
    paused: false,
    tags: ['chat', 'threads'],
  },
  {
    id: 'crm-alert-email',
    name: 'Salesforce Alert Email',
    type: 'gcp-pubsub',
    source_type: 'pubsub',
    source_label: 'GCP Pub/Sub · crm-alert-email',
    summary:
      'A Cloud Storage notification supplies the Salesforce alert email.',
    description:
      'Origin of RUN-1055. Investigation starts on notification; chat is used for approval and reporting.',
    target_workflow: 'sf-alerts-investigator',
    target_channel: 'crm-ops',
    paused: false,
    tags: ['pubsub', 'cloud-storage'],
  },
  {
    id: 'support-incidents',
    name: 'ServiceNow Support Incidents',
    type: 'servicenow',
    source_type: 'polling',
    source_label: 'ServiceNow · Support Intake',
    summary: 'Polls for eligible incidents in Support Intake.',
    description:
      'Origin of RUN-1060. The assignment change shown in this fictional demo is an illustrative approval-gated path.',
    target_workflow: 'support-ticket-triage',
    target_channel: 'support-triage',
    paused: false,
    tags: ['polling', 'incident'],
  },
  {
    id: 'slack-socket-ingress',
    name: 'Slack Socket Mode Ingress',
    type: 'slack',
    source_type: 'socket_mode',
    source_label: 'Slack · Socket Mode',
    summary: 'Alternative chat ingress for mentions and threaded replies.',
    description:
      'Catalog example only. This demo uses Mattermost ingress; the Slack presentation skin does not start tasks.',
    target_workflow: null,
    target_channel: null,
    paused: true,
    tags: ['chat', 'threads'],
  },
  {
    id: 'cloudwatch-alarm-intake',
    name: 'AWS CloudWatch Alarm Intake',
    type: 'webhook',
    source_type: 'webhook',
    source_label: 'CloudWatch · SNS webhook',
    summary:
      'Example of routing alarm notifications directly, without a chat post.',
    description:
      'Catalog example only. EVT-482 arrived as a trusted Mattermost post, not through this route.',
    target_workflow: 'online-alerts-investigator',
    target_channel: 'checkout-alerts',
    paused: true,
    tags: ['AWS', 'SNS', 'webhook'],
  },
  {
    id: 'datadog-webhook-intake',
    name: 'Datadog Alert Intake',
    type: 'webhook',
    source_type: 'webhook',
    source_label: 'Datadog · monitor webhook',
    summary: 'Example of routing APM and synthetic check notifications.',
    description:
      'Catalog example only. No Datadog alert is part of the linked demo stories.',
    target_workflow: 'online-alerts-investigator',
    target_channel: 'checkout-alerts',
    paused: true,
    tags: ['APM', 'synthetics', 'webhook'],
  },
];
