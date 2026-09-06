import type { Analytics } from '@/lib/api';

export function getMockAnalytics(
  startDateStr?: string,
  endDateStr?: string,
): Analytics {
  const now = new Date();
  const reqStart = startDateStr
    ? new Date(`${startDateStr}T00:00:00Z`)
    : new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
  const reqEnd = endDateStr ? new Date(`${endDateStr}T23:59:59Z`) : now;

  // Capped at now so future dates are never generated
  const endTime = Math.min(reqEnd.getTime(), now.getTime());
  const end = new Date(endTime);

  // If viewing current month/year, ensure start is the 1st of the current month
  let startTime: number;
  if (
    end.getUTCFullYear() === now.getUTCFullYear() &&
    end.getUTCMonth() === now.getUTCMonth()
  ) {
    startTime = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1);
  } else {
    startTime = Date.UTC(reqStart.getUTCFullYear(), reqStart.getUTCMonth(), 1);
  }

  const daily_counts: Array<{ date: string; count: number }> = [];
  const current = new Date(
    Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()),
  );

  // Generate descending order: latest day first down to start of month
  while (current.getTime() >= startTime) {
    const dateStr = current.toISOString().slice(0, 10);
    const dayOfWeek = current.getUTCDay();
    const dayOfMonth = current.getUTCDate();
    const isWeekend = dayOfWeek === 0 || dayOfWeek === 6;
    const count = isWeekend
      ? 16 + (dayOfMonth % 8)
      : 42 + ((dayOfMonth * 7) % 24);

    daily_counts.push({ date: dateStr, count });
    current.setUTCDate(current.getUTCDate() - 1);
  }

  // Safety fallback if range produced zero entries
  if (daily_counts.length === 0) {
    const fallbackDate = new Date().toISOString().slice(0, 10);
    daily_counts.push({ date: fallbackDate, count: 48 });
  }

  const totalMonthlyTasks =
    daily_counts.reduce((sum, d) => sum + d.count, 0) || 1248;
  const failedTasks = Math.max(1, Math.round(totalMonthlyTasks * 0.032));
  const succeededTasks = totalMonthlyTasks - failedTasks;

  return {
    total_tasks: totalMonthlyTasks,
    succeeded: succeededTasks,
    failed: failedTasks,
    avg_duration_sec: 38.2,
    total_tokens: totalMonthlyTasks * 2280,
    tasks_by_workflow: {
      'cloud-incident-investigator': Math.round(totalMonthlyTasks * 0.44),
      'online-platform-triage': Math.round(totalMonthlyTasks * 0.29),
      'enterprise-crm-investigator': Math.round(totalMonthlyTasks * 0.17),
      'daily-operations-digest': Math.round(totalMonthlyTasks * 0.07),
      'weekly-reflection-and-learning': Math.max(
        1,
        Math.round(totalMonthlyTasks * 0.03),
      ),
    },
    tokens_by_workflow: {
      'cloud-incident-investigator': Math.round(
        totalMonthlyTasks * 2280 * 0.45,
      ),
      'online-platform-triage': Math.round(totalMonthlyTasks * 2280 * 0.3),
      'enterprise-crm-investigator': Math.round(
        totalMonthlyTasks * 2280 * 0.17,
      ),
      'weekly-reflection-and-learning': Math.round(
        totalMonthlyTasks * 2280 * 0.05,
      ),
      'daily-operations-digest': Math.round(totalMonthlyTasks * 2280 * 0.03),
    },
    tasks_by_status: {
      succeeded: succeededTasks,
      failed: failedTasks,
    },
    daily_counts,
  };
}

export const MOCK_ANALYTICS: Analytics = getMockAnalytics();
