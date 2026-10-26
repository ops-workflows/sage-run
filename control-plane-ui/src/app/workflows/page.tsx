'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import {
  type Agent,
  apiFetch,
  type DeploymentStatus,
  type WorkflowRepoStatus,
  type WorkflowRepoVersion,
} from '@/lib/api';
import { WorkflowsListSection } from '@/components/workflows-list-section';
import { ExpandableMeta } from '@/components/expandable-meta';

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [togglingAgent, setTogglingAgent] = useState<string | null>(null);

  useEffect(() => {
    loadAgents();
  }, []);

  async function loadAgents() {
    setLoading(true);
    try {
      const data = await apiFetch<Agent[]>('/api/agents');
      setAgents(data);
    } catch (e) {
      console.error('Failed to load agents:', e);
    }
    setLoading(false);
  }

  async function toggleAgentPaused(agent: Agent) {
    setTogglingAgent(agent.id);
    try {
      const updated = await apiFetch<Agent>(
        `/api/agents/${agent.name}/${agent.paused ? 'resume' : 'pause'}`,
        { method: 'POST' },
      );
      setAgents((current) =>
        current.map((entry) => (entry.id === updated.id ? updated : entry)),
      );
    } catch (e) {
      console.error(`Failed to ${agent.paused ? 'resume' : 'pause'} agent:`, e);
    } finally {
      setTogglingAgent(null);
    }
  }

  const totalSchedules = agents.reduce((sum, agent) => {
    const config = agent.config as Record<string, unknown>;
    return (
      sum + ((config.schedules as Array<unknown> | undefined) || []).length
    );
  }, 0);
  const activeCount = agents.filter((a) => !a.paused).length;

  return (
    <div className="space-y-10">
      <section className="space-y-4 pt-4">
        <div className="flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-2xl space-y-4">
            <h1 className="font-display text-4xl font-normal leading-[1.15] tracking-tight text-[var(--color-text-primary)]">
              Workflows
            </h1>
          </div>
        </div>
        <div className="mt-6 grid gap-3 sm:grid-cols-3">
          <StatCard label="Total" value={agents.length} />
          <StatCard label="Active" value={activeCount} />
          <StatCard label="Schedules" value={totalSchedules} />
        </div>
      </section>
      <WorkflowRepoDeploySection />
      <WorkflowsListSection
        agents={agents}
        loading={loading}
        togglingAgent={togglingAgent}
        onToggleAgentPaused={toggleAgentPaused}
      />
    </div>
  );
}

