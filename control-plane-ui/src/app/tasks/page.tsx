'use client';

import { useEffect, useState, useCallback, useRef } from 'react';
import {
  Cable,
  CalendarClock,
  Cloud,
  Filter,
  MessageCircle,
  Search,
  ServerCog,
  Webhook,
  X,
  type LucideIcon,
} from 'lucide-react';
import {
  apiFetch,
  type Task,
  type TaskArchiveResult,
  type TaskDeleteResult,
  type TaskListResult,
  type TaskResetResult,
} from '@/lib/api';

type StatusFilter =
  | 'all'
  | 'queued'
  | 'running'
  | 'waiting_approval'
  | 'waiting_user_input'
  | 'resume_pending'
  | 'succeeded'
  | 'failed'
  | 'lost'
  | 'timed_out';

const RERUNNABLE_STATUSES = new Set(['failed', 'lost', 'timed_out']);
const PAGE_SIZE = 50;

type TaskRefinements = {
  workflows: string[];
  origins: string[];
};

function formatDuration(durationSec: number | null): string {
  if (durationSec === null) {
    return '-';
  }

  if (durationSec < 60) {
    return `${Math.round(durationSec)}s`;
  }

  return `${(durationSec / 60).toFixed(1)}m`;
}

type Origin = { label: string; icon: LucideIcon };

const CHANNEL_DISPLAY: Record<string, Origin> = {
  salesforce: { label: 'Salesforce', icon: Cloud },
  servicenow: { label: 'ServiceNow', icon: ServerCog },
  mattermost: { label: 'Mattermost', icon: MessageCircle },
  message: { label: 'Message', icon: MessageCircle },
  schedule: { label: 'Schedule', icon: CalendarClock },
  'gcp-pubsub': { label: 'GCP Pub/Sub', icon: Cable },
  api: { label: 'API', icon: Webhook },
};

function deriveOrigin(task: Task): Origin {
  if (task.channel && CHANNEL_DISPLAY[task.channel]) {
    return CHANNEL_DISPLAY[task.channel];
  }
  if (task.channel) {
    return { label: task.channel, icon: Cable };
  }
  /* Fallback for rows without channel (pre-migration) */
  const meta = task.metadata as Record<string, unknown>;
  if (meta?.triggered_by === 'scheduler')
    return { label: 'Schedule', icon: CalendarClock };
  const source = meta?.source;
  if (typeof source === 'string') {
    const normalizedSource = source.toLowerCase();
    if (normalizedSource.includes('servicenow'))
      return { label: 'ServiceNow', icon: ServerCog };
    if (source.includes('sf-email') || source.includes('salesforce'))
      return { label: 'Salesforce', icon: Cloud };
    if (normalizedSource.includes('mattermost'))
      return { label: 'Mattermost', icon: MessageCircle };
    if (normalizedSource.includes('schedule'))
      return { label: 'Schedule', icon: CalendarClock };
    return { label: source, icon: Cable };
  }
  if (task.message_channel) return { label: 'Message', icon: MessageCircle };
  return { label: 'API', icon: Webhook };
}

function channelLabel(channel: string): string {
  return CHANNEL_DISPLAY[channel]?.label ?? channel;
}

