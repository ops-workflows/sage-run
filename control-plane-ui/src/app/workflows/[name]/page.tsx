'use client';

import { useEffect, useState } from 'react';
import {
  type Agent,
  type AgentFilesResult,
  apiFetch,
} from '@/lib/api';
import {
  getAgentModelBadgeClasses,
  getAgentModelInfo,
} from '@/lib/agent-model';
import { SyntaxCode } from '@/components/content-preview';
import { PluginPreview } from '@/components/plugin-preview';
import { useParams } from 'next/navigation';

type Tab = 'preview' | 'config' | 'schedules';

export default function AgentDetailPage() {
  const params = useParams();
  const nameParam = params?.name;
  const name = Array.isArray(nameParam) ? nameParam[0] : (nameParam ?? '');
  const [agent, setAgent] = useState<Agent | null>(null);
  const [tab, setTab] = useState<Tab>('preview');
  const [loading, setLoading] = useState(true);
  const [pluginFiles, setPluginFiles] = useState<AgentFilesResult | null>(null);
  const [pluginFilesLoading, setPluginFilesLoading] = useState(false);

  useEffect(() => {
    setAgent(null);
    setTab('preview');
    setPluginFiles(null);
    setPluginFilesLoading(false);
    setLoading(true);
  }, [name]);

  useEffect(() => {
    if (!name) {
      setLoading(false);
      return;
    }
    apiFetch<Agent>(`/api/agents/${name}`)
      .then(setAgent)
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [name]);

  const loadPluginFiles = () => {
    if (!name || pluginFiles || pluginFilesLoading) return;
    setPluginFilesLoading(true);
    apiFetch<AgentFilesResult>(`/api/agents/${name}/files`)
      .then(setPluginFiles)
      .catch(console.error)
      .finally(() => setPluginFilesLoading(false));
  };

  useEffect(() => {
    if (tab === 'preview') loadPluginFiles();
  }, [tab, name, pluginFiles, pluginFilesLoading]);

  if (loading)
    return (
      <p className="text-[var(--color-text-tertiary)]">Loading agent...</p>
    );
  if (!name)
    return (
      <p className="text-[var(--color-text-tertiary)]">Invalid agent route</p>
    );
  if (!agent)
    return <p className="text-[var(--color-text-tertiary)]">Agent not found</p>;

  const config = agent.config as Record<string, unknown>;
  const modelInfo = getAgentModelInfo(config);

  return (
    <div>
      <div className="flex items-center justify-between mb-8">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="font-display text-3xl font-normal tracking-tight text-[var(--color-text-primary)]">
              {agent.name}
            </h1>
            <div className="flex items-center gap-2">
              {modelInfo && (
                <span
                  className={`border px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${getAgentModelBadgeClasses(modelInfo.tone)}`}
                >
                  {modelInfo.label}
                </span>
              )}
              <span
                className={`border border-current/40 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.12em] ${agent.paused ? 'text-[var(--color-warning)]' : 'text-[var(--color-success)]'}`}
              >
                {agent.paused ? 'Paused' : 'Active'}
              </span>
            </div>
          </div>
          <p className="text-[var(--color-text-secondary)] mt-1">
            {agent.description}
          </p>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 mb-8 border-b border-ops-border">
        {(['preview', 'config', 'schedules'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2.5 text-sm border-b-2 transition-colors ${
              tab === t
                ? 'border-[var(--color-accent)] text-[var(--color-text-primary)]'
                : 'border-transparent text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]'
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      {tab === 'preview' &&
        (pluginFilesLoading && !pluginFiles ? (
          <div className="bg-ops-surface border border-ops-border rounded-card p-5 text-sm text-[var(--color-text-tertiary)]">
            Loading workflow files...
          </div>
        ) : (
          <PluginPreview
            agentYaml={pluginFiles?.agent_yaml || ''}
            files={pluginFiles?.files || {}}
            emptyMessage="This agent has no workflow files available yet."
          />
        ))}

      {tab === 'config' && (
        <div className="bg-ops-surface border border-ops-border rounded-card p-5">
          <SyntaxCode
            code={JSON.stringify(config, null, 2)}
            language="json"
            className="max-h-[600px] overflow-auto text-sm leading-relaxed"
          />
        </div>
      )}

      {tab === 'schedules' && (
        <div className="space-y-3">
          {((config.schedules as Array<Record<string, unknown>>) || []).map(
            (sched, i) => (
              <div
                key={i}
                className="bg-ops-surface border border-ops-border rounded-card p-5"
              >
                <h3 className="font-medium text-[var(--color-text-primary)]">
                  {sched.name as string}
                </h3>
                <p className="text-sm text-[var(--color-text-secondary)] mt-1">
                  Cron:{' '}
                  <span className="font-mono text-[var(--color-accent)]">
                    {sched.cron as string}
                  </span>
                </p>
                <p className="text-sm text-[var(--color-text-secondary)]">
                  {sched.prompt as string}
                </p>
              </div>
            ),
          )}
          {!((config.schedules as unknown[]) || []).length && (
            <p className="text-[var(--color-text-tertiary)]">
              No schedules configured
            </p>
          )}
        </div>
      )}
    </div>
  );
}
