/**
 * A typed `fetch` wrapper over the generated contract types. It adds no shapes
 * of its own: every response type is `components['schemas'][…]` via `@/contracts`.
 *
 * The app is served from one origin in both dev (Vite proxy) and prod (nginx),
 * so every path here is relative and there is no CORS story.
 */
import type { Problem } from '@/contracts';

export class ApiError extends Error {
  readonly status: number;
  readonly problem: Problem | null;

  constructor(status: number, message: string, problem: Problem | null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.problem = problem;
  }
}

export type QueryValue = string | number | boolean | null | undefined;
export type QueryParams = Record<string, QueryValue | readonly QueryValue[]>;

/** Build a query string, dropping `null`/`undefined` and repeating arrays. */
export function buildQuery(params: QueryParams | undefined): string {
  if (!params) return '';
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined) continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item !== null && item !== undefined) search.append(key, String(item));
      }
    } else {
      search.append(key, String(value));
    }
  }
  const query = search.toString();
  return query === '' ? '' : `?${query}`;
}

export type RequestOptions = {
  params?: QueryParams;
  signal?: AbortSignal;
};

async function request<T>(
  method: 'GET' | 'POST' | 'PUT',
  path: string,
  options: RequestOptions & { body?: unknown } = {},
): Promise<T> {
  const init: RequestInit = { method, headers: { Accept: 'application/json' } };
  if (options.body !== undefined) {
    init.headers = { ...init.headers, 'Content-Type': 'application/json' };
    init.body = JSON.stringify(options.body);
  }
  if (options.signal) init.signal = options.signal;

  const response = await fetch(`${path}${buildQuery(options.params)}`, init);
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

async function toApiError(response: Response): Promise<ApiError> {
  let problem: Problem | null = null;
  try {
    const body: unknown = await response.json();
    if (typeof body === 'object' && body !== null && 'title' in body) {
      problem = body as Problem;
    }
  } catch {
    // A non-JSON error body is still an error; the status carries the meaning.
  }
  const message =
    problem?.detail ?? problem?.title ?? `${response.status} ${response.statusText}`;
  return new ApiError(response.status, message, problem);
}

export const apiGet = <T>(path: string, options?: RequestOptions): Promise<T> =>
  request<T>('GET', path, options ?? {});

export const apiPost = <T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<T> => request<T>('POST', path, { ...(options ?? {}), body });

export const apiPut = <T>(
  path: string,
  body: unknown,
  options?: RequestOptions,
): Promise<T> => request<T>('PUT', path, { ...(options ?? {}), body });
