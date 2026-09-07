import type React from 'react';
import { useEffect, useState } from 'react';

function readRoute(): {
  pathname: string;
  params: Record<string, string>;
  searchParams: URLSearchParams;
} {
  const rawRoute = window.location.hash.slice(1) || '/';
  const [rawPath, rawQuery] = rawRoute.split('?');
  const pathname = rawPath.startsWith('/') ? rawPath : `/${rawPath}`;
  const searchParams = new URLSearchParams(rawQuery || '');
  const params: Record<string, string> = {};
  for (const [pattern, key] of [
    [/^\/workflows\/([^/?#]+)/, 'name'],
    [/^\/tasks\/([^/?#]+)/, 'taskId'],
    [/^\/knowledge-sources\/([^/?#]+)/, 'sourceId'],
  ] as const) {
    const match = pathname.match(pattern);
    if (match) params[key] = decodeURIComponent(match[1]);
  }
  return { pathname, params, searchParams };
}

function useRoute() {
  const [route, setRoute] = useState(readRoute);

  useEffect(() => {
    const update = () => setRoute(readRoute());
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);

  return route;
}

export function usePathname(): string {
  return useRoute().pathname;
}

export function useParams<
  T extends Record<string, string | string[]> = Record<string, string>,
>(): T {
  return useRoute().params as T;
}

export function useSearchParams(): URLSearchParams {
  return useRoute().searchParams;
}

export function redirect(url: string) {
  window.location.hash = url.startsWith('#') ? url : `#${url}`;
}

export function HashNavigation() {
  useEffect(() => {
    const intercept = (event: MouseEvent) => {
      const link = (event.target as Element).closest('a');
      const href = link?.getAttribute('href');
      if (
        !event.defaultPrevented &&
        event.button === 0 &&
        href?.startsWith('/')
      ) {
        event.preventDefault();
        window.location.hash = href;
      }
    };
    document.addEventListener('click', intercept);
    return () => document.removeEventListener('click', intercept);
  }, []);
  return null;
}

export function Link({
  href,
  children,
  className,
  title,
  ...rest
}: {
  href: string;
  children: React.ReactNode;
  className?: string;
  title?: string;
  [key: string]: unknown;
}) {
  const targetHref =
    href.startsWith('#') || href.startsWith('http') ? href : `#${href}`;

  return (
    <a href={targetHref} className={className} title={title} {...rest}>
      {children}
    </a>
  );
}
