import { handleMockApiRequest } from '@/mock-data';

export function initMockAdapter() {
  const originalFetch = window.fetch.bind(window);

  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(
      typeof input === 'string' || input instanceof URL ? input : input.url,
      window.location.href,
    );
    if (!url.pathname.startsWith('/api/')) return originalFetch(input, init);

    const method = (init?.method || 'GET').toUpperCase();
    if (method !== 'GET') {
      return new Response(
        JSON.stringify({ detail: 'Standalone export is read-only' }),
        {
          status: 405,
          headers: { 'Content-Type': 'application/json' },
        },
      );
    }

    const { status, data } = await handleMockApiRequest(
      method,
      url.pathname.slice('/api/'.length).split('/').filter(Boolean),
      url.searchParams,
    );
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  };
}
