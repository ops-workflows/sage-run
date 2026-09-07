import { usePathname } from './navigation';

import Home from '@/app/page';
import WorkflowsPage from '@/app/workflows/page';
import AgentDetailPage from '@/app/workflows/[name]/page';
import QueuePage from '@/app/tasks/page';
import SessionDetailPage from '@/app/tasks/[taskId]/page';
import SchedulesPage from '@/app/schedules/page';
import McpPage from '@/app/mcp/page';
import ConnectorsPage from '@/app/connectors/page';
import ApprovalsPage from '@/app/approvals/page';
import MemoryPage from '@/app/memory/page';
import BackgroundJobsPage from '@/app/background-jobs/page';
import KnowledgeSourcesPage from '@/app/knowledge-sources/page';
import KnowledgeSourceDetailPage from '@/app/knowledge-sources/[sourceId]/page';
import AnalyticsPage from '@/app/analytics/page';

export function RouteRenderer() {
  const pathname = usePathname();

  if (pathname === '/' || pathname === '') {
    return <Home />;
  }
  if (pathname === '/workflows') {
    return <WorkflowsPage />;
  }
  if (pathname.startsWith('/workflows/')) {
    return <AgentDetailPage />;
  }
  if (pathname === '/tasks') {
    return <QueuePage />;
  }
  if (pathname.startsWith('/tasks/')) {
    return <SessionDetailPage />;
  }
  if (pathname === '/schedules') {
    return <SchedulesPage />;
  }
  if (pathname === '/mcp') {
    return <McpPage />;
  }
  if (pathname === '/connectors') {
    return <ConnectorsPage />;
  }
  if (pathname === '/approvals') {
    return <ApprovalsPage />;
  }
  if (pathname === '/memory') {
    return <MemoryPage />;
  }
  if (pathname === '/background-jobs') {
    return <BackgroundJobsPage />;
  }
  if (pathname === '/knowledge-sources') {
    return <KnowledgeSourcesPage />;
  }
  if (pathname.startsWith('/knowledge-sources/')) {
    return <KnowledgeSourceDetailPage />;
  }
  if (pathname === '/analytics') {
    return <AnalyticsPage />;
  }
  if (pathname === '/platform') {
    window.location.hash = '#/';
    return <Home />;
  }

  return (
    <div className="py-12 text-center">
      <h2 className="text-xl font-medium text-[var(--color-text-primary)]">
        Page Not Found
      </h2>
      <p className="mt-2 text-sm text-[var(--color-text-secondary)]">
        The requested path &ldquo;{pathname}&rdquo; was not recognized.
      </p>
      <div className="mt-6">
        <a
          href="#/"
          className="inline-flex items-center rounded-btn bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90"
        >
          Return to Overview
        </a>
      </div>
    </div>
  );
}