function WorkflowRepoDeploySection() {
  const [status, setStatus] = useState<WorkflowRepoStatus | null>(null);
  const [versions, setVersions] = useState<WorkflowRepoVersion[]>([]);
  const [deployment, setDeployment] = useState<DeploymentStatus | null>(null);
  const [selectedRef, setSelectedRef] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tagsFetchedAt = useRef(0);

  const load = useCallback(async () => {
    try {
      const repo = await apiFetch<WorkflowRepoStatus>(
        '/api/platform/workflow-repo',
      );
      setStatus(repo);
      setSelectedRef(
        (current) =>
          current ||
          (repo.source_mode === 'local'
            ? 'working-tree'
            : repo.default_ref || 'main'),
      );
      if (repo.deployment_enabled) {
        const latest = await apiFetch<{
          deployment: DeploymentStatus | null;
        }>('/api/platform/deployments');
        setDeployment(latest.deployment);
        if (Date.now() - tagsFetchedAt.current > 60000) {
          setVersions(
            await apiFetch<WorkflowRepoVersion[]>(
              '/api/platform/workflow-repo/versions',
            ),
          );
          tagsFetchedAt.current = Date.now();
        }
      }
      setError(null);
    } catch (loadError) {
      setError(
        loadError instanceof Error
          ? loadError.message
          : 'Failed to load deployment status',
      );
    }
  }, []);

  useEffect(() => {
    void load();
    // Poll even after completion to pick up deployments started from another browser.
    const timer = window.setInterval(() => void load(), 5000);
    return () => window.clearInterval(timer);
  }, [load]);

  const busy =
    submitting ||
    deployment?.status === 'pending' ||
    deployment?.status === 'running';
  const remote = status?.source_mode === 'remote';

  async function handleDeploy() {
    if (!status || !selectedRef) return;
    const explanation = remote
      ? `Deploy ${selectedRef}? A production backup will be verified first (keep 3 deployment copies). Changed services may restart.`
      : 'Deploy the current working tree? Changed services may restart.';
    if (!window.confirm(explanation)) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await apiFetch<DeploymentStatus>(
        '/api/platform/deployments',
        {
          method: 'POST',
          body: JSON.stringify({ ref: selectedRef }),
        },
      );
      setDeployment(created);
    } catch (deployError) {
      setError(
        deployError instanceof Error
          ? deployError.message
          : 'Failed to start deployment',
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="border-t border-ops-border pt-8">
      <h2 className="text-lg font-medium text-[var(--color-text-primary)]">
        Deploy
      </h2>
      <p className="mt-1 text-sm text-[var(--color-text-tertiary)]">
        Deploy workflow bundles, configuration and MCPs from one checkout.
        Platform version upgrades use the CLI.
      </p>
      {error ? (
        <p role="alert" className="mt-4 text-sm text-[var(--color-error)]">
          {error}
        </p>
      ) : null}
      {!status ? (
        <p className="mt-4 text-sm text-[var(--color-text-tertiary)]">
          Loading deployment status...
        </p>
      ) : (
        <article className="mt-4 rounded-card border border-ops-border bg-ops-surface p-5">
          <div className="grid gap-3 md:grid-cols-3">
            <ExpandableMeta
              label={remote ? 'Repository' : 'Working tree'}
              value={
                status.source_url || status.source_path || 'Local checkout'
              }
            />
            <ExpandableMeta
              label="Active commit"
              value={status.last_synced_commit || 'Not deployed'}
            />
            <ExpandableMeta
              label="Platform version"
              value={status.platform_version}
            />
          </div>
          <div className="mt-5 flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm text-[var(--color-text-secondary)]">
              Workflow ref
              <select
                value={selectedRef}
                onChange={(event) => setSelectedRef(event.target.value)}
                disabled={busy || !status.deployment_enabled}
                className="rounded-btn border border-ops-border bg-ops-surface-raised px-3 py-2 text-sm text-[var(--color-text-primary)]"
              >
                {remote ? (
                  <>
                    <option value="main">main</option>
                    {versions
                      .filter((tag) => tag.name.startsWith('v'))
                      .map((tag) => (
                        <option key={tag.name} value={tag.name}>
                          {tag.name}
                        </option>
                      ))}
                  </>
                ) : (
                  <option value="working-tree">Current working tree</option>
                )}
              </select>
            </label>
            <button
              type="button"
              onClick={handleDeploy}
              disabled={busy || !status.deployment_enabled || !selectedRef}
              className="rounded-btn border border-ops-border bg-ops-surface px-4 py-2 text-sm text-[var(--color-text-secondary)] disabled:opacity-50"
            >
              {busy ? 'Deploying...' : 'Deploy now'}
            </button>
          </div>
          {!status.deployment_enabled ? (
            <p className="mt-3 text-sm text-[var(--color-text-tertiary)]">
              Deployment Jobs are not enabled on this instance. Upgrade using
              the CLI first.
            </p>
          ) : null}
          {deployment ? (
            <div className="mt-5 space-y-3" aria-live="polite">
              <p
                className={`text-sm ${deployment.status === 'failed' ? 'text-[var(--color-error)]' : 'text-[var(--color-text-secondary)]'}`}
              >
                {deployment.status} · {deployment.phase} · {deployment.ref}
              </p>
              {deployment.started_at ? (
                <ExpandableMeta
                  label="Started"
                  value={new Date(deployment.started_at).toLocaleString()}
                />
              ) : null}
              {deployment.finished_at ? (
                <ExpandableMeta
                  label="Finished"
                  value={new Date(deployment.finished_at).toLocaleString()}
                />
              ) : null}
              <ExpandableMeta label="Deployment Job" value={deployment.id} />
              {deployment.commit ? (
                <ExpandableMeta
                  label="Requested commit"
                  value={deployment.commit}
                />
              ) : null}
              {deployment.error ? (
                <p role="alert" className="text-sm text-[var(--color-error)]">
                  {deployment.error}
                </p>
              ) : null}
              <details open={busy || deployment.status === 'failed'}>
                <summary className="cursor-pointer text-sm text-[var(--color-text-secondary)]">
                  Deployment logs
                </summary>
                <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-card bg-ops-surface-raised p-3 text-xs text-[var(--color-text-secondary)]">
                  {deployment.logs || 'Waiting for deployment logs...'}
                </pre>
              </details>
            </div>
          ) : null}
          {status.last_sync_error ? (
            <p className="mt-3 text-sm text-[var(--color-error)]">
              {status.last_sync_error}
            </p>
          ) : null}
          {Object.entries(status.bundle_errors).map(([workflow, message]) => (
            <p
              key={workflow}
              className="mt-2 text-sm text-[var(--color-error)]"
            >
              {workflow}: {message}
            </p>
          ))}
        </article>
      )}
    </section>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="rounded-card border border-ops-border bg-ops-surface px-4 py-4">
      <div className="text-[10px] uppercase tracking-[0.18em] text-[var(--color-text-tertiary)]">
        {label}
      </div>
      <div className="mt-2 text-2xl font-medium text-[var(--color-text-primary)]">
        {value}
      </div>
    </div>
  );
}
