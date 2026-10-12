'use client';

import { RefreshCw } from 'lucide-react';
import { useParams } from 'next/navigation';
import { useEffect, useState } from 'react';
import {
  EMPTY_KNOWLEDGE_SOURCE_FORM,
  KnowledgeSourceForm,
  sourceForm,
  sourcePayload,
} from '@/components/knowledge-source-form';
import {
  apiFetch,
  type BackgroundJobRun,
  type ConfluenceConnection,
  type GitHubConnection,
  type KnowledgeSource,
  type KnowledgeSourceVersion,
  type PlatformBackgroundJobs,
} from '@/lib/api';

export default function KnowledgeSourceDetailPage() {
  const params = useParams();
  const rawId = params?.sourceId;
  const sourceId = Array.isArray(rawId) ? rawId[0] : rawId || '';
  const [source, setSource] = useState<KnowledgeSource | null>(null);
  const [form, setForm] = useState(EMPTY_KNOWLEDGE_SOURCE_FORM);
  const [versions, setVersions] = useState<KnowledgeSourceVersion[]>([]);
  const [runs, setRuns] = useState<BackgroundJobRun[]>([]);
  const [connections, setConnections] = useState<GitHubConnection[]>([]);
  const [confluenceConnections, setConfluenceConnections] = useState<
    ConfluenceConnection[]
  >([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const currentVersion = versions.find(
    (version) => version.id === source?.current_successful_version_id,
  );

  const syncActive = runs.some(
    (run) => run.status === 'queued' || run.status === 'running',
  );

  async function load(resetForm = true) {
    if (!sourceId) return;
    try {
      const [
        item,
        sourceVersions,
        jobs,
        configuredConnections,
        wikiConnections,
      ] = await Promise.all([
        apiFetch<KnowledgeSource>(
          `/api/platform/knowledge-sources/${sourceId}`,
        ),
        apiFetch<KnowledgeSourceVersion[]>(
          `/api/platform/knowledge-sources/${sourceId}/versions`,
        ),
        apiFetch<PlatformBackgroundJobs>(
          `/api/platform/background-jobs?knowledge_source_id=${sourceId}&limit=20&offset=0`,
        ),
        apiFetch<GitHubConnection[]>(
          '/api/platform/knowledge-sources/github-connections',
        ),
        apiFetch<ConfluenceConnection[]>(
          '/api/platform/knowledge-sources/confluence-connections',
        ),
      ]);
      setSource(item);
      setVersions(sourceVersions);
      setRuns(jobs.items);
      setConnections(configuredConnections);
      setConfluenceConnections(wikiConnections);
      if (resetForm) setForm(sourceForm(item));
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Failed to load source',
      );
    }
  }
  useEffect(() => {
    load();
  }, [sourceId]);

  useEffect(() => {
    if (!syncActive) return;
    const timer = setInterval(() => load(false), 5000);
    return () => clearInterval(timer);
  }, [sourceId, syncActive]);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/platform/knowledge-sources/${sourceId}`, {
        method: 'PUT',
        body: JSON.stringify(sourcePayload(form)),
      });
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Save failed');
    } finally {
      setBusy(false);
    }
  }
  async function sync() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch(`/api/platform/knowledge-sources/${sourceId}/sync`, {
        method: 'POST',
      });
      await load();
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Sync request failed',
      );
    } finally {
      setBusy(false);
    }
  }

  if (!source)
    return (
      <p className="text-sm text-[var(--color-text-tertiary)]">
        {error || 'Loading source...'}
      </p>
    );
  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-normal text-[var(--color-text-primary)]">
            {source.display_name}
          </h1>
          <p className="mt-2 break-words text-sm text-[var(--color-text-tertiary)]">
            {source.canonical_alias} ·{' '}
            {source.source_kind === 'github'
              ? 'GitHub / Code graph'
              : 'Confluence / Hybrid search'}
            {currentVersion
              ? ` · Current index: ${currentVersion.source_revision?.slice(0, 12) || 'Unknown revision'}`
              : ' · No promoted index yet'}
          </p>
        </div>
        <button
          type="button"
          disabled={busy || !source.enabled || syncActive}
          title={
            !source.enabled
              ? 'Enable the source before syncing'
              : syncActive
                ? 'A sync is already active'
                : 'Queue source sync'
          }
          onClick={sync}
          className="inline-flex shrink-0 items-center gap-2 border border-ops-border bg-ops-surface px-4 py-2 text-sm disabled:opacity-50"
        >
          <RefreshCw size={16} />
          {syncActive ? 'Sync active' : 'Queue sync'}
        </button>
      </header>
      {error ? (
        <p className="text-sm text-[var(--color-error)]">{error}</p>
      ) : null}
      {source.serving_suspended_at ? (
        <p
          role="alert"
          className="break-words border-l-2 border-[var(--color-warning)] pl-3 text-sm text-[var(--color-warning)]"
        >
          Serving suspended:{' '}
          {source.serving_suspension_reason || 'A successful sync is required'}
        </p>
      ) : null}
      {!source.enabled ? (
        <p className="text-sm text-[var(--color-warning)]">Source disabled</p>
      ) : null}
      {currentVersion ? (
        <section>
          <h2 className="mb-3 text-lg font-medium">Current version</h2>
          <VersionMetrics version={currentVersion} />
        </section>
      ) : null}
      <section>
        <h2 className="mb-3 text-lg font-medium">Configuration</h2>
        <KnowledgeSourceForm
          form={form}
          setForm={setForm}
          onSubmit={save}
          submitLabel={busy ? 'Saving...' : 'Save changes'}
          connections={connections}
          confluenceConnections={confluenceConnections}
          editing
          busy={busy}
        />
      </section>
      <section>
        <h2 className="mb-3 text-lg font-medium">Sync history</h2>
        <div className="divide-y divide-ops-border border-y border-ops-border">
          {runs.map((run) => {
            const version = versions.find(
              (item) => item.id === run.knowledge_source_version_id,
            );
            return (
              <div
                key={run.id}
                className="grid gap-2 py-4 text-sm sm:grid-cols-[1fr_auto]"
              >
                <div>
                  <span className="font-medium capitalize">{run.trigger}</span>
                  <span className="ml-3 text-[var(--color-text-tertiary)]">
                    {new Date(run.started_at).toLocaleString()}
                  </span>
                </div>
                <div>
                  {run.status} ·{' '}
                  {run.duration_sec === null
                    ? 'pending'
                    : `${run.duration_sec.toFixed(1)}s`}
                </div>
                {version ? (
                  <div className="sm:col-span-2">
                    <VersionMetrics version={version} />
                  </div>
                ) : null}
                {run.error ? (
                  <p className="text-[var(--color-error)] sm:col-span-2">
                    {run.error}
                  </p>
                ) : null}
                {run.warnings.length > 0 ? (
                  <p className="break-words text-[var(--color-warning)] sm:col-span-2">
                    {run.warnings.join('; ')}
                  </p>
                ) : null}
              </div>
            );
          })}
          {runs.length === 0 ? (
            <p className="py-6 text-sm text-[var(--color-text-tertiary)]">
              No sync attempts yet.
            </p>
          ) : null}
        </div>
      </section>
      <section>
        <h2 className="mb-3 text-lg font-medium">Version history</h2>
        <div className="divide-y divide-ops-border border-y border-ops-border">
          {versions.map((version) => (
            <article key={version.id} className="space-y-2 py-4">
              <p className="text-sm">
                {new Date(version.created_at).toLocaleString()}
                {version.id === source.current_successful_version_id
                  ? ' · Current'
                  : ''}
              </p>
              <VersionMetrics version={version} />
              {version.error ? (
                <p className="break-words text-sm text-[var(--color-error)]">
                  {version.error}
                </p>
              ) : null}
              {version.warnings.length ? (
                <p className="break-words text-xs text-[var(--color-warning)]">
                  {version.warnings.map(String).join('; ')}
                </p>
              ) : null}
            </article>
          ))}
        </div>
      </section>
    </div>
  );
}

function VersionMetrics({ version }: { version: KnowledgeSourceVersion }) {
  return (
    <div className="space-y-2 text-xs text-[var(--color-text-secondary)]">
      <p className="break-all font-mono">
        {version.source_revision || version.commit_sha || 'Unknown revision'} ·{' '}
        {version.index_kind === 'code_graph' ? 'Graphify' : 'Hybrid index'}{' '}
        {version.indexer_version || version.graphify_version}
      </p>
      <p className="break-all font-mono">
        Config: {version.index_config_hash || 'Unavailable'}
      </p>
      {version.index_kind === 'code_graph' ? (
        <p>
          {version.file_count} files · {version.node_count} nodes ·{' '}
          {version.edge_count} edges
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          {Object.entries(version.stats)
            .filter(
              ([, value]) =>
                typeof value === 'number' || typeof value === 'string',
            )
            .map(([name, value]) => (
              <div key={name} className="min-w-0">
                <dt className="break-words capitalize">
                  {name.replaceAll('_', ' ')}
                </dt>
                <dd className="break-words font-mono text-[var(--color-text-primary)]">
                  {String(value)}
                </dd>
              </div>
            ))}
        </dl>
      )}
    </div>
  );
}
