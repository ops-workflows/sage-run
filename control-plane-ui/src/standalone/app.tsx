import { HashNavigation } from './navigation';
import { ThemeProvider } from '@/components/theme-provider';
import { TopNav } from '@/components/top-nav';
import { RouteRenderer } from './router';

export function App() {
  return (
    <ThemeProvider>
      <HashNavigation />
      <div className="min-h-screen bg-ops-bg transition-colors">
        <TopNav />
        <main className="mx-auto max-w-6xl px-4 py-6 sm:px-6 md:px-8 md:py-10">
          <RouteRenderer />
        </main>
      </div>
    </ThemeProvider>
  );
}
