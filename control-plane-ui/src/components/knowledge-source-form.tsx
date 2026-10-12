'use client';

import { Save } from 'lucide-react';
import {
  type ConfluenceConnection,
  type GitHubConnection,
  type KnowledgeSource,
  type KnowledgeSourceWrite,
  knowledgeSourcePayload,
} from '@/lib/api';

export interface KnowledgeSourceFormValue {
  source_kind: 'github' | 'confluence';
  canonical_alias: string;
  display_name: string;
  repository: string;
  default_ref: string;
  include_paths: string;
  exclude_paths: string;
  root_pages: string;
  include_descendants: boolean;
  scrub_patterns: string;
  lexical_config: 'simple' | 'english';
  credential_ref: string;
  schedule: string;
  interval_sec: string;
  enabled: boolean;
}

export const EMPTY_KNOWLEDGE_SOURCE_FORM: KnowledgeSourceFormValue = {
  source_kind: 'github',
  canonical_alias: '',
  display_name: '',
  repository: '',
  default_ref: 'main',
  include_paths: '',
  exclude_paths: '',
  root_pages: '',
  include_descendants: true,
  scrub_patterns: '',
  lexical_config: 'simple',
  credential_ref: '',
  schedule: 'daily',
  interval_sec: '86400',
  enabled: true,
};

export function sourcePayload(
  form: KnowledgeSourceFormValue,
): KnowledgeSourceWrite {
  const intervals: Record<string, number> = {
    hourly: 3600,
    daily: 86400,
    weekly: 604800,
  };
  const intervalSec =
    form.schedule === 'custom'
      ? Number(form.interval_sec)
      : intervals[form.schedule];
  const common = {
    canonical_alias: form.canonical_alias || undefined,
    display_name: form.display_name || undefined,
    credential_ref: form.credential_ref,
    sync_policy: intervalSec ? { interval_sec: intervalSec } : {},
    enabled: form.enabled,
  };
  if (form.source_kind === 'confluence') {
    return {
      ...common,
      source_kind: 'confluence',
      index_kind: 'hybrid_vector',
      source_config: {
        root_pages: splitLines(form.root_pages),
        include_descendants: form.include_descendants,
        scrub_patterns: form.scrub_patterns
          .split(/\r?\n/)
          .filter((pattern) => pattern.trim()),
        body_format: 'storage',
        lexical_config: form.lexical_config,
      },
    };
  }
  return {
    ...common,
    source_kind: 'github',
    index_kind: 'code_graph',
    repository: form.repository,
    default_ref: form.default_ref,
    include_paths: splitLines(form.include_paths),
    exclude_paths: splitLines(form.exclude_paths),
  };
}

export function sourceForm(source: KnowledgeSource): KnowledgeSourceFormValue {
  const payload = knowledgeSourcePayload(source);
  const interval = source.sync_policy.interval_sec;
  return {
    ...EMPTY_KNOWLEDGE_SOURCE_FORM,
    source_kind: source.source_kind,
    canonical_alias: source.canonical_alias,
    display_name: source.display_name,
    credential_ref: source.credential_ref || '',
    schedule:
      interval === 3600
        ? 'hourly'
        : interval === 86400
          ? 'daily'
          : interval === 604800
            ? 'weekly'
            : interval
              ? 'custom'
              : '',
    interval_sec: typeof interval === 'number' ? String(interval) : '86400',
    enabled: source.enabled,
    ...(payload.source_kind === 'github'
      ? {
          repository: payload.repository,
          default_ref: payload.default_ref,
          include_paths: payload.include_paths.join('\n'),
          exclude_paths: payload.exclude_paths.join('\n'),
        }
      : {
          root_pages:
            source.source_kind === 'confluence'
              ? source.source_config.root_page_ids.join('\n')
              : '',
          lexical_config: payload.source_config.lexical_config,
          include_descendants: payload.source_config.include_descendants,
          scrub_patterns: payload.source_config.scrub_patterns.join('\n'),
        }),
  };
}

