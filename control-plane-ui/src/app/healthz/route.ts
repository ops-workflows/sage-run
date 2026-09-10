import { NextResponse } from 'next/server';

const DEFAULT_GATEWAY_URL = 'http://gateway:8080';
const HEALTH_CHECK_TIMEOUT_MS = 2_000;

export async function GET(): Promise<Response> {
  const gatewayUrl = process.env.INTERNAL_GATEWAY_URL || DEFAULT_GATEWAY_URL;

  try {
    const response = await fetch(new URL('/health', gatewayUrl), {
      cache: 'no-store',
      signal: AbortSignal.timeout(HEALTH_CHECK_TIMEOUT_MS),
    });

    if (response.ok) {
      return NextResponse.json(
        { status: 'healthy' },
        { headers: { 'Cache-Control': 'no-store' } },
      );
    }
  } catch {}

  return NextResponse.json(
    { status: 'unhealthy' },
    { status: 503, headers: { 'Cache-Control': 'no-store' } },
  );
}