export default function QueuePage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [refinements, setRefinements] = useState<TaskRefinements>({
    workflows: [],
    origins: [],
  });
  const [draftRefinements, setDraftRefinements] = useState<TaskRefinements>({
    workflows: [],
    origins: [],
  });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [workflowSearch, setWorkflowSearch] = useState('');
  const [includeArchived, setIncludeArchived] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const [offset, setOffset] = useState(0);
  const [total, setTotal] = useState(0);
  const [filterOptions, setFilterOptions] = useState<TaskRefinements>({
    workflows: [],
    origins: [],
  });
  const [loading, setLoading] = useState(true);
  const [actionError, setActionError] = useState<string | null>(null);
  const [rerunningTaskId, setRerunningTaskId] = useState<string | null>(null);
  const [deletingTaskId, setDeletingTaskId] = useState<string | null>(null);
  const [archivingTaskId, setArchivingTaskId] = useState<string | null>(null);
  const desktopFiltersRef = useRef<HTMLDivElement>(null);

  const fetchTasks = useCallback(() => {
    const params = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(offset),
    });
    if (filter !== 'all') params.set('status', filter);
    if (includeArchived) params.set('include_archived', 'true');
    refinements.workflows.forEach((workflow) => {
      params.append('workflow', workflow);
    });
    refinements.origins.forEach((origin) => {
      params.append('channel', origin);
    });
    apiFetch<TaskListResult>(`/api/tasks?${params.toString()}`)
      .then((result) => {
        setTasks(result.items);
        setTotal(result.total);
        setFilterOptions({
          workflows: result.workflows,
          origins: result.channels,
        });
      })
      .catch(console.error)
      .finally(() => setLoading(false));
  }, [filter, includeArchived, offset, refinements]);

  useEffect(() => {
    fetchTasks();
  }, [fetchTasks]);

  useEffect(() => {
    if (!autoRefresh) return;
    const interval = setInterval(fetchTasks, 5000);
    return () => clearInterval(interval);
  }, [autoRefresh, fetchTasks]);

  useEffect(() => {
    if (!filtersOpen) return;

    function closeFiltersOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') setFiltersOpen(false);
    }

    function closeFiltersOnOutsideClick(event: MouseEvent) {
      const popover = desktopFiltersRef.current;
      if (
        !popover ||
        popover.offsetParent === null ||
        popover.contains(event.target as Node)
      )
        return;
      setFiltersOpen(false);
    }

    document.addEventListener('keydown', closeFiltersOnEscape);
    document.addEventListener('mousedown', closeFiltersOnOutsideClick);
    return () => {
      document.removeEventListener('keydown', closeFiltersOnEscape);
      document.removeEventListener('mousedown', closeFiltersOnOutsideClick);
    };
  }, [filtersOpen]);

  const statusColor = (s: string) => {
    switch (s) {
      case 'queued':
        return 'bg-[var(--color-info-muted)] text-[var(--color-info)]';
      case 'running':
        return 'bg-[var(--color-warning-muted)] text-[var(--color-warning)]';
      case 'resume_pending':
        return 'bg-[var(--color-info-muted)] text-[var(--color-info)]';
      case 'waiting_approval':
      case 'waiting_user_input':
        return 'bg-[var(--color-warning-muted)] text-[var(--color-warning)]';
      case 'succeeded':
        return 'bg-[var(--color-success-muted)] text-[var(--color-success)]';
      case 'failed':
        return 'bg-[var(--color-error-muted)] text-[var(--color-error)]';
      case 'lost':
        return 'bg-[var(--color-border-subtle)] text-[var(--color-text-tertiary)]';
      case 'timed_out':
        return 'bg-[var(--color-warning-muted)] text-[var(--color-warning)]';
      default:
        return 'bg-[var(--color-border-subtle)] text-[var(--color-text-tertiary)]';
    }
  };

  const rerunTask = useCallback(
    async (task: Task) => {
      setActionError(null);
      setRerunningTaskId(task.id);
      try {
        await apiFetch<TaskResetResult>(`/api/tasks/${task.id}/rerun`, {
          method: 'POST',
        });
        fetchTasks();
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : 'Failed to rerun task',
        );
      } finally {
        setRerunningTaskId(null);
      }
    },
    [fetchTasks],
  );

  const deleteTask = useCallback(
    async (task: Task) => {
      if (
        !window.confirm(
          `Delete task ${task.id.slice(0, 8)} and its related session data?`,
        )
      ) {
        return;
      }

      setActionError(null);
      setDeletingTaskId(task.id);
      try {
        await apiFetch<TaskDeleteResult>(`/api/tasks/${task.id}`, {
          method: 'DELETE',
        });
        fetchTasks();
      } catch (error) {
        setActionError(
          error instanceof Error ? error.message : 'Failed to delete task',
        );
      } finally {
        setDeletingTaskId(null);
      }
    },
    [fetchTasks],
  );

  const archiveTask = useCallback(
    async (task: Task) => {
      setActionError(null);
      setArchivingTaskId(task.id);
      try {
        const action = task.archived_at ? 'unarchive' : 'archive';
        await apiFetch<TaskArchiveResult>(`/api/tasks/${task.id}/${action}`, {
          method: 'POST',
        });
        fetchTasks();
      } catch (error) {
        setActionError(
          error instanceof Error
            ? error.message
            : 'Failed to update archive state',
        );
      } finally {
        setArchivingTaskId(null);
      }
    },
    [fetchTasks],
  );

  const setStatusFilter = useCallback((nextFilter: StatusFilter) => {
    setFilter(nextFilter);
    setOffset(0);
  }, []);

  const workflowOptions = Array.from(
    new Set([
      ...filterOptions.workflows,
      ...refinements.workflows,
      ...draftRefinements.workflows,
    ]),
  ).sort();
  const originOptions = Array.from(
    new Set([
      ...filterOptions.origins,
      ...refinements.origins,
      ...draftRefinements.origins,
    ]),
  )
    .sort()
    .map((channel) => ({ value: channel, label: channelLabel(channel) }));
  const refinementCount =
    refinements.workflows.length + refinements.origins.length;

  function openFilters() {
    setDraftRefinements(refinements);
    setWorkflowSearch('');
    setFiltersOpen(true);
  }

  function toggleDraftRefinement(key: keyof TaskRefinements, value: string) {
    setDraftRefinements((current) => ({
      ...current,
      [key]: current[key].includes(value)
        ? current[key].filter((item) => item !== value)
        : [...current[key], value],
    }));
  }

  function applyRefinements() {
    setRefinements(draftRefinements);
    setOffset(0);
    setFiltersOpen(false);
  }

  function clearRefinements() {
    const emptyRefinements = { workflows: [], origins: [] };
    setDraftRefinements(emptyRefinements);
    setRefinements(emptyRefinements);
    setOffset(0);
    setFiltersOpen(false);
  }

  function removeRefinement(key: keyof TaskRefinements, value: string) {
    setRefinements((current) => ({
      ...current,
      [key]: current[key].filter((item) => item !== value),
    }));
    setDraftRefinements((current) => ({
      ...current,
      [key]: current[key].filter((item) => item !== value),
    }));
    setOffset(0);
  }

  return (
    <div>
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <h1 className="font-display text-3xl font-normal tracking-tight text-[var(--color-text-primary)]">
          Tasks
        </h1>
        <div className="flex items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
            <input
              type="checkbox"
              checked={includeArchived}
              onChange={(event) => {
                setIncludeArchived(event.target.checked);
                setOffset(0);
              }}
              className="h-4 w-4 rounded border-ops-border bg-ops-surface"
            />
            Archived
          </label>
          <label className="inline-flex items-center gap-2 text-sm text-[var(--color-text-secondary)]">
            <input
              type="checkbox"
              checked={autoRefresh}
              onChange={(event) => setAutoRefresh(event.target.checked)}
              className="h-4 w-4 rounded border-ops-border bg-ops-surface"
            />
            Auto refresh
          </label>
          <button
            onClick={fetchTasks}
            className="px-4 py-2 bg-ops-surface border border-ops-border rounded-btn text-sm text-[var(--color-text-secondary)] hover:border-[var(--color-accent)]/30 hover:text-[var(--color-text-primary)] transition-all"
          >
            Refresh
          </button>
        </div>
      </div>

      <div className="mb-6 space-y-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {(
            [
              'all',
              'queued',
              'running',
              'waiting_approval',
              'waiting_user_input',
              'resume_pending',
              'succeeded',
              'failed',
              'lost',
              'timed_out',
            ] as StatusFilter[]
          ).map((s) => {
            const label: Record<string, string> = {
              timed_out: 'Timed Out',
              waiting_approval: 'Approval',
              waiting_user_input: 'User Input',
              resume_pending: 'Resume',
            };
            return (
              <button
                key={s}
                type="button"
                onClick={() => setStatusFilter(s)}
                className={`rounded-btn px-3 py-1.5 text-sm transition-all ${
                  filter === s
                    ? 'bg-[var(--color-accent)] text-white'
                    : 'border border-ops-border bg-ops-surface text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]'
                }`}
              >
                {label[s] || s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            );
          })}

          <div ref={desktopFiltersRef} className="relative hidden md:block">
            <button
              type="button"
              onClick={openFilters}
              aria-expanded={filtersOpen}
              aria-controls="task-refinements"
              className={`inline-flex items-center gap-1.5 rounded-btn border px-3 py-1.5 text-sm transition-colors ${
                refinementCount > 0
                  ? 'border-[var(--color-accent)]/30 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                  : 'border-ops-border bg-ops-surface text-[var(--color-text-tertiary)] hover:text-[var(--color-text-primary)]'
              }`}
            >
              <Filter size={14} aria-hidden="true" />
              Filters
              {refinementCount > 0 && <span>{refinementCount} selected</span>}
            </button>
            {filtersOpen && (
              <div
                id="task-refinements"
                className="absolute right-0 z-30 mt-2 w-80 animate-[task-filter-popover-in_160ms_ease-out] border border-ops-border bg-ops-surface p-4 shadow-card-hover"
              >
                <TaskRefinementForm
                  workflowOptions={workflowOptions}
                  originOptions={originOptions}
                  draftRefinements={draftRefinements}
                  workflowSearch={workflowSearch}
                  onWorkflowSearchChange={setWorkflowSearch}
                  onToggle={toggleDraftRefinement}
                  onApply={applyRefinements}
                  onClear={clearRefinements}
                />
              </div>
            )}
          </div>

          <button
            type="button"
            onClick={openFilters}
            aria-expanded={filtersOpen}
            aria-controls="task-refinements-mobile"
            className={`inline-flex items-center gap-1.5 rounded-btn border px-3 py-1.5 text-sm transition-colors md:hidden ${
              refinementCount > 0
                ? 'border-[var(--color-accent)]/30 bg-[var(--color-accent)]/10 text-[var(--color-accent)]'
                : 'border-ops-border bg-ops-surface text-[var(--color-text-tertiary)]'
            }`}
          >
            <Filter size={14} aria-hidden="true" />
            Filters
            {refinementCount > 0 && <span>{refinementCount}</span>}
          </button>
        </div>

        {refinementCount > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            {refinements.workflows.map((workflow) => (
              <AppliedFilterChip
                key={`workflow-${workflow}`}
                label={`Workflow: ${workflow}`}
                onRemove={() => removeRefinement('workflows', workflow)}
              />
            ))}
            {refinements.origins.map((origin) => (
              <AppliedFilterChip
                key={`origin-${origin}`}
                label={`Origin: ${channelLabel(origin)}`}
                onRemove={() => removeRefinement('origins', origin)}
              />
            ))}
            <button
              type="button"
              onClick={clearRefinements}
              className="px-1.5 py-1 text-xs text-[var(--color-text-tertiary)] transition-colors hover:text-[var(--color-text-primary)]"
            >
              Clear all
            </button>
          </div>
        )}
      </div>

      {filtersOpen && (
        <div className="md:hidden">
          <button
            type="button"
            aria-label="Close filters"
            className="fixed inset-0 z-40 bg-black/25 animate-[task-filter-fade-in_160ms_ease-out]"
            onClick={() => setFiltersOpen(false)}
          />
          <section
            id="task-refinements-mobile"
            aria-label="Task filters"
            className="fixed inset-x-0 bottom-0 z-50 max-h-[85vh] overflow-y-auto rounded-t-btn border border-b-0 border-ops-border bg-ops-surface p-5 shadow-card-hover animate-[task-filter-sheet-in_180ms_ease-out]"
          >
            <div className="mx-auto mb-5 h-1 w-10 rounded-full bg-[var(--color-border-subtle)]" />
            <TaskRefinementForm
              workflowOptions={workflowOptions}
              originOptions={originOptions}
              draftRefinements={draftRefinements}
              workflowSearch={workflowSearch}
              onWorkflowSearchChange={setWorkflowSearch}
              onToggle={toggleDraftRefinement}
              onApply={applyRefinements}
              onClear={clearRefinements}
            />
          </section>
        </div>
      )}

      {actionError && (
        <div className="mb-4 rounded-btn border border-[var(--color-error)]/30 bg-[var(--color-error-muted)] px-4 py-3 text-sm text-[var(--color-error)]">
          {actionError}
        </div>
      )}

      {/* Task Table */}
      {loading ? (
        <p className="text-[var(--color-text-tertiary)]">Loading tasks...</p>
      ) : (
        <div className="bg-ops-surface border border-ops-border rounded-card overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-ops-border text-left text-sm text-[var(--color-text-tertiary)]">
                <th className="px-4 py-3 font-medium">Task ID</th>
                <th className="px-4 py-3 font-medium">Workflow</th>
                <th className="px-4 py-3 font-medium">Origin</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Tokens</th>
                <th className="px-4 py-3 font-medium hidden sm:table-cell">
                  Created
                </th>
                <th className="px-4 py-3 font-medium hidden md:table-cell">
                  Duration
                </th>
                <th className="px-4 py-3"></th>
              </tr>
            </thead>
            <tbody>
              {tasks.map((task) => {
                const createdAt = new Date(task.created);
                const origin = deriveOrigin(task);

                return (
                  <tr
                    key={task.id}
                    className="border-b border-ops-border/50 hover:bg-ops-surface-raised/50 transition-colors"
                  >
                    <td className="px-4 py-3 font-mono text-sm text-[var(--color-text-secondary)]">
                      {task.id.slice(0, 8)}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-primary)]">
                      {task.workflow}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-tertiary)]">
                      <span
                        className="inline-flex items-center gap-1"
                        title={origin.label}
                      >
                        <origin.icon
                          aria-hidden="true"
                          size={14}
                          strokeWidth={1.8}
                        />
                        <span className="hidden lg:inline">{origin.label}</span>
                      </span>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${statusColor(task.status)}`}
                      >
                        {task.status}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-secondary)]">
                      {task.tokens_used.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-tertiary)] hidden sm:table-cell">
                      {createdAt.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-sm text-[var(--color-text-tertiary)] hidden md:table-cell">
                      {formatDuration(task.duration_sec)}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        {RERUNNABLE_STATUSES.has(task.status) && (
                          <ActionIconButton
                            label={
                              rerunningTaskId === task.id
                                ? 'Requeueing task'
                                : 'Rerun task'
                            }
                            title={
                              rerunningTaskId === task.id
                                ? 'Requeueing…'
                                : 'Rerun task'
                            }
                            tone="amber"
                            disabled={
                              rerunningTaskId === task.id ||
                              deletingTaskId === task.id
                            }
                            onClick={() => rerunTask(task)}
                          >
                            <ReplayIcon
                              spinning={rerunningTaskId === task.id}
                            />
                          </ActionIconButton>
                        )}
                        <ActionIconLink
                          label="View session"
                          title="View session"
                          tone="blue"
                          href={`/tasks/${task.id}`}
                        >
                          <EyeIcon />
                        </ActionIconLink>
                        <ActionIconButton
                          label={
                            task.archived_at ? 'Unarchive task' : 'Archive task'
                          }
                          title={
                            task.archived_at ? 'Unarchive task' : 'Archive task'
                          }
                          tone="blue"
                          disabled={
                            archivingTaskId === task.id ||
                            deletingTaskId === task.id ||
                            rerunningTaskId === task.id
                          }
                          onClick={() => archiveTask(task)}
                        >
                          <ArchiveIcon
                            open={Boolean(task.archived_at)}
                            spinning={archivingTaskId === task.id}
                          />
                        </ActionIconButton>
                        <ActionIconButton
                          label={
                            deletingTaskId === task.id
                              ? 'Deleting task'
                              : 'Delete task'
                          }
                          title={
                            deletingTaskId === task.id
                              ? 'Deleting…'
                              : 'Delete task'
                          }
                          tone="rose"
                          disabled={
                            deletingTaskId === task.id ||
                            rerunningTaskId === task.id
                          }
                          onClick={() => deleteTask(task)}
                        >
                          <TrashIcon spinning={deletingTaskId === task.id} />
                        </ActionIconButton>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {tasks.length === 0 && (
                <tr>
                  <td
                    colSpan={8}
                    className="px-4 py-12 text-center text-[var(--color-text-tertiary)]"
                  >
                    No tasks found
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
      <div className="mt-4 flex items-center justify-between text-sm text-[var(--color-text-tertiary)]">
        <span>
          {total === 0
            ? '0 tasks'
            : `${offset + 1}-${Math.min(offset + PAGE_SIZE, total)} of ${total}`}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
            className="px-3 py-1.5 rounded-btn border border-ops-border bg-ops-surface disabled:opacity-40"
          >
            Previous
          </button>
          <button
            type="button"
            disabled={offset + PAGE_SIZE >= total}
            onClick={() => setOffset(offset + PAGE_SIZE)}
            className="px-3 py-1.5 rounded-btn border border-ops-border bg-ops-surface disabled:opacity-40"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

function TaskRefinementForm({
  workflowOptions,
  originOptions,
  draftRefinements,
  workflowSearch,
  onWorkflowSearchChange,
  onToggle,
  onApply,
  onClear,
}: {
  workflowOptions: string[];
  originOptions: Array<{ value: string; label: string }>;
  draftRefinements: TaskRefinements;
  workflowSearch: string;
  onWorkflowSearchChange: (value: string) => void;
  onToggle: (key: keyof TaskRefinements, value: string) => void;
  onApply: () => void;
  onClear: () => void;
}) {
  const visibleWorkflows = workflowOptions.filter((workflow) =>
    workflow.toLowerCase().includes(workflowSearch.toLowerCase()),
  );
  const selectedCount =
    draftRefinements.workflows.length + draftRefinements.origins.length;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        onApply();
      }}
    >
      <div className="mb-4 flex items-center justify-between">
        <h2 className="font-display text-lg font-normal text-[var(--color-text-primary)]">
          Filters
        </h2>
        <span className="text-xs text-[var(--color-text-tertiary)]">
          {selectedCount === 0 ? 'None selected' : `${selectedCount} selected`}
        </span>
      </div>

      <fieldset>
        <legend className="mb-2 text-xs font-medium text-[var(--color-text-secondary)]">
          Workflow
        </legend>
        <label className="relative mb-2 block">
          <Search
            size={14}
            aria-hidden="true"
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--color-text-tertiary)]"
          />
          <input
            type="search"
            value={workflowSearch}
            onChange={(event) => onWorkflowSearchChange(event.target.value)}
            placeholder="Search workflows"
            className="w-full rounded-btn border border-ops-border bg-ops-surface py-2 pl-8 pr-3 text-sm text-[var(--color-text-primary)] placeholder:text-[var(--color-text-tertiary)]"
          />
        </label>
        <div className="max-h-32 space-y-1 overflow-y-auto pr-1">
          {visibleWorkflows.map((workflow) => (
            <FilterCheckbox
              key={workflow}
              checked={draftRefinements.workflows.includes(workflow)}
              label={workflow}
              onChange={() => onToggle('workflows', workflow)}
            />
          ))}
          {visibleWorkflows.length === 0 && (
            <p className="px-2 py-1 text-xs text-[var(--color-text-tertiary)]">
              No workflows found
            </p>
          )}
        </div>
      </fieldset>

      <fieldset className="mt-4 border-t border-ops-border pt-4">
        <legend className="mb-2 text-xs font-medium text-[var(--color-text-secondary)]">
          Origin
        </legend>
        <div className="space-y-1">
          {originOptions.map((origin) => (
            <FilterCheckbox
              key={origin.value}
              checked={draftRefinements.origins.includes(origin.value)}
              label={origin.label}
              onChange={() => onToggle('origins', origin.value)}
            />
          ))}
        </div>
      </fieldset>

      <div className="mt-5 flex items-center justify-between gap-3 border-t border-ops-border pt-4">
        <button
          type="button"
          onClick={onClear}
          className="text-sm text-[var(--color-accent)] transition-colors hover:text-[var(--color-accent-hover)]"
        >
          Clear
        </button>
        <button
          type="submit"
          className="min-w-24 rounded-btn bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
        >
          Apply
        </button>
      </div>
    </form>
  );
}

function FilterCheckbox({
  checked,
  label,
  onChange,
}: {
  checked: boolean;
  label: string;
  onChange: () => void;
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 rounded-btn px-2 py-1.5 text-sm text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-surface-raised)]">
      <input
        type="checkbox"
        checked={checked}
        onChange={onChange}
        className="h-3.5 w-3.5 rounded border-ops-border bg-ops-surface accent-[var(--color-accent)]"
      />
      <span className="min-w-0 truncate">{label}</span>
    </label>
  );
}

function AppliedFilterChip({
  label,
  onRemove,
}: {
  label: string;
  onRemove: () => void;
}) {
  return (
    <span className="inline-flex max-w-full items-center gap-1 rounded-btn bg-[var(--color-accent)]/10 py-1 pl-2 pr-1 text-xs text-[var(--color-accent)]">
      <span className="truncate">{label}</span>
      <button
        type="button"
        aria-label={`Remove ${label} filter`}
        onClick={onRemove}
        className="inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full transition-colors hover:bg-[var(--color-accent)]/20"
      >
        <X size={12} aria-hidden="true" />
      </button>
    </span>
  );
}

function ActionIconButton({
  children,
  disabled,
  label,
  onClick,
  title,
  tone,
}: {
  children: React.ReactNode;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  title: string;
  tone: 'blue' | 'amber' | 'rose';
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={title}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-9 w-9 items-center justify-center rounded-btn border transition-all hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-40 ${actionToneClasses[tone]}`}
    >
      {children}
    </button>
  );
}

