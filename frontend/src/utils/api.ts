// API client: base URL, auth header, error normalisation and session expiry.

import { getToken, redirectToLogin, removeToken } from './auth';

export const API_BASE_URL: string = (import.meta.env.PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

export class ApiError extends Error {
  status: number;
  /** Field-level validation messages from FastAPI 422 responses, keyed by field name. */
  fields: Record<string, string>;

  constructor(message: string, status: number, fields: Record<string, string> = {}) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.fields = fields;
  }
}

interface ValidationIssue {
  loc?: (string | number)[];
  msg?: string;
}

function cleanMessage(msg: string): string {
  // Pydantic prefixes custom validator errors with "Value error, ".
  return msg.replace(/^Value error,\s*/i, '');
}

async function toApiError(response: Response): Promise<ApiError> {
  let detail: unknown;
  try {
    detail = (await response.json())?.detail;
  } catch {
    detail = undefined;
  }
  if (typeof detail === 'string') return new ApiError(detail, response.status);
  if (Array.isArray(detail)) {
    const fields: Record<string, string> = {};
    for (const issue of detail as ValidationIssue[]) {
      const key = issue.loc?.[issue.loc.length - 1];
      if (key !== undefined && issue.msg) fields[String(key)] = cleanMessage(issue.msg);
    }
    const first = Object.values(fields)[0];
    return new ApiError(first ?? 'Please check the highlighted fields.', response.status, fields);
  }
  if (response.status >= 500) return new ApiError('Something went wrong on our side. Please try again.', response.status);
  return new ApiError(`Request failed (${response.status}).`, response.status);
}

export interface FetchOptions extends RequestInit {
  requiresAuth?: boolean;
}

export async function apiFetch<T>(endpoint: string, options: FetchOptions = {}): Promise<T> {
  const { requiresAuth = false, headers = {}, ...rest } = options;
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  const requestHeaders: Record<string, string> = {
    Accept: 'application/json',
    ...(rest.body ? { 'Content-Type': 'application/json' } : {}),
    ...(headers as Record<string, string>),
  };

  if (requiresAuth) {
    const token = getToken();
    if (!token) {
      redirectToLogin();
      throw new ApiError('Please sign in to continue.', 401);
    }
    requestHeaders.Authorization = `Bearer ${token}`;
  }

  let response: Response;
  try {
    response = await fetch(url, { ...rest, headers: requestHeaders });
  } catch {
    throw new ApiError("Can't reach Shurly right now. Check your connection and try again.", 0);
  }

  if (response.status === 401 && requiresAuth) {
    removeToken();
    redirectToLogin('expired');
    throw new ApiError('Your session has expired. Please sign in again.', 401);
  }

  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function apiGet<T>(endpoint: string, requiresAuth = true): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'GET', requiresAuth });
}

export function apiPost<T>(endpoint: string, data?: unknown, requiresAuth = true): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'POST', body: JSON.stringify(data ?? {}), requiresAuth });
}

export function apiPatch<T>(endpoint: string, data: unknown, requiresAuth = true): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'PATCH', body: JSON.stringify(data), requiresAuth });
}

export function apiDelete<T = void>(endpoint: string, requiresAuth = true): Promise<T> {
  return apiFetch<T>(endpoint, { method: 'DELETE', requiresAuth });
}

/** Build a query string, skipping empty values and expanding arrays as repeated params. */
export function qs(params: Record<string, string | number | boolean | (string | number)[] | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    if (Array.isArray(value)) value.forEach((v) => search.append(key, String(v)));
    else search.append(key, String(value));
  }
  const s = search.toString();
  return s ? `?${s}` : '';
}

/** Download a file (e.g. CSV export) from an authenticated endpoint. */
export async function apiDownload(endpoint: string, fallbackName: string): Promise<void> {
  const token = getToken();
  const url = endpoint.startsWith('http') ? endpoint : `${API_BASE_URL}${endpoint}`;
  let response: Response;
  try {
    response = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  } catch {
    throw new ApiError("Can't reach Shurly right now. Check your connection and try again.", 0);
  }
  if (response.status === 401) {
    removeToken();
    redirectToLogin('expired');
    throw new ApiError('Your session has expired. Please sign in again.', 401);
  }
  if (!response.ok) throw await toApiError(response);

  const disposition = response.headers.get('content-disposition') ?? '';
  const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";]+)"?/i);
  const filename = match ? decodeURIComponent(match[1]) : fallbackName;
  saveBlob(await response.blob(), filename);
}

export function saveBlob(blob: Blob, filename: string): void {
  const href = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = href;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(href), 1000);
}

export function errorMessage(error: unknown, fallback = 'Something went wrong. Please try again.'): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
