'use client';

import { BookOpenText, Plus, X } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useState } from 'react';
import {
  EMPTY_KNOWLEDGE_SOURCE_FORM,
  KnowledgeSourceForm,
  sourcePayload,
} from '@/components/knowledge-source-form';
import {
  apiFetch,
  type ConfluenceConnection,
  type GitHubConnection,
  type KnowledgeSource,
  knowledgeSourcePayload,
} from '@/lib/api';

export default function KnowledgeSourcesPage() {
  const [sources, setSources] = useState<KnowledgeSource[]>([]);
  const [connections, setConnections] = useState<GitHubConnection[]>([]);
  const [confluenceConnections, setConfluenceConnections] = useState<
    ConfluenceConnection[]
  >([]);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY_KNOWLEDGE_SOURCE_FORM);
  const [showForm, setShowForm] = useState(false);
  const [togglingId, setTogglingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function load() {
    try {
      const [items, configuredConnections, wikiConnections] = await Promise.all(
        [
          apiFetch<KnowledgeSource[]>('/api/platform/knowledge-sources'),
          apiFetch<GitHubConnection[]>(
            '/api/platform/knowledge-sources/github-connections',
          ),
          apiFetch<ConfluenceConnection[]>(
            '/api/platform/knowledge-sources/confluence-connections',
          ),
        ],
      );
      setSources(items);
      setConnections(configuredConnections);
      setConfluenceConnections(wikiConnections);
    } catch (caught) {
      setError(
        caught instanceof Error ? caught.message : 'Failed to load sources',
      );
    }
  }
  useEffect(() => {
    load();
  }, []);

  async function createSource(event: React.FormEvent) {
    event.preventDefault();
    setCreating(true);
    setError(null);
    try {
      await apiFetch('/api/platform/knowledge-sources', {
        method: 'POST',
        body: JSON.stringify(sourcePayload(form)),
      });
      setForm(EMPTY_KNOWLEDGE_SOURCE_FORM);
      setShowForm(false);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Create failed');
    } finally {
      setCreating(false);
    }
  }

  async function toggleSource(source: KnowledgeSource) {
    setTogglingId(source.id);
    setError(null);
    try {
      const updated = await apiFetch<KnowledgeSource>(
        `/api/platform/knowledge-sources/${source.id}`,
        {
          method: 'PUT',
          body: JSON.stringify({
            ...knowledgeSourcePayload(source),
            enabled: !source.enabled,
          }),
        },
      );
      setSources((current) =>
        current.map((item) => (item.id === updated.id ? updated : item)),
      );
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Update failed');
    } finally {
      setTogglingId(null);
    }
  }

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <h1 className="font-display text-4xl font-normal text-[var(--color-text-primary)]">
            Knowledge Sources
          </h1>
          <p className="mt-2 text-sm text-[var(--color-text-tertiary)]">
            {sources.length} registered sources
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm(!showForm)}
          className="inline-flex items-center gap-2 border border-ops-border bg-ops-surface px-4 py-2 text-sm text-[var(--color-text-primary)]"
        >
          {showForm ? <X size={16} /> : <Plus size={16} />}
          {showForm ? 'Close' : 'Add source'}
        </button>
      </header>
      {error ? (
        <p className="text-sm text-[var(--color-error)]">{error}</p>
      ) : null}
      {showForm ? (
        <KnowledgeSourceForm
          form={form}
          setForm={setForm}
          onSubmit={createSource}
          submitLabel={creating ? 'Creating...' : 'Create source'}
          connections={connections}
          confluenceConnections={confluenceConnections}
          busy={creating}
        />
      ) : null}
      <section className="border-t border-ops-border">
        {sources.map((source) => (
          <article
            key={source.id}
            className="grid gap-4 border-b border-ops-border py-5 sm:grid-cols-[1fr_auto] sm:px-3"
          >
            <Link
              href={`/knowledge-sources/${source.id}`}
              className="flex min-w-0 items-start gap-3 rounded-btn p-1 transition-colors hover:bg-[var(--color-surface-raised)]"
            >
              <BookOpenText
                className="mt-1 shrink-0 text-[var(--color-accent)]"
                size={18}
              />
              <div className="min-w-0">
                <h2 className="font-medium text-[var(--color-text-primary)]">
                  {source.display_name}
                </h2>
                <p className="break-words font-mono text-xs text-[var(--color-text-tertiary)]">
                  {source.canonical_alias}
                </p>
                <p className="mt-1 break-words text-xs text-[var(--color-text-secondary)]">
                  {source.source_kind === 'github'
                    ? 'GitHub / Code graph'
                    : 'Confluence / Hybrid search'}
                  {' · '}
                  {source.source_kind === 'github'
                    ? `${source.repository_url} · ${source.default_ref}`
                    : `${source.source_config.root_page_ids.length} roots · ${source.source_config.lexical_config}`}
                </p>
                {source.serving_suspended_at ? (
                  <p className="mt-2 break-words text-xs text-[var(--color-warning)]">
                    {source.serving_suspension_reason || 'Serving suspended'}
                  </p>
                ) : null}
              </div>
            </Link>
            <div className="flex flex-wrap items-center gap-3 text-xs">
              <button
                type="button"
                role="switch"
                aria-checked={source.enabled}
                aria-label={`${source.enabled ? 'Disable' : 'Enable'} ${source.display_name}`}
                disabled={togglingId === source.id}
                onClick={() => toggleSource(source)}
                className={`relative inline-flex h-7 w-12 shrink-0 items-center rounded-full transition-colors ${
                  source.enabled
                    ? 'bg-[var(--color-success)]'
                    : 'bg-[var(--color-border)]'
                } ${togglingId === source.id ? 'opacity-60' : ''}`}
              >
                <span
                  className={`inline-block h-5 w-5 rounded-full bg-white transition-transform ${
                    source.enabled ? 'translate-x-6' : 'translate-x-1'
                  }`}
                />
              </button>
              <span
                className={
                  source.enabled
                    ? 'text-[var(--color-success)]'
                    : 'text-[var(--color-warning)]'
                }
              >
                {source.enabled ? 'Enabled' : 'Disabled'}
              </span>
              <span className="text-[var(--color-text-tertiary)]">
                {source.serving_suspended_at
                  ? 'Suspended'
                  : !source.enabled
                    ? 'Not serving'
                    : source.current_successful_version_id
                      ? 'Ready'
                      : 'Not indexed'}
              </span>
            </div>
          </article>
        ))}
        {sources.length === 0 ? (
          <p className="py-10 text-sm text-[var(--color-text-tertiary)]">
            No Knowledge Sources registered.
          </p>
        ) : null}
      </section>
    </div>
  );
}