function ActionIconLink({
  children,
  href,
  label,
  title,
  tone,
}: {
  children: React.ReactNode;
  href: string;
  label: string;
  title: string;
  tone: 'blue' | 'amber' | 'rose';
}) {
  return (
    <a
      aria-label={label}
      title={title}
      href={href}
      className={`inline-flex h-9 w-9 items-center justify-center rounded-btn border transition-all hover:-translate-y-0.5 ${actionToneClasses[tone]}`}
    >
      {children}
    </a>
  );
}

const actionToneClasses = {
  blue: 'border-[var(--color-info)]/20 bg-[var(--color-info-muted)] text-[var(--color-info)] hover:bg-[var(--color-info)]/20 hover:text-[var(--color-text-primary)]',
  amber:
    'border-[var(--color-warning)]/20 bg-[var(--color-warning-muted)] text-[var(--color-warning)] hover:bg-[var(--color-warning)]/20 hover:text-[var(--color-text-primary)]',
  rose: 'border-[var(--color-error)]/20 bg-[var(--color-error-muted)] text-[var(--color-error)] hover:bg-[var(--color-error)]/20 hover:text-[var(--color-text-primary)]',
} as const;

function EyeIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

function ReplayIcon({ spinning = false }: { spinning?: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={spinning ? 'animate-spin' : ''}
    >
      <polyline points="23 4 23 10 17 10" />
      <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  );
}

function TrashIcon({ spinning = false }: { spinning?: boolean }) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={spinning ? 'animate-pulse' : ''}
    >
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <line x1="10" y1="11" x2="10" y2="17" />
      <line x1="14" y1="11" x2="14" y2="17" />
    </svg>
  );
}

function ArchiveIcon({
  open = false,
  spinning = false,
}: {
  open?: boolean;
  spinning?: boolean;
}) {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={spinning ? 'animate-pulse' : ''}
    >
      <rect x="3" y="4" width="18" height="4" rx="1" />
      <path d="M5 8v10a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8" />
      {open ? <path d="M9 14h6" /> : <path d="M10 12h4" />}
    </svg>
  );
}
