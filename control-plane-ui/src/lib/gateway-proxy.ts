import type { NextRequest } from 'next/server';
import { handleMockApiRequest } from '@/mock-data';

const DEFAULT_GATEWAY_URL = 'http://gateway:8080';
const BODYLESS_METHODS = new Set(['GET', 'HEAD']);

export async function proxyGatewayRequest(
  request: NextRequest,
  prefix: 'api' | 'webhooks',
  path: string[],
): Promise<Response> {
  const isMock =
    process.env.USE_MOCKS === 'true' ||
    process.env.INTERNAL_GATEWAY_URL === 'mock';

  if (isMock && prefix === 'api') {
    let requestBody: unknown = undefined;
    if (!BODYLESS_METHODS.has(request.method)) {
      try {
        requestBody = await request.clone().json();
      } catch {
        // Body may not be JSON
      }
    }

    const { status, data } = await handleMockApiRequest(
      request.method,
      path,
      request.nextUrl.searchParams,
      requestBody,
    );
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  const gatewayUrl = process.env.INTERNAL_GATEWAY_URL || DEFAULT_GATEWAY_URL;
  const upstreamUrl = new URL(
    `/${prefix}/${path.map(encodeURIComponent).join('/')}`,
    gatewayUrl,
  );
  upstreamUrl.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete('host');
  headers.delete('content-length');

  return fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: BODYLESS_METHODS.has(request.method)
      ? undefined
      : await request.arrayBuffer(),
    redirect: 'manual',
    cache: 'no-store',
  });
}