export function KnowledgeSourceForm({
  form,
  setForm,
  onSubmit,
  submitLabel,
  connections,
  confluenceConnections,
  editing = false,
  busy = false,
}: {
  form: KnowledgeSourceFormValue;
  setForm: React.Dispatch<React.SetStateAction<KnowledgeSourceFormValue>>;
  onSubmit: (event: React.FormEvent) => void;
  submitLabel: string;
  connections: GitHubConnection[];
  confluenceConnections: ConfluenceConnection[];
  editing?: boolean;
  busy?: boolean;
}) {
  const field = (
    name:
      | 'repository'
      | 'default_ref'
      | 'canonical_alias'
      | 'display_name'
      | 'interval_sec',
  ) => ({
    value: form[name],
    onChange: (event: React.ChangeEvent<HTMLInputElement>) =>
      setForm((current) => ({ ...current, [name]: event.target.value })),
  });
  const multilineField = (
    name: 'include_paths' | 'exclude_paths' | 'root_pages' | 'scrub_patterns',
  ) => ({
    value: form[name],
    onChange: (event: React.ChangeEvent<HTMLTextAreaElement>) =>
      setForm((current) => ({ ...current, [name]: event.target.value })),
  });
  const selectField = (name: 'credential_ref' | 'schedule') => ({
    value: form[name],
    onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
      setForm((current) => ({ ...current, [name]: event.target.value })),
  });
  return (
    <form
      onSubmit={onSubmit}
      className="grid gap-5 border-y border-ops-border py-5 md:grid-cols-2"
    >
      <Select
        label="Source kind"
        value={form.source_kind}
        disabled={editing || busy}
        onChange={(event) =>
          setForm((current) => ({
            ...current,
            source_kind:
              event.target.value === 'confluence' ? 'confluence' : 'github',
            credential_ref: '',
          }))
        }
      >
        <option value="github">GitHub / Code graph</option>
        <option value="confluence">Confluence / Hybrid search</option>
      </Select>
      <Input
        label="Alias"
        required={form.source_kind === 'confluence'}
        readOnly={editing}
        maxLength={128}
        pattern={'[A-Za-z0-9][A-Za-z0-9_\\-]{0,127}'}
        {...field('canonical_alias')}
      />
      <Input label="Display name" maxLength={200} {...field('display_name')} />
      {form.source_kind === 'github' ? (
        <>
          <Input
            label="Repository (organization/repository)"
            required
            {...field('repository')}
          />
          <Select
            label="GitHub connection"
            required
            {...selectField('credential_ref')}
          >
            <option value="">Select connection</option>
            {connections.map((connection) => (
              <option key={connection.name} value={connection.name}>
                {connection.name} ({connection.web_base_url})
              </option>
            ))}
          </Select>
          <Input label="Default ref" required {...field('default_ref')} />
          <Textarea
            label="Include globs, one per line"
            {...multilineField('include_paths')}
          />
          <Textarea
            label="Exclude globs, one per line"
            {...multilineField('exclude_paths')}
          />
        </>
      ) : (
        <>
          <Select
            label="Confluence connection"
            required
            {...selectField('credential_ref')}
          >
            <option value="">Select connection</option>
            {confluenceConnections.map((connection) => (
              <option key={connection.name} value={connection.name}>
                {connection.name} ({connection.base_url})
              </option>
            ))}
          </Select>
          <Textarea
            label="Root page URLs or numeric IDs, one per line"
            required
            {...multilineField('root_pages')}
          />
          <Select
            label="Lexical language"
            value={form.lexical_config}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                lexical_config:
                  event.target.value === 'english' ? 'english' : 'simple',
              }))
            }
          >
            <option value="simple">Simple (multilingual)</option>
            <option value="english">English</option>
          </Select>
          <Textarea
            label="Body scrub regexes, one per line"
            {...multilineField('scrub_patterns')}
          />
        </>
      )}
      {form.source_kind === 'confluence' ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={form.include_descendants}
            onChange={(event) =>
              setForm((current) => ({
                ...current,
                include_descendants: event.target.checked,
              }))
            }
          />
          Include subpages
        </label>
      ) : null}
      <Select label="Sync schedule" {...selectField('schedule')}>
        <option value="">Manual only</option>
        <option value="hourly">Hourly</option>
        <option value="daily">Daily</option>
        <option value="weekly">Weekly</option>
        <option value="custom">Custom interval</option>
      </Select>
      {form.schedule === 'custom' ? (
        <Input
          label="Interval (seconds)"
          type="number"
          min={1}
          step={1}
          required
          {...field('interval_sec')}
        />
      ) : null}
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={form.enabled}
          onChange={(event) =>
            setForm((current) => ({
              ...current,
              enabled: event.target.checked,
            }))
          }
        />
        Enabled
      </label>
      <div className="flex items-end gap-3 md:col-span-2">
        <button
          type="submit"
          disabled={
            busy ||
            (form.source_kind === 'confluence'
              ? confluenceConnections.length === 0
              : connections.length === 0)
          }
          className="inline-flex items-center gap-2 rounded-btn bg-[var(--color-accent)] px-4 py-2.5 text-sm font-medium text-white shadow-sm transition-colors hover:bg-[var(--color-accent-hover)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)] focus:ring-offset-2 focus:ring-offset-ops-surface disabled:opacity-50"
        >
          <Save size={16} />
          {submitLabel}
        </button>
        {(
          form.source_kind === 'confluence'
            ? confluenceConnections.length === 0
            : connections.length === 0
        ) ? (
          <p role="alert" className="text-sm text-[var(--color-warning)]">
            No configured connection. Contact the platform administrator.
          </p>
        ) : null}
      </div>
    </form>
  );
}

function Select({
  label,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement> & { label: string }) {
  return (
    <label className="space-y-1.5 text-xs font-medium text-[var(--color-text-secondary)]">
      <span>{label}</span>
      <select
        {...props}
        className="w-full appearance-none rounded-btn border border-ops-border bg-ops-bg px-3 py-2.5 text-sm text-[var(--color-text-primary)] shadow-sm outline-none transition-colors hover:border-[var(--color-text-tertiary)] focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]/20"
      >
        {children}
      </select>
    </label>
  );
}

function Textarea({
  label,
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement> & { label: string }) {
  return (
    <label className="space-y-1.5 text-xs font-medium text-[var(--color-text-secondary)]">
      <span>{label}</span>
      <textarea
        {...props}
        rows={3}
        className="w-full resize-y rounded-btn border border-ops-border bg-ops-bg px-3 py-2.5 text-sm text-[var(--color-text-primary)] shadow-sm outline-none transition-colors placeholder:text-[var(--color-text-tertiary)] hover:border-[var(--color-text-tertiary)] focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]/20"
      />
    </label>
  );
}

function Input({
  label,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className="space-y-1.5 text-xs font-medium text-[var(--color-text-secondary)]">
      <span>{label}</span>
      <input
        {...props}
        className="w-full rounded-btn border border-ops-border bg-ops-bg px-3 py-2.5 text-sm text-[var(--color-text-primary)] shadow-sm outline-none transition-colors placeholder:text-[var(--color-text-tertiary)] hover:border-[var(--color-text-tertiary)] focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]/20"
      />
    </label>
  );
}

function splitLines(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function repositoryName(repository: string) {
  return (
    repository
      .replace(/\.git$/, '')
      .split('/')
      .pop() || repository
  );
}
