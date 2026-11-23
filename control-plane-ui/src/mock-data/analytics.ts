import type { Analytics } from '@/lib/api';
import { MOCK_TASKS } from './tasks';

export function getMockAnalytics(startDate = '', endDate = '9999-12-31'): Analytics {
  const tasks = MOCK_TASKS.filter((task) => {
    const date = task.created.slice(0, 10);
    return date >= startDate && date <= endDate;
  });
  const tasks_by_workflow: Record<string, number> = {};
  const tokens_by_workflow: Record<string, number> = {};
  const tasks_by_status: Record<string, number> = {};
  const countsByDay: Record<string, number> = {};
  let total_tokens = 0;
  let duration = 0;
  let completed = 0;
  for (const task of tasks) {
    const day = task.created.slice(0, 10);
    tasks_by_workflow[task.workflow] = (tasks_by_workflow[task.workflow] ?? 0) + 1;
    tokens_by_workflow[task.workflow] = (tokens_by_workflow[task.workflow] ?? 0) + task.tokens_used;
    tasks_by_status[task.status] = (tasks_by_status[task.status] ?? 0) + 1;
    countsByDay[day] = (countsByDay[day] ?? 0) + 1;
    total_tokens += task.tokens_used;
    if (task.duration_sec != null) {
      duration += task.duration_sec;
      completed++;
    }
  }
  return {
    total_tasks: tasks.length,
    succeeded: tasks_by_status.succeeded ?? 0,
    failed: tasks_by_status.failed ?? 0,
    avg_duration_sec: completed ? duration / completed : null,
    total_tokens,
    tasks_by_workflow,
    tasks_by_status,
    tokens_by_workflow,
    daily_counts: Object.entries(countsByDay).sort(([a], [b]) => b.localeCompare(a)).map(([date, count]) => ({ date, count })),
  };
}
